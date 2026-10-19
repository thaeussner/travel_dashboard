"""Airports and great-circle distances, so flights can be entered by airport code instead of km.

data/reference/airports.csv is a filtered copy of OurAirports (public domain): every airport with
scheduled passenger service and an IATA code, with its country's name. Refresh it with
`python -m travel_dashboard airports`. The build also writes it to site/data/airports.json, so the
waypoint form can fill in the airports of a place as its name is typed.

A flight row (leg or alternative) may leave `km` empty. The build then takes the great-circle
distance between the airports at both ends:
- a waypoint id → the first code in that waypoint's `airport` column (e.g. la-palma → SPC)
- anything else → an IATA code in the text: "BCN", "Barcelona (BCN)" or "Barcelona El Prat BCN".
  An alternative may also start or end at another airport its waypoint lists, e.g. "TFN" for a
  waypoint with "TFS TFN"; trip.Resolver ties it to that waypoint.
The flight model adds its routing uplift on top, as for any flight distance.
"""

from __future__ import annotations

import csv
import io
import math
import re
import urllib.request
from pathlib import Path

from .tables import FUEL_MODES, Issue, Travel, Waypoint

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
COUNTRIES_URL = "https://davidmegginson.github.io/ourairports-data/countries.csv"
COLUMNS = ["iata", "name", "city", "country", "country_name", "lat", "lon", "type"]
TYPE_RANK = {"large": 0, "medium": 1, "small": 2}
EARTH_KM = 6371.0088
_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")


def great_circle_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "travel-dashboard (personal project)"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8")


def download_airports(dest: Path) -> int:
    """Rewrite dest from OurAirports. Returns the number of airports kept."""
    countries = {c["code"]: c["name"] for c in csv.DictReader(io.StringIO(_fetch(COUNTRIES_URL)))}
    kept = []
    for a in csv.DictReader(io.StringIO(_fetch(OURAIRPORTS_URL))):
        code = (a.get("iata_code") or "").strip().upper()
        if a.get("scheduled_service") != "yes" or len(code) != 3 or not code.isalpha():
            continue
        if a.get("type") not in ("large_airport", "medium_airport", "small_airport"):
            continue
        kept.append({
            "iata": code, "name": a.get("name", ""), "city": a.get("municipality", ""),
            "country": a.get("iso_country", ""), "country_name": countries.get(a.get("iso_country", ""), ""),
            "lat": f"{float(a['latitude_deg']):.4f}",
            "lon": f"{float(a['longitude_deg']):.4f}", "type": a.get("type", "").replace("_airport", ""),
        })
    best: dict[str, dict] = {}
    for a in kept:   # a few codes appear twice: keep the larger airport
        if a["iata"] not in best or TYPE_RANK[a["type"]] < TYPE_RANK[best[a["iata"]]["type"]]:
            best[a["iata"]] = a
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(best.values(), key=lambda a: a["iata"]))
    return len(best)


def load_airports(path: Path) -> dict[str, tuple[float, float]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r["iata"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)}


def airports_json(path: Path) -> dict:
    """The airport list for the waypoint form: code, name, city, country and size (0 = large)."""
    if not path.exists():
        return {"countries": {}, "airports": []}
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        "countries": {r["country"]: r.get("country_name", "") for r in rows},
        "airports": [[r["iata"], r["name"], r["city"], r["country"], TYPE_RANK.get(r["type"], 2)] for r in rows],
    }


def written_codes(text: str) -> list[str]:
    """IATA codes written in a from/to text: the whole text if it is three letters ("tfn"), else the
    upper-case codes in it ("Barcelona (BCN)")."""
    t = text.strip()
    if len(t) == 3 and t.isalpha():
        return [t.upper()]
    return [m.group(1) for m in _CODE.finditer(t)]


def airport_code(text: str, waypoint_airports: dict[str, str], airports: dict[str, tuple[float, float]]) -> str | None:
    """IATA code for a from/to value: a waypoint's (first) airport, or a code written in the text."""
    t = text.strip()
    if t.lower() in waypoint_airports:
        return waypoint_airports[t.lower()]
    return next((c for c in written_codes(t) if c in airports), None)


def fill_km(travel: list[Travel], waypoints: list[Waypoint], airports: dict[str, tuple[float, float]],
            detour: dict[str, float], issues: list[Issue]) -> list[Travel]:
    """Give flight rows their airport codes, and every row without km a distance.

    - Flights: the great-circle km between the airports at both ends.
    - Everything else: the straight line between the two places × the network's detour for the mode
      (config [distance]), when both places have coordinates.
    Rows that still have no km are skipped, except fuel-based ones (a yacht's litres or engine
    hours), which need no distance. Runs before trip.build, which replaces an alternative's end codes
    (e.g. "TFN") by waypoint ids."""
    wp_air: dict[str, str] = {}
    where: dict[str, tuple[float, float]] = {}
    for w in waypoints:
        if w.airports:
            wp_air[w.id.lower()] = w.airports[0]
            wp_air.setdefault(w.name.lower(), w.airports[0])
        if w.lat is not None and w.lon is not None:
            where[w.id.lower()] = (w.lat, w.lon)
            where.setdefault(w.name.lower(), (w.lat, w.lon))
    out: list[Travel] = []
    for t in travel:
        if t.mode == "plane":
            a, b = airport_code(t.from_, wp_air, airports), airport_code(t.to, wp_air, airports)
            t.from_code, t.to_code = a or "", b or ""
            if t.km is None:
                if not a or not b:
                    missing = t.from_ if not a else t.to
                    issues.append(Issue("travel", t.id, f"no km and no airport code for {missing!r}: give the waypoint "
                                                        "an airport or write a code like 'BCN'; row skipped", "error"))
                    continue
                t.km = round(great_circle_km(airports[a], airports[b]))
                t.km_note = f"great circle {a}–{b}"
        elif t.km is None:
            a, b = where.get(t.from_.strip().lower()), where.get(t.to.strip().lower())
            if a and b and a != b:
                line = great_circle_km(a, b)
                factor = detour.get(t.mode, 1.0)
                t.km = round(line * factor)
                t.km_note = f"estimated: {round(line):,} km straight line × {factor:g}"
            elif not (t.mode in FUEL_MODES and (t.fuel_l or t.engine_h)):
                issues.append(Issue("travel", t.id, "needs a distance in km (or places with coordinates, or the fuel "
                                                    "used); row skipped", "error"))
                continue
        out.append(t)
    return out
