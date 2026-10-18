"""Throwaway spike: illustrative numbers for prototype/emissions-mockup.html.

Models a *plausible* version of the trip (route, dates and vessels are guesses, not logged data)
with the method lenses and shared-parameter Monte Carlo described in docs/PLAN.md §6, then injects
the results into the mockup page. It exists so the mockup's charts are internally consistent.
It is NOT the real engine; see docs/METHODOLOGY.md for the actual method and sources.

Pure standard library on purpose:   python prototype/mock_model.py
"""

from __future__ import annotations

import json
import math
import random
import re
from array import array
from itertools import product
from pathlib import Path

HERE = Path(__file__).parent
DRAWS = 4000
SEED = 20261018
TODAY = "2026-10-18"

GRAINS = ("regions", "destinations", "stops")
ALLOCS = ("passenger", "iso", "mass")
OCCS = ("typical", "observed")
NONCO2 = ("co2", "full")
SCOPES = ("todate", "planned")

# --------------------------------------------------------------------------------------------
# Parameters: (low, mode, high) of a triangular distribution. Units in the comments.
# Values are illustrative and loosely based on the sources collected in METHODOLOGY.md.
# --------------------------------------------------------------------------------------------
P = {
    # rail, kg CO2e per passenger-km, well-to-wheel (location-based electricity at the high end)
    "rail_lyria": (0.0010, 0.0025, 0.0060),     # SNCF Info GES 2025: Lyria 2.5; CH/FR location-based high end
    "rail_fr_tgv": (0.0014, 0.0023, 0.0050),    # SNCF: TGV INOUI 2.3; ADEME 2.93 incl. rolling stock
    "rail_es": (0.0036, 0.011, 0.025),          # Renfe market-based 3.6; ES grid ~150 g/kWh location-based
    "rail_es_hsr": (0.0036, 0.008, 0.018),      # AVE: lighter per seat than Alvia; same grid logic
    # coach, kg CO2e per passenger-km
    "coach": (0.025, 0.032, 0.048),             # FlixBus Iberia 27; DESNZ 2025 34 WTW; DESNZ 2026 higher
    # ---- ferries: ship emissions per sailing x allocation lens x occupancy lens ----
    "mgo_wtw": (3.80, 3.88, 3.95),             # t CO2e per t MGO, WTW (IMO 4th GHG 3.206 + FuelEU WTT)
    "hfo_wtw": (3.55, 3.68, 3.88),             # t CO2e per t residual fuel / VLSFO, WTW
    "pax_mass_t": (0.08, 0.10, 0.10),          # passenger + luggage (DESNZ 0.10, EN 16258 0.08)
    # Huelva - Las Palmas - Santa Cruz de Tenerife ro-pax (Marie Curie / Buenavista Express type)
    "ropax_kg_nm": (145, 170, 257),            # EU MRV 2024-25: Sicilia 145-162, Marie Curie 170, Volcan de Tinamar 245-257
    "ropax_nm": (725, 739, 760),               # Huelva-LPA 691 nm + LPA-TFE 48 nm
    "ropax_pax_typ": (90, 160, 300),           # ~9,000 passengers in Jun+Jul 2026 on the line
    "ropax_trailers": (60, 100, 150),          # freight units per sailing
    "ropax_cars": (20, 50, 90),
    "trailer_peq": (14, 15, 18),               # ISO 14083 Annex G: unaccompanied trailer 14, artic truck 18
    "trailer_t": (18.0, 22.2, 26.0),           # DESNZ freight unit incl. vehicle 22.17 t
    # Fred. Olsen fast-ferry line Los Cristianos - Santa Cruz de La Palma (Bencomo Express)
    "hsc_kg_nm": (130, 145, 170),              # EU MRV: 139 kg/nm (2024), 145 (2025)
    "hsc_nm": (66, 68, 70),                    # operator: 68 nm, 2 h 30 min
    "hsc_pax_typ": (230, 260, 300),            # MRV-derived average 252-267 aboard (29-31 % of 859)
    "hsc_pax_obs": (120, 150, 190),            # observed: "only ~150 on board"
    "hsc_vehicles": (40, 75, 110),             # line average 0.29 vehicles per passenger
    "truck_share": (0.02, 0.05, 0.10),         # share of vehicles that are trucks
    # ---- flights: per-flight fuel model  fuel = LTO + cruise_per_km * flown_km ----
    "route_uplift": (0.04, 0.08, 0.12),        # flown distance over great circle (DESNZ +8 %)
    "jet_seats": (174, 180, 186),              # A320 family as flown to the Canaries
    "jet_lf": (0.80, 0.85, 0.92),              # IATA 2025 European carriers 84 %; SWISS group 83 %
    "jet_lto_kg": (550, 750, 950),
    "jet_cruise_kg_km": (2.4, 2.7, 3.0),
    "wide_seats": (300, 350, 430),             # A350/A330neo in leisure layouts (Paris-Antilles)
    "wide_lf": (0.78, 0.83, 0.88),
    "wide_lto_kg": (1800, 2200, 2700),
    "wide_cruise_kg_km": (6.0, 6.8, 7.6),
    "wide_cargo": (0.06, 0.12, 0.20),          # share of fuel allocated to belly freight
    "tp_seats": (70, 72, 72),                  # Binter ATR 72-600
    "tp_lf": (0.60, 0.72, 0.85),
    "tp_lto_kg": (140, 190, 250),
    "tp_cruise_kg_km": (1.25, 1.45, 1.70),
    "jet_co2": (3.16, 3.16, 3.16),             # kg CO2 per kg jet fuel burnt (ICAO)
    "jet_wtt": (0.50, 0.54, 0.65),             # kg CO2e per kg jet fuel, upstream (myclimate P = 0.538)
    "nonco2_jet": (1.2, 1.7, 3.0),             # Lee et al. 2021: GWP100 1.7; GWP*/ERF ~3
    "nonco2_short": (1.0, 1.3, 2.0),           # jets under 500 km spend less of the flight at cruise altitude
    "nonco2_tp": (1.0, 1.1, 1.4),              # turboprops cruise low: contrails rarely form
    # sailing yacht: litres of diesel for the whole crossing, crew size, kg CO2e per litre WTW
    "sail_fuel_l": (50, 150, 400),              # no published average; ARC survey: ~3 h/day charging
    "sail_crew": (4, 5.5, 7),                   # ARC 2025: ~5.5 crew per boat
    "diesel_wtw": (3.25, 3.29, 3.40),           # DESNZ 2025: diesel 3.29, MGO 3.40 kg CO2e/L WTW
}

