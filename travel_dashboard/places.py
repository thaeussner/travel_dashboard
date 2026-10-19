"""Places: the populated places (and islands, bays, harbours) of the countries the trip may visit.

data/reference/places/<CC>.csv is made from the GeoNames per-country dumps (CC BY 4.0) by
`python -m travel_dashboard places [CC ...]`; countries.csv lists the countries. Each place carries
its nearest airports, so a waypoint picked from the list knows its coordinates and airports. The
waypoint form searches these lists; the build fills in waypoints entered without coordinates.
"""

from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .geo import great_circle_km
from .tables import Issue, Waypoint

GEONAMES = "https://download.geonames.org/export/dump/"
EUROPE = ("AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GB GG GI GR HR HU IE IM IS IT JE LI LT LU LV "
          "MC MD ME MK MT NL NO PL PT RO RS SE SI SJ SK SM UA VA XK").split()
AMERICAS = ("CA US MX GL PM BM BZ CR SV GT HN NI PA AG AI AW BB BL BQ BS CU CW DM DO GD GP HT JM KN KY LC MF MQ "
            "MS PR SX TC TT VC VG VI AR BO BR CL CO EC FK GF GY PE PY SR UY VE").split()
DEFAULT = EUROPE + AMERICAS          # Russia and Turkey (mostly in Asia, huge lists) are left out for now
FULL_LIMIT = 40_000    # larger countries keep only towns of 500+ people or administrative seats
POPULATED = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLF", "PPLG", "PPLR", "PPLS"}
SEATS = {"PPLC": "C", "PPLA": "A", "PPLA2": "A", "PPLA3": "A", "PPLA4": "A"}
WATER = {"ISL": "I", "ISLS": "I", "BAY": "H", "ANCH": "H", "MRN": "H", "HBR": "H"}
KIND_RANK = {"C": 0, "A": 1, "I": 2, "P": 3, "H": 4}   # capital, admin seat, island, place, harbour or bay
COLUMNS = ["name", "region", "lat", "lon", "kind", "population", "airports", "alt"]
AIRPORT_KM = 150       # airports within this distance count as the place's own
_LATIN = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿĀ-ž' .\-]+$")


