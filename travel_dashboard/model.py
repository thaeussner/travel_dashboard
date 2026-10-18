"""Per-passenger emissions (kg CO2e) of one travel row, for one draw and one lens setting.

Every mode is modelled per vehicle and then divided by the passengers on board, so that the
occupancy lens works the same way everywhere:

- factor:  published g/pkm at the factor's typical load; observed load rescales it
- vehicle: car or taxi, g per vehicle-km (or litres of fuel) ÷ occupants
- fuel:    sailing yacht, litres of diesel ÷ crew
- ship:    fuel per nautical mile × distance, split between passengers and freight (alloc lens)
- flight:  take-off/landing fuel + cruise fuel × flown km, ÷ (seats × load factor), non-CO2 lens
"""

from __future__ import annotations

from .profiles import Profile, Sampler
from .tables import Travel

LENSES = {
    "alloc": ("passenger", "iso", "mass"),
    "occ": ("typical", "observed"),
    "nonco2": ("co2", "full"),
}
NM_KM = 1.852


def dims(t: Travel, p: Profile) -> tuple[str, ...]:
    """The lens dimensions that change this travel's value, in canonical order."""
    out = []
    if p.kind == "ship":
        out.append("alloc")
    if t.occ_obs and p.kind != "zero":
        out.append("occ")
    if p.kind == "flight":
        out.append("nonco2")
    return tuple(out)


def variant_key(dims_: tuple[str, ...], alloc: str, occ: str, nonco2: str) -> str:
    vals = {"alloc": alloc, "occ": occ, "nonco2": nonco2}
    return "|".join(vals[d] for d in dims_)


def ship_freight(p: Profile, s: Sampler) -> tuple[float, float]:
    """(passenger equivalents, tonnes) of the vehicles and freight on a typical sailing."""
    g = lambda k: p.get(k, s)  # noqa: E731
    if p.has("trailers"):
        peq = g("trailers") * g("trailer_peq") + g("cars") * g("car_peq")
        tonnes = g("trailers") * g("trailer_t") + g("cars") * g("car_t")
    elif p.has("vehicles"):
        ts = g("truck_share")
        peq = g("vehicles") * ((1 - ts) * g("car_peq") + ts * g("truck_peq"))
        tonnes = g("vehicles") * ((1 - ts) * g("car_t") + ts * g("truck_t"))
    else:
        peq = tonnes = 0.0
    return peq, tonnes


def ship_passengers(t: Travel, p: Profile, s: Sampler, occ: str) -> float:
    if occ == "observed" and t.occ_obs:
        return t.occ_obs
    if p.has("pax_typical"):
        return p.get("pax_typical", s)
    return (t.occ_max or p.get("seats", s)) * p.get("lf", s)


def allocate(e_ship: float, pax: float, veh_peq: float, veh_t: float, pax_t: float, alloc: str) -> float:
    if alloc == "passenger":   # everything on the passengers; cargo ignored
        return e_ship / pax
    if alloc == "iso":         # ISO 14083 Annex G passenger equivalents, 1 per passenger
        return e_ship / (pax + veh_peq)
    return e_ship * pax_t / (pax * pax_t + veh_t)   # by mass


def boat_litres(t: Travel, p: Profile, s: Sampler) -> float:
    """Litres for a boat: logged litres, else engine hours × consumption, else a default per km."""
    if t.fuel_l:
        return t.fuel_l
    if t.engine_h and p.has("l_per_engine_h"):
        return t.engine_h * p.get("l_per_engine_h", s)
    return p.get("l_per_100km", s) * (t.km or 0) / 100