# --------------------------------------------------------------------------------------------
# Illustrative itinerary
# --------------------------------------------------------------------------------------------
STOPS = [
    dict(id="zrh", short="Zürich", region="CH", kind="home", caption="start", kind_label="home", arrive=None),
    dict(id="hen", short="Hendaye", region="FR", kind="transit", caption="1 night", kind_label="transit", arrive="2026-09-26"),
    dict(id="mad", short="Madrid", region="ES", kind="transit", caption="1 night", kind_label="transit", arrive="2026-09-27"),
    dict(id="tf1", short="Tenerife", region="Canaries", kind="destination", caption="12 nights", kind_label="destination", arrive="2026-09-30"),
    dict(id="lp", short="La Palma", region="Canaries", kind="destination", caption="5 nights", kind_label="destination", arrive="2026-10-12"),
    dict(id="tf2", short="Tenerife", region="Canaries", kind="destination", caption="since 17 Oct", kind_label="destination", arrive="2026-10-17"),
    dict(id="mq", short="Martinique", region="Antilles", kind="destination", caption="Dec", kind_label="planned", arrive="2026-12-12", planned=True),
]

LEGS = [
    dict(id="L1", date="2026-09-26", seg="zrh-hen", title="Zürich → Paris", short="Zürich → Paris", mode="train",
         mode_label="TGV Lyria", service="SBB/SNCF TGV Lyria", km=610, km_note="rail distance, est.", grade="C",
         model="rail_lyria"),
    dict(id="L2", date="2026-09-26", seg="zrh-hen", title="Paris → Hendaye", short="Paris → Hendaye", mode="train",
         mode_label="TGV", service="SNCF TGV inOui", km=790, km_note="rail distance, est.", grade="C",
         model="rail_fr_tgv"),
    dict(id="L3", date="2026-09-27", seg="hen-mad", title="Irun → Madrid", short="Irun → Madrid", mode="train",
         mode_label="Alvia", service="Renfe Alvia", km=640, km_note="rail distance, est.", grade="C", model="rail_es"),
    dict(id="L4", date="2026-09-28", seg="mad-tf1", title="Madrid → Sevilla", short="Madrid → Sevilla", mode="train",
         mode_label="AVE", service="Renfe AVE", km=471, km_note="timetable km", grade="C", model="rail_es_hsr"),
    dict(id="L5", date="2026-09-28", seg="mad-tf1", title="Sevilla → Huelva", short="Sevilla → Huelva", mode="coach",
         mode_label="coach", service="intercity coach", km=95, km_note="road distance", grade="D", model="coach"),
    dict(id="L6", date="2026-09-28", seg="mad-tf1", title="Huelva → Santa Cruz de Tenerife",
         short="Huelva → Tenerife", mode="ferry", mode_label="ro-pax ferry", service="conventional ro-pax (illustrative)",
         km=1370, km_note="739 nm via Las Palmas", grade="D", model="ropax"),
    dict(id="L7", date="2026-10-12", seg="tf1-lp", title="Los Cristianos → Santa Cruz de La Palma",
         short="Tenerife → La Palma", mode="ferry_fast", mode_label="fast ferry",
         service="Fred. Olsen line (vessel not logged)", km=126, km_note="68 nm", grade="C", model="hsc_line"),
    dict(id="L8", date="2026-10-17", seg="lp-tf2", title="Santa Cruz de La Palma → Los Cristianos",
         short="La Palma → Tenerife", mode="ferry_fast", mode_label="fast ferry", service="Fred. Olsen · Bencomo Express",
         km=126, km_note="68 nm", grade="B", model="hsc", observed="~150 passengers on board"),
    dict(id="L9", date="2026-11-22", seg="tf2-mq", title="Tenerife → Martinique", short="Tenerife → Martinique",
         mode="sail", mode_label="sailing yacht", service="crew on a 45 ft yacht", km=5300, km_note="trade-wind route, est.",
         grade="C", model="sail", planned=True),
]

