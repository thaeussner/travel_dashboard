"""Read and validate the three hand-edited CSV tables: costs, waypoints, travel.

Invalid rows never crash the build: they are fixed up where the intent is obvious, or skipped,
and every problem is reported as an Issue that ends up on the site.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

COST_CATEGORIES = (
    "groceries", "coffee", "treats", "activities", "accommodation", "transport", "restaurants", "other",
)
WAYPOINT_TYPES = ("stop", "destination")
TRAVEL_TYPES = ("leg", "alt")
MODES = (
    "train", "bus", "coach", "ferry", "fast_ferry", "plane", "car", "taxi", "sail", "bike", "walk", "other",
)

COLUMNS = {
    "costs": ["id", "date", "amount", "category", "country"],
    "waypoints": ["id", "name", "type", "country", "arrive", "depart", "note"],
    "travel": ["id", "type", "option", "main", "date", "from", "to", "mode", "vehicle", "km",
               "occ_max", "occ_obs", "fuel_l", "note"],
}


@dataclass
class Issue:
    table: str
    id: str
    message: str
    level: str = "warning"  # "warning": used with a fix-up; "error": row skipped

    def as_dict(self) -> dict:
        return {"table": self.table, "id": self.id, "message": self.message, "level": self.level}


@dataclass
class Cost:
    id: str
    date: dt.date
    amount: float
    category: str
    country: str


@dataclass
class Waypoint:
    id: str
    name: str
    type: str
    country: str = ""
    arrive: dt.date | None = None
    depart: dt.date | None = None
    note: str = ""


@dataclass
class Travel:
    id: str
    type: str
    from_: str
    to: str
    mode: str
    km: float
    option: str = ""
    main: bool = False
    date: dt.date | None = None
    vehicle: str = ""
    occ_max: float | None = None
    occ_obs: float | None = None
    fuel_l: float | None = None
    note: str = ""

    @property
    def is_leg(self) -> bool:
        return self.type == "leg"


@dataclass
class Tables:
    costs: list[Cost] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)
    travel: list[Travel] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


# ------------------------------------------------------------------ parsing helpers
def read_rows(path: Path) -> list[dict[str, str]]:
    """CSV rows as dicts with stripped keys and values. A missing file is an empty table."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for raw in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k is not None}
            if any(row.values()):
                rows.append(row)
        return rows


def parse_date(text: str) -> dt.date | None:
    text = text.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {text!r} (use YYYY-MM-DD)")


def parse_number(text: str) -> float | None:
    text = text.strip().replace("'", "").replace("’", "")
    if not text:
        return None
    if "," in text and "." not in text:  # 12,50 → 12.50
        text = text.replace(",", ".")
    text = text.replace(",", "")
    return float(text)


def parse_bool(text: str) -> bool:
    return text.strip().lower() in {"1", "true", "yes", "y", "x", "main"}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "item"


def _normalise_mode(text: str) -> str:
    m = text.strip().lower().replace(" ", "_").replace("-", "_")
    return {"fastferry": "fast_ferry", "hsc": "fast_ferry", "flight": "plane", "boat": "sail",
            "sailing": "sail", "ship": "ferry"}.get(m, m)


# ------------------------------------------------------------------ table readers
def read_costs(path: Path, issues: list[Issue]) -> list[Cost]:
    out: list[Cost] = []
    seen: set[str] = set()
    for n, row in enumerate(read_rows(path), start=1):
        rid = row.get("id") or f"row{n}"
        try:
            date = parse_date(row.get("date", ""))
            amount = parse_number(row.get("amount", ""))
        except ValueError as e:
            issues.append(Issue("costs", rid, f"{e}; row skipped", "error"))
            continue
        if date is None or amount is None:
            issues.append(Issue("costs", rid, "needs a date and an amount; row skipped", "error"))
            continue
        cat = row.get("category", "").lower()
        if cat == "coffe":
            cat = "coffee"
        if cat not in COST_CATEGORIES:
            issues.append(Issue("costs", rid, f"unknown category {cat!r}, counted as 'other'"))
            cat = "other"
        country = row.get("country", "")
        if not country:
            issues.append(Issue("costs", rid, "no country, counted as 'Unknown'"))
            country = "Unknown"
        if rid in seen:
            issues.append(Issue("costs", rid, "duplicate id; row kept"))
        seen.add(rid)
        out.append(Cost(rid, date, round(amount, 2), cat, country))
    return out