def ship_breakdown(t: Travel, p: Profile, occ: str) -> dict | None:
    """How one sailing's emissions are split under each allocation method (central values).

    Used by the Method page to show what the ferry-share switch does with real numbers."""
    if p.kind != "ship":
        return None
    s = Sampler(None)
    g = lambda k: p.get(k, s)  # noqa: E731
    fuel_kg = g("kg_fuel_nm") * t.km / NM_KM
    e = fuel_kg * g("fuel_factor")
    pax = ship_passengers(t, p, s, occ)
    if p.has("trailers"):
        groups = [("cars", g("cars"), g("car_peq"), g("car_t")),
                  ("trucks and trailers", g("trailers"), g("trailer_peq"), g("trailer_t"))]
    elif p.has("vehicles"):
        n, ts = g("vehicles"), g("truck_share")
        groups = [("cars", n * (1 - ts), g("car_peq"), g("car_t")), ("trucks", n * ts, g("truck_peq"), g("truck_t"))]
    else:
        groups = []
    rows = [{"label": "passengers", "count": pax, "peq": pax, "t": pax * g("pax_t")}]
    rows += [{"label": lab, "count": c, "peq": c * pe, "t": c * tt} for lab, c, pe, tt in groups]
    tot_peq, tot_t = sum(r["peq"] for r in rows), sum(r["t"] for r in rows)
    shares = {"passenger": [1.0] + [0.0] * len(groups),
              "iso": [r["peq"] / tot_peq for r in rows],
              "mass": [r["t"] / tot_t for r in rows]}
    return {
        "fuel_t": round(fuel_kg / 1000, 2), "e_kg": round(e), "observed": occ == "observed" and bool(t.occ_obs),
        "groups": [{"label": r["label"], "count": round(r["count"], 1), "peq": round(r["peq"], 1), "t": round(r["t"], 1)}
                   for r in rows],
        "methods": {m: {"shares": [round(x, 4) for x in sh], "kg": round(e * sh[0] / pax, 1)}
                    for m, sh in shares.items()},
    }


def kg(t: Travel, p: Profile, s: Sampler, alloc: str = "iso", occ: str = "typical", nonco2: str = "full") -> float:
    g = lambda k: p.get(k, s)  # noqa: E731
    observed = occ == "observed" and bool(t.occ_obs)
    k = p.kind
    if k == "zero":
        return 0.0
    if k == "factor":
        per_pax = g("g_pkm") / 1000 * t.km
        if observed:
            typical_pax = (t.occ_max or g("seats")) * g("lf")
            return per_pax * typical_pax / t.occ_obs
        return per_pax
    if k == "vehicle":
        logged = bool(t.fuel_l) and p.has("fuel_factor")   # litres beat any factor (not for electric cars)
        e = t.fuel_l * g("fuel_factor") if logged else g("g_vkm") / 1000 * (t.km or 0)
        return e / (t.occ_obs if observed else g("occupancy"))
    if k == "fuel":
        return boat_litres(t, p, s) * g("fuel_factor") / (t.occ_obs if observed else g("occupancy"))
    if k == "ship":
        e = g("kg_fuel_nm") * t.km / NM_KM * g("fuel_factor")
        veh_peq, veh_t = ship_freight(p, s)
        return allocate(e, ship_passengers(t, p, s, occ), veh_peq, veh_t, g("pax_t"), alloc)
    if k == "flight":
        seats = t.occ_max or g("seats")
        lf = min(1.0, t.occ_obs / seats) if observed else g("lf")
        flown = t.km * (1 + g("uplift"))
        fuel = (g("lto_kg") + g("cruise_kg_km") * flown) * (1 - g("cargo")) / (seats * lf)
        m = g("nonco2") if nonco2 == "full" else 1.0
        return fuel * (g("co2_per_kg") * m + g("wtt"))
    raise ValueError(f"unknown profile kind {k!r}")


# ------------------------------------------------------------------------------- traces
def _n(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}"