SEGMENTS = [
    dict(id="zrh-hen", from_stop="zrh", to_stop="hen", label="TGV ×2", title="Zürich → Hendaye"),
    dict(id="hen-mad", from_stop="hen", to_stop="mad", label="Alvia", title="Hendaye → Madrid"),
    dict(id="mad-tf1", from_stop="mad", to_stop="tf1", label="AVE · coach · ferry", title="Madrid → Tenerife"),
    dict(id="tf1-lp", from_stop="tf1", to_stop="lp", label="fast ferry", title="Tenerife → La Palma"),
    dict(id="lp-tf2", from_stop="lp", to_stop="tf2", label="fast ferry", title="La Palma → Tenerife"),
    dict(id="tf2-mq", from_stop="tf2", to_stop="mq", label="sailing", title="Tenerife → Martinique", planned=True),
]

# flight legs: (from, to, great-circle km, aircraft class)
FLIGHTS = {
    "ZRH-TFS": ("ZRH", "TFS", 3063, "jet"),
    "TFN-SPC": ("TFN", "SPC", 139, "tp"),
    "SPC-TFN": ("SPC", "TFN", 139, "tp"),
    "TFS-ORY": ("TFS", "ORY", 2814, "jet"),
    "ORY-FDF": ("ORY", "FDF", 6852, "wide"),
    "ZRH-BIQ": ("ZRH", "BIQ", 901, "jet"),
    "BIQ-MAD": ("BIQ", "MAD", 373, "jet"),
    "MAD-TFN": ("MAD", "TFN", 1771, "jet"),
}

# journeys per grain: (from_stop, to_stop, flight chain, label, note)
J = {
    "regions": [
        ("zrh", "tf1", ["ZRH-TFS"], "ZRH–TFS", "Edelweiss, daily A320"),
        ("tf2", "mq", ["TFS-ORY", "ORY-FDF"], "TFS–ORY–FDF", "no nonstop from the Canaries; via Orly"),
    ],
    "destinations": [
        ("zrh", "tf1", ["ZRH-TFS"], "ZRH–TFS", "Edelweiss, daily A320"),
        ("tf1", "lp", ["TFN-SPC"], "TFN–SPC", "Binter ATR 72-600, ~30 min"),
        ("lp", "tf2", ["SPC-TFN"], "SPC–TFN", "Binter ATR 72-600, ~30 min"),
        ("tf2", "mq", ["TFS-ORY", "ORY-FDF"], "TFS–ORY–FDF", "no nonstop from the Canaries; via Orly"),
    ],
    "stops": [
        ("zrh", "hen", ["ZRH-BIQ"], "ZRH–BIQ", "Edelweiss, seasonal direct"),
        ("hen", "mad", ["BIQ-MAD"], "BIQ–MAD", "assumed direct"),
        ("mad", "tf1", ["MAD-TFN"], "MAD–TFN", "direct"),
        ("tf1", "lp", ["TFN-SPC"], "TFN–SPC", "Binter ATR 72-600, ~30 min"),
        ("lp", "tf2", ["SPC-TFN"], "SPC–TFN", "Binter ATR 72-600, ~30 min"),
        ("tf2", "mq", ["TFS-ORY", "ORY-FDF"], "TFS–ORY–FDF", "no nonstop from the Canaries; via Orly"),
    ],
}