def read_waypoints(path: Path, issues: list[Issue]) -> list[Waypoint]:
    out: list[Waypoint] = []
    seen: set[str] = set()
    for n, row in enumerate(read_rows(path), start=1):
        name = row.get("name", "")
        rid = row.get("id") or slug(name or f"waypoint-{n}")
        if not name:
            issues.append(Issue("waypoints", rid, "needs a name; row skipped", "error"))
            continue
        if rid in seen:
            issues.append(Issue("waypoints", rid, "duplicate id; row skipped", "error"))
            continue
        wtype = row.get("type", "").lower()
        if wtype not in WAYPOINT_TYPES:
            issues.append(Issue("waypoints", rid, f"type {wtype!r} is not stop/destination; using 'stop'"))
            wtype = "stop"
        try:
            arrive = parse_date(row.get("arrive", ""))
            depart = parse_date(row.get("depart", ""))
        except ValueError as e:
            issues.append(Issue("waypoints", rid, f"{e}; row skipped", "error"))
            continue
        if arrive and depart and depart < arrive:
            issues.append(Issue("waypoints", rid, "depart is before arrive"))
        seen.add(rid)
        out.append(Waypoint(rid, name, wtype, row.get("country", ""), arrive, depart, row.get("note", "")))
    return out


def read_travel(path: Path, issues: list[Issue]) -> list[Travel]:
    out: list[Travel] = []
    seen: set[str] = set()
    for n, row in enumerate(read_rows(path), start=1):
        rid = row.get("id") or f"T{n:02d}"
        if rid in seen:
            issues.append(Issue("travel", rid, "duplicate id; row skipped", "error"))
            continue
        ttype = row.get("type", "").lower()
        if ttype not in TRAVEL_TYPES:
            issues.append(Issue("travel", rid, f"type {ttype!r} is not leg/alt; row skipped", "error"))
            continue
        mode = _normalise_mode(row.get("mode", ""))
        if mode not in MODES:
            issues.append(Issue("travel", rid, f"unknown mode {mode!r}, treated as 'other'"))
            mode = "other"
        try:
            km = parse_number(row.get("km", ""))
            date = parse_date(row.get("date", ""))
            occ_max = parse_number(row.get("occ_max", ""))
            occ_obs = parse_number(row.get("occ_obs", ""))
            fuel_l = parse_number(row.get("fuel_l", ""))
        except ValueError as e:
            issues.append(Issue("travel", rid, f"{e}; row skipped", "error"))
            continue
        if km is None or km <= 0:
            issues.append(Issue("travel", rid, "needs a distance in km; row skipped", "error"))
            continue
        frm, to = row.get("from", ""), row.get("to", "")
        if not frm or not to:
            issues.append(Issue("travel", rid, "needs from and to; row skipped", "error"))
            continue
        if ttype == "leg" and date is None:
            issues.append(Issue("travel", rid, "a leg needs a date; row skipped", "error"))
            continue
        for label, val in (("occ_max", occ_max), ("occ_obs", occ_obs)):
            if val is not None and val <= 0:
                issues.append(Issue("travel", rid, f"{label} must be positive; ignored"))
                if label == "occ_max":
                    occ_max = None
                else:
                    occ_obs = None
        if occ_max and occ_obs and occ_obs > occ_max:
            issues.append(Issue("travel", rid, "observed occupancy is above the maximum"))
        option = row.get("option", "")
        if ttype == "alt" and not option:
            option = rid
        seen.add(rid)
        out.append(Travel(
            id=rid, type=ttype, from_=frm, to=to, mode=mode, km=km, option=option,
            main=parse_bool(row.get("main", "")), date=date, vehicle=row.get("vehicle", ""),
            occ_max=occ_max, occ_obs=occ_obs, fuel_l=fuel_l, note=row.get("note", ""),
        ))
    return out


def read_all(data_dir: Path) -> Tables:
    t = Tables()
    t.costs = read_costs(data_dir / "costs.csv", t.issues)
    t.waypoints = read_waypoints(data_dir / "waypoints.csv", t.issues)
    t.travel = read_travel(data_dir / "travel.csv", t.issues)
    return t