def trace(t: Travel, p: Profile, alloc: str, occ: str, nonco2: str) -> str:
    """The calculation with central values, as a reader would check it by hand."""
    s = Sampler(None)
    g = lambda k: p.get(k, s)  # noqa: E731
    v = kg(t, p, s, alloc, occ, nonco2)
    observed = occ == "observed" and bool(t.occ_obs)
    k = p.kind
    if k == "zero":
        return f"{_n(t.km)} km by {t.mode}: no fuel burnt."
    if k == "factor":
        line = f"{_n(t.km)} km × {g('g_pkm'):.1f} g CO₂e/pkm ({p.label}, at its typical load)"
        if observed:
            seats = t.occ_max or g("seats")
            line += (f"\n× typical load {seats * g('lf'):.0f} of {seats:.0f} seats ÷ {t.occ_obs:.0f} observed")
        return f"{line}\n= {v:.1f} kg"
    if k == "vehicle":
        if t.fuel_l and p.has("fuel_factor"):
            e_txt = f"{_n(t.fuel_l, 1)} L × {g('fuel_factor'):.2f} kg CO₂e/L"
        else:
            e_txt = f"{_n(t.km or 0)} km × {g('g_vkm'):.0f} g CO₂e per vehicle-km"
        pax = t.occ_obs if observed else g("occupancy")
        return f"{e_txt}\n÷ {pax:.1f} {'people aboard (observed)' if observed else 'people (typical)'}\n= {v:.1f} kg"
    if k == "fuel":
        litres = boat_litres(t, p, s)
        if t.fuel_l:
            src = "logged"
        elif t.engine_h and p.has("l_per_engine_h"):
            src = f"{_n(t.engine_h, 1)} engine hours × {g('l_per_engine_h'):.1f} L/h"
        else:
            src = f"estimated at {g('l_per_100km'):.1f} L/100 km"
        crew = t.occ_obs if observed else g("occupancy")
        return (f"{_n(litres)} L fuel ({src}) × {g('fuel_factor'):.2f} kg CO₂e/L\n"
                f"÷ {crew:.1f} {'people aboard (observed)' if observed else 'people aboard (typical)'}\n= {v:.0f} kg")
    if k == "ship":
        fuel_kg = g("kg_fuel_nm") * t.km / NM_KM
        e = fuel_kg * g("fuel_factor")
        pax = ship_passengers(t, p, s, occ)
        veh_peq, veh_t = ship_freight(p, s)
        head = (f"Ship ({p.label}): {g('kg_fuel_nm'):.0f} kg fuel per nm × {t.km / NM_KM:.0f} nm = {fuel_kg / 1000:.1f} t\n"
                f"× {g('fuel_factor'):.2f} t CO₂e/t (well-to-wake) = {e / 1000:.1f} t CO₂e for the sailing\n")
        who = f"{pax:.0f} passengers ({'observed' if observed else 'typical'})"
        if alloc == "passenger":
            body = f"Per passenger, cargo ignored: ÷ {who} = {_n(v)} kg"
        elif alloc == "iso":
            body = (f"ISO 14083: {who} + {veh_peq:,.0f} passenger-equivalents for the vehicles and freight\n"
                    f"→ {e / 1000:.1f} t ÷ {pax + veh_peq:,.0f} = {v:.0f} kg per passenger")
        else:
            body = (f"By mass: {g('pax_t') * 1000:.0f} kg per passenger vs {veh_t:,.0f} t of vehicles and freight\n"
                    f"→ {v:.1f} kg per passenger ({who})")
        return head + body
    if k == "flight":
        seats = t.occ_max or g("seats")
        lf = min(1.0, t.occ_obs / seats) if observed else g("lf")
        flown = t.km * (1 + g("uplift"))
        fuel_total = (g("lto_kg") + g("cruise_kg_km") * flown) * (1 - g("cargo"))
        per_pax = fuel_total / (seats * lf)
        m = g("nonco2") if nonco2 == "full" else 1.0
        cargo = f" × {1 - g('cargo'):.0%} passenger share" if g("cargo") else ""
        src = f" ({t.km_note})" if t.km_note else ""
        return (f"{p.label}: {_n(t.km)} km great circle{src} + {g('uplift'):.0%} routing = {_n(flown)} km\n"
                f"fuel ({g('lto_kg'):.0f} kg take-off/landing + {g('cruise_kg_km'):.2f} kg/km × {_n(flown)} km){cargo}"
                f" = {_n(fuel_total)} kg\n"
                f"÷ ({seats:.0f} seats × {lf:.0%} {'observed' if observed else 'typical'} load) = {per_pax:.1f} kg fuel per passenger\n"
                f"× ({g('co2_per_kg'):.2f} kg CO₂ × {m:.1f} {'non-CO₂ multiplier' if nonco2 == 'full' else '(CO₂ only)'}"
                f" + {g('wtt'):.2f} kg upstream) = {v:.0f} kg")
    return f"{v:.1f} kg"