STOP_ORDER = [s["id"] for s in STOPS]


def legs_between(a: str, b: str) -> list[dict]:
    """Legs of the segments from stop a to stop b (consecutive in STOP_ORDER)."""
    ia, ib = STOP_ORDER.index(a), STOP_ORDER.index(b)
    segs = {f"{STOP_ORDER[i]}-{STOP_ORDER[i + 1]}" for i in range(ia, ib)}
    return [leg for leg in LEGS if leg["seg"] in segs]


# --------------------------------------------------------------------------------------------
# Leg models: return kg CO2e per passenger for one draw p, allocation a, occupancy o
# --------------------------------------------------------------------------------------------
def ferry_share(e_ship: float, pax: float, veh_peq: float, veh_t: float, pax_t: float, alloc: str) -> float:
    """kg CO2e per passenger for one sailing emitting e_ship kg."""
    if alloc == "passenger":                    # all of it on the passengers; cargo ignored
        return e_ship / pax
    if alloc == "iso":                          # ISO 14083 passenger equivalents (1 per passenger)
        return e_ship / (pax + veh_peq)
    return e_ship * pax_t / (pax * pax_t + veh_t)   # mass


def hsc_parts(p: dict, occ: str, observed: bool) -> tuple[float, float, float, float]:
    e = p["hsc_kg_nm"] * p["hsc_nm"] * p["mgo_wtw"]
    pax = p["hsc_pax_obs"] if (occ == "observed" and observed) else p["hsc_pax_typ"]
    ts = p["truck_share"]
    veh_peq = p["hsc_vehicles"] * ((1 - ts) * 1.35 + ts * 18)    # cars/vans 1.3-1.4 peq, trucks 18
    veh_t = p["hsc_vehicles"] * ((1 - ts) * 1.4 + ts * 22.0)
    return e, pax, veh_peq, veh_t


def ropax_parts(p: dict) -> tuple[float, float, float, float]:
    e = p["ropax_kg_nm"] * p["ropax_nm"] * p["hfo_wtw"]
    veh_peq = p["ropax_trailers"] * p["trailer_peq"] + p["ropax_cars"] * 1.3
    veh_t = p["ropax_trailers"] * p["trailer_t"] + p["ropax_cars"] * 1.25
    return e, p["ropax_pax_typ"], veh_peq, veh_t


def leg_kg(leg: dict, p: dict, alloc: str, occ: str) -> float:
    m, km_ = leg["model"], leg["km"]
    if m.startswith("rail") or m == "coach":
        return km_ * p[m]
    if m == "ropax":
        e, pax, vp, vt = ropax_parts(p)
        return ferry_share(e, pax, vp, vt, p["pax_mass_t"], alloc)
    if m in ("hsc", "hsc_line"):
        e, pax, vp, vt = hsc_parts(p, occ, observed=(m == "hsc"))
        return ferry_share(e, pax, vp, vt, p["pax_mass_t"], alloc)
    if m == "sail":
        return p["sail_fuel_l"] * p["diesel_wtw"] / round(p["sail_crew"])
    raise ValueError(m)


def flight_kg(code: str, p: dict, nonco2: str) -> float:
    _, _, gcd, kind = FLIGHTS[code]
    flown = gcd * (1 + p["route_uplift"])
    if kind == "jet":
        fuel = (p["jet_lto_kg"] + p["jet_cruise_kg_km"] * flown) / (p["jet_seats"] * p["jet_lf"])
        mult = p["nonco2_short"] if gcd < 500 else p["nonco2_jet"]
    elif kind == "wide":
        fuel = (p["wide_lto_kg"] + p["wide_cruise_kg_km"] * flown) * (1 - p["wide_cargo"]) / (p["wide_seats"] * p["wide_lf"])
        mult = p["nonco2_jet"]
    else:
        fuel = (p["tp_lto_kg"] + p["tp_cruise_kg_km"] * flown) / (p["tp_seats"] * p["tp_lf"])
        mult = p["nonco2_tp"]
    m = mult if nonco2 == "full" else 1.0
    return fuel * (p["jet_co2"] * m + p["jet_wtt"])


def central() -> dict:
    return {k: v[1] for k, v in P.items()}


