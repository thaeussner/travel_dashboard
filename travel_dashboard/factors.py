"""Reference table of emission factors per passenger-km: each mode's default and each named vehicle.

The values come from the model itself (model.kg on a made-up reference row), so the table always
agrees with the dashboard: the central value from config/emissions.toml and the middle 90 % of the
Monte Carlo draws, at typical load, with the page's default switches. A flight's factor depends on
its distance (take-off and landing cost the same on any flight), so flights get one row per
reference distance. Shown on the Method page.
"""

from __future__ import annotations

import random

from .model import LENSES, kg, ship_breakdown
from .montecarlo import quantiles
from .profiles import Profile, Profiles, Sampler
from .tables import MODES, Travel

TITLES = {"train": "Train", "bus": "Local bus", "coach": "Coach", "ferry": "Ferry", "fast_ferry": "Fast ferry",
          "plane": "Plane", "car": "Car", "taxi": "Taxi", "sail": "Sailing yacht", "bike": "Bike", "walk": "Walk",
          "other": "Other"}
LENS_LABELS = {"passenger": "per passenger", "iso": "ISO 14083", "mass": "by mass",
               "co2": "CO₂ only", "full": "with non-CO₂"}
FLIGHT_KM = (400, 1000, 2500, 7000)   # short hop, medium, Zurich–Canaries, long-haul
TURBOPROP_KM = 300
REF_KM = 100.0                        # every other mode scales with distance, so any distance will do


def _num(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def basis(t: Travel, p: Profile, nonco2: str, named: bool = False) -> str:
    """What the factor is made of, with central values, in words (named rows already show the class)."""
    s = Sampler(None)
    g = lambda k: p.get(k, s)  # noqa: E731
    label = "" if named else f"{p.label[:1].upper()}{p.label[1:]}: "
    k = p.kind
    if k == "zero":
        return "No fuel burnt"
    if k == "factor":
        if g("seats") <= 1:
            return "Placeholder factor"
        return f"Published factor; typical load {_pct(g('lf'))} of {_num(g('seats'))} seats"
    if k == "vehicle":
        name = label if t.mode == "car" else ""
        return f"{name}{_num(g('g_vkm'))} g per vehicle-km ÷ {_num(g('occupancy'))} people"
    if k == "fuel":
        hours = f"; logged engine hours count {_num(g('l_per_engine_h'))} L each" if p.has("l_per_engine_h") else ""
        return (f"{_num(g('l_per_100km'))} L diesel per 100 km × {_num(g('fuel_factor'))} kg CO₂e/L "
                f"÷ {_num(g('occupancy'))} crew{hours}")
    if k == "ship":
        b = ship_breakdown(t, p, "typical")
        pax, *freight = b["groups"]
        load = " and ".join(f"{f['count']:.0f} {f['label']}" for f in freight)
        return (f"{_num(g('kg_fuel_nm'))} kg fuel per nautical mile; typical sailing {pax['count']:.0f} passengers"
                + (f", {load}" if load else ""))
    if k == "flight":
        cargo = f"; {_pct(g('cargo'))} of the fuel to belly freight" if g("cargo") else ""
        m = f"; non-CO₂ × {_num(g('nonco2'))}" if nonco2 == "full" else ""
        return (f"{label}{_num(g('lto_kg'))} kg fuel for take-off and landing "
                f"+ {_num(g('cruise_kg_km'))} kg/km, {_pct(g('uplift'))} detour; {_num(g('seats'))} seats, "
                f"{_pct(g('lf'))} full{cargo}{m}")
    return ""


def _row(profiles: Profiles, defaults: dict, draws: int, seed: int, *, group: str, title: str, mode: str,
         km: float = REF_KM, text: str = "", vehicle: dict | None = None, prefix: str = "") -> dict:
    t = Travel(id="ref", type="leg", from_="a", to="b", mode=mode, km=km, vehicle=text)
    p = profiles.resolve(t, vehicle)
    alloc, nonco2 = defaults.get("alloc", "iso"), defaults.get("nonco2", "full")

    def g_pkm(s: Sampler, a: str = alloc, n: str = nonco2) -> float:
        return kg(t, p, s, a, "typical", n) / km * 1000

    s = Sampler(random.Random(seed))
    vals = []
    for _ in range(draws):
        s.new_draw()
        vals.append(g_pkm(s))
    lo, _, hi = quantiles(vals)
    c = Sampler(None)
    if p.kind == "ship":
        other = [(LENS_LABELS[a], g_pkm(c, a=a)) for a in LENSES["alloc"] if a != alloc]
    elif p.kind == "flight":
        other = [(LENS_LABELS[n], g_pkm(c, n=n)) for n in LENSES["nonco2"] if n != nonco2]
    else:
        other = []
    return {
        "group": group, "title": title, "mode": mode, "profile": p.label,
        "basis": prefix + basis(t, p, nonco2, named=group == "named"), "g": round(g_pkm(c), 2), "range": [lo, hi],
        "other": [{"label": lab, "g": round(v, 2)} for lab, v in other],
        "grade": p.grade, "source": p.sources[0] if p.sources else "",
    }


def table(profiles: Profiles, defaults: dict, draws: int = 2000, seed: int = 1) -> dict:
    """Rows for the Method page: group 'default' (one per mode, flights per distance) and 'named'."""
    row = lambda **kw: _row(profiles, defaults, draws, seed, **kw)  # noqa: E731
    rows = []
    for mode in MODES:
        if mode not in profiles.modes:
            continue
        if profiles.modes[mode]["kind"] == "flight":
            rows += [row(group="default", title=f"{TITLES[mode]}, {km:,} km", mode=mode, km=km) for km in FLIGHT_KM]
        else:
            rows.append(row(group="default", title=TITLES.get(mode, mode), mode=mode))
    for v in profiles.vehicles:
        mode = v.get("mode", "")
        if mode in profiles.modes:
            rows.append(row(group="named", title=v["name"], mode=mode, vehicle=v, prefix=f"{TITLES.get(mode, mode)} · "))
    for key in profiles.cars.get("g_vkm", {}):
        size, fuel = key.split("_", 1)
        rows.append(row(group="named", title=f"{size.capitalize()} {fuel} car", mode="car", text=f"{size} {fuel}",
                        prefix="Car · "))
    if "turboprop" in profiles.flight:
        rows.append(row(group="named", title=f"Turboprop, {TURBOPROP_KM:,} km", mode="plane", km=TURBOPROP_KM,
                        text="turboprop", prefix="Plane · "))
    return {"alloc": defaults.get("alloc", "iso"), "nonco2": defaults.get("nonco2", "full"), "draws": draws,
            "rows": rows}
