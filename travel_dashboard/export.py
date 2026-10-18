"""Assemble the JSON files the static site reads (the data contract). Keep in sync with site/assets/*.js."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import costs as costs_mod
from . import factors, geo, montecarlo, trip as trip_mod
from .model import LENSES, ship_breakdown, trace
from .montecarlo import variants
from .profiles import Profiles, central
from .tables import COLUMNS, COST_CATEGORIES, MODES, Tables

GRADE_NOTES = {
    "A": "Fuel measured for this trip (litres you logged)",
    "B": "Specific to this vessel, service or trip (ship data, engine hours)",
    "C": "Operator, model or country-specific factor",
    "D": "Generic factor for the mode",
}

LENS_DEFS = {
    "level": {"title": "Compare against", "options": [
        {"id": "destination", "label": "Destinations",
         "hint": "Your alternatives between destinations",
         "explain": "Destinations: each journey between two destinations is compared with the alternative you marked "
                    "as main for it. Stops in between only exist because of how you travelled."},
        {"id": "stop", "label": "Every stop",
         "hint": "Use stop-level alternatives where you entered them",
         "explain": "Every stop: where you entered alternatives between stops that cover a whole journey, those are "
                    "used instead, usually more and shorter flights. Elsewhere the destination-level alternative "
                    "stays."},
        {"id": "direct", "label": "Direct",
         "hint": "Use alternatives that skip destinations, e.g. one flight Zurich → Martinique",
         "explain": "Direct: where you entered an alternative that skips destinations, it replaces everything in "
                    "between, local trips at the places it skips included. This asks what the trip cost against "
                    "flying straight there. Elsewhere the destination-level alternative stays."},
    ]},
    "alloc": {"title": "Ferry share", "options": [
        {"id": "passenger", "label": "Per passenger",
         "hint": "All of the ship's emissions divided by its passengers; freight ignored (upper bound)"},
        {"id": "iso", "label": "ISO 14083",
         "hint": "Passenger equivalents (ISO 14083 Annex G): car 1.3, trailer 14, truck 18 (recommended)"},
        {"id": "mass", "label": "By mass",
         "hint": "Split by mass: 100 kg per passenger vs 1.25 t per car, ~22 t per truck (as DESNZ)"},
    ]},
    "occ": {"title": "Occupancy", "options": [
        {"id": "typical", "label": "Typical", "hint": "Typical load factors everywhere"},
        {"id": "observed", "label": "As observed", "hint": "Your observed head count where you entered one"},
    ]},
    "nonco2": {"title": "Flights count", "options": [
        {"id": "co2", "label": "CO₂ only", "hint": "Fuel burnt plus fuel production"},
        {"id": "full", "label": "+ non-CO₂", "hint": "Adds contrails and NOx (multiplier ~1.7, range 1.2–3)"},
    ]},
}


def _iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def emissions_json(tables: Tables, profiles: Profiles, today: dt.date, draws: int, seed: int,
                   defaults: dict, airports: dict | None = None) -> dict:
    issues = tables.issues
    airports = airports or {}
    travel = geo.fill_flight_km(tables.travel, tables.waypoints, airports, issues)
    trip = trip_mod.build(tables.waypoints, travel, issues)
    mc = montecarlo.run(trip, profiles, today, draws, seed)
    prof, tdims = mc["profiles"], mc["dims"]

    def travel_out(t, planned: bool) -> dict:
        p = prof[t.id]
        vs = variants(tdims[t.id])
        return {
            "id": t.id, "type": t.type, "option": t.option, "main": t.main, "date": _iso(t.date),
            "from": t.from_, "to": t.to, "from_name": trip.name(t.from_), "to_name": trip.name(t.to),
            "mode": t.mode, "vehicle": t.vehicle, "km": t.km, "occ_max": t.occ_max, "occ_obs": t.occ_obs,
            "fuel_l": t.fuel_l, "note": t.note, "planned": planned, "local": t.is_leg and t.from_ == t.to,
            "km_note": t.km_note, "from_code": t.from_code or None, "to_code": t.to_code or None,
            "engine_h": t.engine_h,
            "ship": {o: ship_breakdown(t, p, o) for o in ("observed", "typical")} if p.kind == "ship" else None,
            "profile": p.label, "grade": p.grade, "grade_note": GRADE_NOTES[p.grade],
            "dims": list(tdims[t.id]), "q": mc["travel"][t.id],
            "trace": {vk: trace(t, p, *combo) for vk, combo in vs},
            "sources": p.sources,
        }

    journeys_out = {}
    option_planned: dict[str, bool] = {}
    for lvl in trip_mod.LEVELS:
        rows = []
        for ji, j in enumerate(trip.journeys[lvl]):
            planned = j.planned(today)
            for o in ([j.option] if j.option else []) + j.extras:
                option_planned[o.id] = option_planned.get(o.id, False) or planned
            rows.append({
                "start": j.start, "end": j.end, "title": f"{trip.name(j.start)} → {trip.name(j.end)}",
                "legs": [t.id for t in j.legs], "option": j.option.id if j.option else None,
                "extras": [o.id for o in j.extras], "date": _iso(j.date), "planned": planned, "skipped": j.skipped,
                "q": mc["journeys"][lvl][ji],
            })
        journeys_out[lvl] = rows

    return {
        "meta": {
            "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "today": today.isoformat(), "draws": draws, "seed": seed, "profiles_version": profiles.version,
            "counts": {"waypoints": len(trip.waypoints), "legs": len(trip.legs), "options": len(trip.options)},
        },
        "lenses": LENS_DEFS,
        "defaults": defaults,
        "waypoints": [{
            "id": w.id, "name": w.name, "type": w.type, "country": w.country, "arrive": _iso(w.arrive),
            "depart": _iso(w.depart), "note": w.note, "planned": bool(w.arrive and w.arrive > today),
            "airport": w.airport,
        } for w in trip.waypoints],
        "travels": [travel_out(t, bool(t.date and t.date > today)) for t in trip.legs]
                   + [travel_out(r, option_planned.get(o.id, True)) for o in trip.options for r in o.rows],
        "options": [{
            "id": o.id, "start": o.start, "end": o.end, "level": o.level, "main": o.main,
            "rows": [r.id for r in o.rows], "label": o.label, "planned": option_planned.get(o.id, True),
            "used": any(j["option"] == o.id for rows in journeys_out.values() for j in rows), "q": mc["option"][o.id],
        } for o in trip.options],
        "journeys": journeys_out,
        "local": mc["local"],
        "local_total": mc["local_total"],
        "totals": mc["totals"],
        "cumulative": mc["cumulative"],
        "issues": [i.as_dict() for i in issues if i.table != "costs"],
        "factors": factors.table(profiles, defaults, draws, seed),
    }


def costs_json(tables: Tables, today: dt.date) -> dict:
    out = costs_mod.build(tables.costs, today)
    out["meta"] = {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "today": today.isoformat()}
    out["issues"] = [i.as_dict() for i in tables.issues if i.table == "costs"]
    return out


def meta_json(settings: dict, profiles: Profiles | None = None) -> dict:
    site = settings.get("site", {})
    return {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "title": site.get("title", "Travel dashboard"),
        "repo": {"owner": site.get("owner", ""), "name": site.get("repo", ""), "branch": site.get("branch", "main"),
                 "data_dir": site.get("data_dir", "data")},
        "columns": COLUMNS,
        "categories": [{"id": c, "label": costs_mod.CATEGORY_LABELS[c]} for c in COST_CATEGORIES],
        "modes": list(MODES),
        "lenses": {k: list(v) for k, v in LENSES.items()},
        "vehicles": [{"name": v["name"], "mode": v.get("mode", "")} for v in (profiles.vehicles if profiles else [])],
        "profiles": profile_meta(profiles) if profiles else None,
    }


def profile_meta(profiles: Profiles) -> dict:
    """What the editor needs to show which data a vehicle name will match (display only, no maths)."""
    cars = profiles.cars
    return {
        "modes": {m: {"label": d.get("label", m), "grade": d.get("grade", "D"), "kind": d["kind"]}
                  for m, d in profiles.modes.items()},
        "vehicles": [{"name": v["name"], "mode": v.get("mode", ""), "match": v.get("match", []),
                      "grade": v.get("grade", "D"), "source": v.get("source", "")} for v in profiles.vehicles],
        "flight": {"classes": {k: {"label": v.get("label", k), "match": v.get("match", [])}
                               for k, v in profiles.flight.items() if isinstance(v, dict)},
                   "wide_from_km": profiles.flight.get("wide_from_km", 4000)},
        "cars": {"sizes": cars.get("sizes", {}), "fuels": cars.get("fuels", {}),
                 "size_default": cars.get("size_default", "average"), "fuel_default": cars.get("fuel_default", "petrol"),
                 "g_vkm": {k: central(v) for k, v in cars.get("g_vkm", {}).items()}, "source": cars.get("source", "")},
    }


def write(path: Path, data: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text)