# --------------------------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------------------------
def quantiles(xs) -> list[float]:
    s = sorted(xs)
    n = len(s)
    pick = lambda q: s[min(n - 1, max(0, int(round(q * (n - 1)))))]
    return [round(pick(0.05), 2), round(pick(0.5), 2), round(pick(0.95), 2)]


def main() -> None:
    rng = random.Random(SEED)
    lens_al = list(product(ALLOCS, OCCS))
    full = list(product(GRAINS, ALLOCS, OCCS, NONCO2))

    # event dates for the cumulative chart (always include today and the end of the trip)
    dates = sorted({leg["date"] for leg in LEGS} | {TODAY, "2026-12-12"})

    store: dict[tuple, array] = {}

    def put(key, value):
        store.setdefault(key, array("d")).append(value)

    for _ in range(DRAWS):
        p = {k: rng.triangular(lo, hi, mode) for k, (lo, mode, hi) in P.items()}
        L = {(leg["id"], a, o): leg_kg(leg, p, a, o) for leg in LEGS for a, o in lens_al}
        F = {(c, n): flight_kg(c, p, n) for c in FLIGHTS for n in NONCO2}
        for leg in LEGS:
            for a, o in lens_al:
                put(("leg", leg["id"], a, o), L[(leg["id"], a, o)])
        for sg in SEGMENTS:
            for a, o in lens_al:
                put(("seg", sg["id"], a, o), sum(L[(leg["id"], a, o)] for leg in LEGS if leg["seg"] == sg["id"]))
        for c in ("SPC-TFN",):
            for n in NONCO2:
                put(("flight", c, n), F[(c, n)])
        for g, a, o, n in full:
            tot_act = {s: 0.0 for s in SCOPES}
            tot_fly = {s: 0.0 for s in SCOPES}
            # actual: every leg; flying: actual minus replaced legs plus flights
            events_act, events_fly = [], []
            for leg in LEGS:
                v = L[(leg["id"], a, o)]
                for s in SCOPES:
                    if s == "planned" or not leg.get("planned"):
                        tot_act[s] += v
                events_act.append((leg["date"], v))
            replaced = set()
            for (fs, ts, chain, *_rest) in J[g]:
                legs = legs_between(fs, ts)
                replaced |= {leg["id"] for leg in legs}
                act = sum(L[(leg["id"], a, o)] for leg in legs)
                fly = sum(F[(c, n)] for c in chain)
                jkey = (g, fs, ts)
                if n == "full":  # journey actual depends only on a, o; store once
                    put(("j_act", *jkey, a, o), act)
                if a == ALLOCS[0] and o == OCCS[0]:  # journey flying depends only on n; store once
                    put(("j_fly", *jkey, n), fly)
                put(("j_diff", *jkey, a, o, n), fly - act)
                planned = any(leg.get("planned") for leg in legs)
                for s in SCOPES:
                    if s == "planned" or not planned:
                        tot_fly[s] += fly
                events_fly.append((legs[0]["date"], fly))
            for leg in LEGS:
                if leg["id"] not in replaced:
                    v = L[(leg["id"], a, o)]
                    for s in SCOPES:
                        if s == "planned" or not leg.get("planned"):
                            tot_fly[s] += v
                    events_fly.append((leg["date"], v))
            for s in SCOPES:
                put(("tot", g, a, o, n, s, "actual"), tot_act[s])
                put(("tot", g, a, o, n, s, "flying"), tot_fly[s])
                put(("tot", g, a, o, n, s, "avoided"), tot_fly[s] - tot_act[s])
            for d in dates:
                ca = sum(v for dd, v in events_act if dd <= d)
                cf = sum(v for dd, v in events_fly if dd <= d)
                put(("cum", g, a, o, n, d, "actual"), ca)
                put(("cum", g, a, o, n, d, "flying"), cf)
                put(("cum", g, a, o, n, d, "avoided"), cf - ca)

    Q = {k: quantiles(v) for k, v in store.items()}
    c = central()

    # ---------------- assemble the data contract of the mockup ----------------
    legs_out = []
    for leg in LEGS:
        q = {f"{a}|{o}": Q[("leg", leg["id"], a, o)] for a, o in lens_al}
        legs_out.append(dict(
            id=leg["id"], date=leg["date"], title=leg["title"], short=leg["short"], mode=leg["mode"],
            mode_label=leg["mode_label"], service=leg["service"], km=leg["km"], km_note=leg["km_note"],
            grade=leg["grade"], grade_note=GRADE_NOTE[leg["grade"]], planned=bool(leg.get("planned")),
            q=q, trace={f"{a}|{o}": trace(leg, c, a, o) for a, o in lens_al}, sources=SOURCES[leg["model"]],
        ))
    segs_out = []
    for sg in SEGMENTS:
        segs_out.append(dict(
            id=sg["id"], from_stop=sg["from_stop"], to_stop=sg["to_stop"], label=sg["label"], title=sg["title"],
            km=sum(leg["km"] for leg in LEGS if leg["seg"] == sg["id"]), planned=bool(sg.get("planned")),
            q={f"{a}|{o}": Q[("seg", sg["id"], a, o)] for a, o in lens_al},
        ))
    stop_name = {s["id"]: s["short"] for s in STOPS}
    journeys_out = {}
    for g in GRAINS:
        rows = []
        for (fs, ts, chain, label, note) in J[g]:
            legs = legs_between(fs, ts)
            jkey = (g, fs, ts)
            rows.append(dict(
                from_stop=fs, to_stop=ts, title=f"{stop_name[fs]} → {stop_name[ts]}",
                planned=any(leg.get("planned") for leg in legs),
                actual_label=summarise_modes(legs), flight_label=label, flight_note=note,
                flight_km=round(sum(FLIGHTS[x][2] for x in chain) * (1 + P["route_uplift"][1])),
                actual={f"{a}|{o}": Q[("j_act", *jkey, a, o)] for a, o in lens_al},
                flying={n: Q[("j_fly", *jkey, n)] for n in NONCO2},
                diff={f"{a}|{o}|{n}": Q[("j_diff", *jkey, a, o, n)] for a, o in lens_al for n in NONCO2},
            ))
        journeys_out[g] = rows
    totals = {f"{g}|{a}|{o}|{n}|{s}": {k: Q[("tot", g, a, o, n, s, k)] for k in ("actual", "flying", "avoided")}
              for g, a, o, n in full for s in SCOPES}
    cumulative = {f"{g}|{a}|{o}|{n}": {"points": [
        {"date": d, **{k: Q[("cum", g, a, o, n, d, k)] for k in ("actual", "flying", "avoided")}}
        for d in [dates[0]] + dates[1:]]} for g, a, o, n in full}
    # flight intensity band per grain and lens: min/max median g/pkm of the flights used
    flight_band = {}
    for g in GRAINS:
        flight_band[g] = {}
        for n in NONCO2:
            vals = []
            for (_fs, _ts, chain, *_r) in J[g]:
                for code in chain:
                    flown = FLIGHTS[code][2] * (1 + P["route_uplift"][1])
                    vals.append(flight_kg(code, c, n) / flown * 1000)
            flight_band[g][n] = [round(min(vals) * 0.85, 1), round(max(vals) * 1.15, 1)]
    hsc_rows = [dict(alloc=a, occ=o, q=Q[("leg", "L8", a, o)]) for a in ALLOCS for o in OCCS]

    data = dict(
        meta=dict(today=TODAY, draws=DRAWS, seed=SEED, max_flight_km=round(
            max(sum(FLIGHTS[x][2] for x in chain) for js in J.values() for (_a, _b, chain, *_r) in js) * 1.08),
            footer=FOOTER),
        lenses=LENSES, defaults=DEFAULTS,
        stops=[dict(id=s["id"], short=s["short"], caption=s["caption"], kind=s["kind"], kind_label=s["kind_label"],
                    planned=bool(s.get("planned"))) for s in STOPS],
        segments=segs_out, legs=legs_out, journeys=journeys_out, totals=totals, cumulative=cumulative,
        milestones=[dict(date=s["arrive"], label=s["short"], planned=bool(s.get("planned")))
                    for s in STOPS if s["kind"] == "destination"],
        spotlight=dict(SPOTLIGHT, rows=hsc_rows, flight={n: Q[("flight", "SPC-TFN", n)] for n in NONCO2}),
        flight_band=flight_band,
        refs=[dict(label="car, alone", gpkm=209), dict(label="car, 4 aboard", gpkm=52)],
    )
    page = HERE / "emissions-mockup.html"
    html = page.read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = re.sub(r'(<script type="application/json" id="mock-data">).*?(</script>)',
                  lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    page.write_text(html, encoding="utf-8")
    (HERE / "mock_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    t = totals[f"{DEFAULTS['grain']}|{DEFAULTS['alloc']}|{DEFAULTS['occ']}|{DEFAULTS['nonco2']}|{DEFAULTS['scope']}"]
    print("defaults:", json.dumps(t))
    for s in SCOPES:
        av = [totals[f"{g}|{a}|{o}|{n}|{s}"]["avoided"][1] for g, a, o, n in full]
        print(f"{s:8} avoided median across lenses: {min(av):8.0f} … {max(av):8.0f} kg; positive {sum(v > 0 for v in av)}/36")
    for a, o in lens_al:
        print(f"L8 {a:9} {o:9}", Q[("leg", "L8", a, o)], " L6", Q[("leg", "L6", a, o)])
    print("flight SPC-TFN", {n: Q[("flight", "SPC-TFN", n)] for n in NONCO2})
    print("size", len(blob) // 1024, "KB")


def summarise_modes(legs: list[dict]) -> str:
    out: list[str] = []
    for leg in legs:
        lab = {"train": "train", "coach": "coach", "ferry": "ferry", "ferry_fast": "fast ferry", "sail": "sailing"}[leg["mode"]]
        out.append(lab)
    counts: dict[str, int] = {}
    for x in out:
        counts[x] = counts.get(x, 0) + 1
    return ", ".join(f"{n} {k}s" if n > 1 else k for k, n in counts.items())


def trace(leg: dict, p: dict, alloc: str, occ: str) -> str:
    """Human-readable calculation for the central parameter values."""
    m, km_ = leg["model"], leg["km"]
    v = leg_kg(leg, p, alloc, occ)
    if m.startswith("rail") or m == "coach":
        return f"{km_} km × {p[m] * 1000:.1f} g CO₂e/pkm = {v:.1f} kg\n(range of the factor: {P[m][0] * 1000:.1f}–{P[m][2] * 1000:.1f} g/pkm)"
    if m == "sail":
        return (f"{p['sail_fuel_l']:.0f} L diesel for motoring and charging × {p['diesel_wtw']:.2f} kg CO₂e/L "
                f"÷ {round(p['sail_crew'])} crew = {v:.0f} kg\n(fuel range {P['sail_fuel_l'][0]}–{P['sail_fuel_l'][2]} L; "
                "log the real figure on arrival)")
    if m in ("hsc", "hsc_line"):
        e, pax, vp, vt = hsc_parts(p, occ, observed=(m == "hsc"))
        fuel_t = p["hsc_kg_nm"] * p["hsc_nm"] / 1000
        head = (f"Ship: {p['hsc_kg_nm']:.0f} kg MGO per nm (EU MRV 2025) × {p['hsc_nm']:.0f} nm = {fuel_t:.1f} t fuel\n"
                f"× {p['mgo_wtw']:.2f} t CO₂e/t (well-to-wake) = {e / 1000:.1f} t CO₂e for the sailing\n")
        occ_txt = f"{pax:.0f} passengers, {'as observed' if (m == 'hsc' and occ == 'observed') else 'line average'}"
        veh_txt = f"{p['hsc_vehicles']:.0f} vehicles"
    else:
        e, pax, vp, vt = ropax_parts(p)
        fuel_t = p["ropax_kg_nm"] * p["ropax_nm"] / 1000
        head = (f"Ship: {p['ropax_kg_nm']:.0f} kg fuel per nm × {p['ropax_nm']:.0f} nm = {fuel_t:.0f} t\n"
                f"× {p['hfo_wtw']:.2f} t CO₂e/t (well-to-wake) = {e / 1000:.0f} t CO₂e for the voyage\n")
        occ_txt = f"{pax:.0f} passengers, typical (not observed)"
        veh_txt = f"{p['ropax_trailers']:.0f} trailers + {p['ropax_cars']:.0f} cars"
    if alloc == "passenger":
        body = f"Per passenger: all of it ÷ {occ_txt} = {v:,.0f} kg (cargo ignored: upper bound)"
    elif alloc == "iso":
        body = (f"ISO 14083: {pax:.0f} passengers + {vp:,.0f} passenger-equivalents for {veh_txt}\n"
                f"→ {e / 1000:.1f} t ÷ {pax + vp:,.0f} = {v:.0f} kg per passenger ({occ_txt})")
    else:
        body = (f"By mass: {p['pax_mass_t'] * 1000:.0f} kg per passenger vs {vt:,.0f} t of vehicles and cargo\n"
                f"→ {v:.1f} kg per passenger ({occ_txt})")
    return head + body


GRADE_NOTE = {
    "A": "Measured fuel or operator data for that trip",
    "B": "Vessel- or service-specific model",
    "C": "Operator or country-specific factor",
    "D": "Generic factor or estimated distance",
}
SOURCES = {
    "rail_lyria": ["SBB and SNCF published factors", "location-based grid mix as upper bound"],
    "rail_fr_tgv": ["ADEME Base Carbone (TGV)", "SNCF published factors"],
    "rail_es": ["Renfe published factors", "Spanish grid mix 2025"],
    "rail_es_hsr": ["Renfe published factors", "Spanish grid mix 2025"],
    "coach": ["DESNZ 2025 coach factor", "ADEME autocar"],
    "ropax": ["EU MRV 2024-25 fuel per nm (Huelva-Canarias ro-pax)", "ISO 14083 Annex G", "DESNZ 2026 masses"],
    "hsc_line": ["EU MRV 2025 (Bencomo Express)", "line average load", "ISO 14083 Annex G"],
    "hsc": ["EU MRV 2025 (Bencomo Express)", "Fred. Olsen fleet data", "ISO 14083 Annex G", "FuelEU MGO factors"],
    "sail": ["Diesel factor: DESNZ 2025 (combustion + upstream)"],
}
LENSES = {
    "grain": dict(title="Compare against", options=[
        dict(id="regions", label="Regions", hint="One flight chain per region visited",
             explain="Regions: a flying traveller flies into each region once and travels inside it like you did. "
                     "Island hops stay ferries in both worlds, so they cancel out. This is the lower bound."),
        dict(id="destinations", label="Destinations", hint="Flights between stops of two nights or more",
             explain="Destinations (recommended): every stop of two nights or more is a place you'd have gone anyway, "
                     "so each gets its own flight. Hendaye and Madrid were only overnight stops on the way and are "
                     "skipped. The island hops become Binter flights."),
        dict(id="stops", label="Every stop", hint="Flights between all overnight stops",
             explain="Every stop: even one-night transit stops get a flight. This inflates the counterfactual with "
                     "stops that only exist because you travelled overland, so it is the upper bound."),
    ]),
    "alloc": dict(title="Ferry share", options=[
        dict(id="passenger", label="Per passenger", hint="All of the ship's emissions divided by its passengers; cargo ignored (upper bound)"),
        dict(id="iso", label="ISO 14083", hint="Passenger equivalents (ISO 14083 Annex G): car 1.3, trailer 14, truck 18 (recommended)"),
        dict(id="mass", label="By mass", hint="Split by mass: 100 kg per passenger vs 1.25 t per car, ~22 t per truck (as DESNZ)"),
    ]),
    "occ": dict(title="Occupancy", options=[
        dict(id="typical", label="Typical", hint="Average load factors for every vehicle"),
        dict(id="observed", label="As observed", hint="Your own count where you logged one; typical elsewhere"),
    ]),
    "nonco2": dict(title="Flights count", options=[
        dict(id="co2", label="CO₂ only", hint="Fuel combustion and upstream fuel production"),
        dict(id="full", label="+ non-CO₂", hint="Adds contrails and NOx effects (multiplier, uncertain)"),
    ]),
}
DEFAULTS = dict(grain="destinations", alloc="iso", occ="observed", nonco2="full", scope="planned")
SPOTLIGHT = dict(
    lede=("On 17 October the Bencomo Express, a 38-knot catamaran, crossed from La Palma to Los Cristianos with about "
          "150 people aboard, where it averages around 260. A fast craft burns about as much fuel per mile as a large "
          "ro-pax ferry but has far less freight to share it with, so each passenger's share is large. How large "
          "depends on how you count."),
    facts=[
        ["Operator", "Fred. Olsen Express"],
        ["Vessel", "Incat 96 m wave-piercing catamaran, 1999"],
        ["Capacity", "859 passengers, 230 vehicles"],
        ["Engines", "4 × Caterpillar 3618, 28.8 MW, waterjets, ~38 kn"],
        ["Fuel", "marine gas oil; 145 kg per nautical mile (EU MRV 2025)"],
        ["Route", "Los Cristianos – Santa Cruz de La Palma, 68 nm, 2 h 30"],
        ["This sailing", "~150 passengers (17 % full); 2025 average ~260"],
        ["Alternative", "Binter ATR 72-600, Tenerife North – La Palma, ~30 min"],
    ],
    flight_label="Binter flight SPC–TFN",
    callout=("Counted per passenger or with ISO 14083 passenger equivalents, this crossing emitted more than the "
             "30-minute flight would have. Counted by mass, the cars and trucks carry most of it. In its 2025 EU MRV "
             "report the operator put 76 % of the ship's emissions on passengers: about 110 kg for this crossing."),
)
FOOTER = ("Illustrative model: 4,000 Monte Carlo draws with parameters shared across legs within each draw. "
          "All numbers are computed in Python (prototype/mock_model.py); the page only selects among them.")

if __name__ == "__main__":
    main()