def fold(text: str) -> str:
    """Lower case without accents or punctuation, for matching ("El Médano" → "el medano")."""
    t = unicodedata.normalize("NFD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


@dataclass
class Place:
    name: str
    country: str          # ISO code
    region: str
    lat: float
    lon: float
    kind: str
    population: int = 0
    airports: list[str] = field(default_factory=list)
    alt: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return ", ".join(x for x in (self.name, self.region) if x)


# ------------------------------------------------------------------------------ download
def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "travel-dashboard (personal project)"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def nearest_airports(lat: float, lon: float, country: str, index: dict, n: int = 3) -> list[str]:
    """The place's own airports: those in its country within AIRPORT_KM, plus foreign ones closer than
    any of those (Hendaye gets San Sebastián across the border; Le Marin not St Lucia across the sea).
    Without any nearby, the nearest airport of the country within 400 km."""
    def around(km: float) -> list[tuple[float, str, str]]:
        dlat = math.ceil(km / 111) + 1
        dlon = min(30, math.ceil(km / (111 * max(0.1, math.cos(math.radians(lat))))) + 1)
        out = []
        for di in range(-dlat, dlat + 1):
            for dj in range(-dlon, dlon + 1):
                for code, cc, alat, alon in index.get((math.floor(lat) + di, math.floor(lon) + dj), ()):
                    d = great_circle_km((lat, lon), (alat, alon))
                    if d <= km:
                        out.append((d, code, cc))
        return sorted(out)

    cands = around(AIRPORT_KM)
    home = [c for c in cands if c[2] == country]
    limit = home[0][0] if home else AIRPORT_KM
    own = [c for c in cands if c[2] == country or c[0] < limit]
    if not own:
        far = around(400)
        own = [c for c in far if c[2] == country][:1] or far[:1]
    return [code for _d, code, _cc in own[:n]]


def airport_index(airports_csv: Path) -> dict:
    index: dict[tuple[int, int], list] = defaultdict(list)
    with airports_csv.open(encoding="utf-8", newline="") as f:
        for a in csv.DictReader(f):
            lat, lon = float(a["lat"]), float(a["lon"])
            index[(math.floor(lat), math.floor(lon))].append((a["iata"], a["country"], lat, lon))
    return index


def _alt_names(raw: str, name: str) -> list[str]:
    seen, out = {fold(name)}, []
    for a in raw.split(","):
        a = a.strip()
        if 2 < len(a) <= 30 and _LATIN.match(a) and fold(a) not in seen:
            seen.add(fold(a))
            out.append(a)
    return out[:3]


def download(dest: Path, countries: list[str], airports_csv: Path, log=print) -> dict[str, int]:
    """Rewrite dest/<CC>.csv for each country, and dest/countries.csv. Returns places per country."""
    dest.mkdir(parents=True, exist_ok=True)
    admin1: dict[str, str] = {}
    for line in _fetch(GEONAMES + "admin1CodesASCII.txt").decode("utf-8").splitlines():
        code, name, *_ = line.split("\t")
        admin1[code] = name
    info = {}
    for line in _fetch(GEONAMES + "countryInfo.txt").decode("utf-8").splitlines():
        if line and not line.startswith("#"):
            c = line.split("\t")
            info[c[0]] = {"code": c[0], "name": c[4], "continent": c[8]}
    index = airport_index(airports_csv)
    counts: dict[str, int] = {}
    for cc in countries:
        with zipfile.ZipFile(io.BytesIO(_fetch(f"{GEONAMES}{cc}.zip"))) as z:
            text = z.read(f"{cc}.txt").decode("utf-8")
        rows = [line.split("\t") for line in text.splitlines() if line]
        populated = [r for r in rows if r[6] == "P" and r[7] in POPULATED]
        full = len(populated) <= FULL_LIMIT
        keep = []
        for r in populated:
            pop = int(r[14] or 0)
            if full or pop >= 500 or r[7] in SEATS:
                keep.append((r, SEATS.get(r[7], "P"), pop))
        if full:
            keep += [(r, WATER[r[7]], int(r[14] or 0)) for r in rows if r[7] in WATER]
        out = []
        for r, kind, pop in keep:
            lat, lon = round(float(r[4]), 4), round(float(r[5]), 4)
            important = kind in ("C", "A", "I") or pop >= 20_000
            out.append({
                "name": r[1], "region": admin1.get(f"{cc}.{r[10]}", ""), "lat": lat, "lon": lon, "kind": kind,
                "population": pop or "", "airports": " ".join(nearest_airports(lat, lon, cc, index)),
                "alt": "|".join(_alt_names(r[3], r[1])) if important else "",
            })
        out.sort(key=lambda p: (fold(p["name"]), p["region"]))
        with (dest / f"{cc}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(out)
        counts[cc] = len(out)
        log(f"  {cc} {info.get(cc, {}).get('name', '?')}: {len(out):,} places{'' if full else ' (towns of 500+ and seats)'}")
    existing = load_countries(dest)
    for cc in countries:
        existing[cc] = {**info.get(cc, {"code": cc, "name": cc, "continent": ""}), "places": counts[cc]}
    with (dest / "countries.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "continent", "places"], lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(existing.values(), key=lambda c: c["code"]))
    return counts


# ------------------------------------------------------------------------------ lookup
def load_countries(dest: Path) -> dict[str, dict]:
    path = dest / "countries.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {c["code"]: c for c in csv.DictReader(f)}


class Places:
    """The place lists, loaded per country on first use."""

    def __init__(self, dest: Path):
        self.dest = dest
        self.countries = load_countries(dest)
        self._by_name = {fold(c["name"]): code for code, c in self.countries.items()}
        self._cache: dict[str, list[Place]] = {}

    def country_code(self, text: str) -> str | None:
        t = (text or "").strip()
        if t.upper() in self.countries:
            return t.upper()
        return self._by_name.get(fold(t))

    def of(self, cc: str) -> list[Place]:
        if cc not in self._cache:
            path = self.dest / f"{cc}.csv"
            rows = []
            if path.exists():
                with path.open(encoding="utf-8", newline="") as f:
                    for r in csv.DictReader(f):
                        rows.append(Place(r["name"], cc, r["region"], float(r["lat"]), float(r["lon"]), r["kind"],
                                          int(r["population"] or 0), r["airports"].split(), [a for a in r["alt"].split("|") if a]))
            self._cache[cc] = rows
        return self._cache[cc]

    def find(self, name: str, country: str = "") -> list[Place]:
        """Places called `name` (or with it as another name), best first: capitals and seats, then
        islands, then places by population. Searches the country if given, else every country."""
        key = fold(name)
        cc = self.country_code(country)
        pool = self.of(cc) if cc else [p for c in self.countries for p in self.of(c)]
        hits = [p for p in pool if fold(p.name) == key] or [p for p in pool if key in (fold(a) for a in p.alt)]
        return sorted(hits, key=lambda p: (KIND_RANK.get(p.kind, 5), -p.population))


def locate(waypoints: list[Waypoint], places: Places | None, issues: list[Issue]) -> None:
    """Fill in coordinates (and airports, when none are given) of waypoints entered without them."""
    if not places or not places.countries:
        return
    for w in waypoints:
        if w.lat is not None and w.lon is not None:
            continue
        hits = places.find(w.name, w.country)
        if not hits and w.country:      # e.g. "Le Marin", France: the place is listed under Martinique
            hits = places.find(w.name)
        if not hits:
            issues.append(Issue("waypoints", w.id, f"no place called {w.name!r} in the place lists; pick it in the "
                                                   "waypoint form to put it on the map"))
            continue
        best = hits[0]
        w.lat, w.lon = best.lat, best.lon
        if not w.airport:
            w.airport = " ".join(best.airports)
        if len(hits) > 1 and KIND_RANK.get(hits[1].kind, 5) == KIND_RANK.get(best.kind, 5):
            others = "; ".join(p.label for p in hits[1:3])
            issues.append(Issue("waypoints", w.id, f"placed at {best.label}; also possible: {others}. Pick it in the "
                                                   "waypoint form if that is wrong"))


# ------------------------------------------------------------------------------ browser
def browser_json(dest: Path, cc: str) -> dict:
    """One country's places for the waypoint form: regions once, then compact rows
    [name, region index, lat, lon, kind, population, airports, other names]."""
    rows, regions = [], {}
    path = dest / f"{cc}.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                ri = regions.setdefault(r["region"], len(regions))
                rows.append([r["name"], ri, float(r["lat"]), float(r["lon"]), r["kind"], int(r["population"] or 0),
                             r["airports"], r["alt"]])
    return {"country": cc, "regions": list(regions), "places": rows}
