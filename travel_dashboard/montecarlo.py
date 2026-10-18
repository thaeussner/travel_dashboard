"""Monte Carlo over every lens combination, with parameters shared across travels in each draw.

Lens combinations are separate scenarios and never mixed; the draws only express parameter
uncertainty within one combination (see METHODOLOGY.md §2).

Scope "todate" counts legs dated up to today. A journey's swap to its alternative is dated at the
journey's last leg, so the comparison appears once the journey is complete (conservative).
"""

from __future__ import annotations

import datetime as dt
import random
from array import array
from collections import defaultdict
from itertools import product

from .model import LENSES, dims, kg, variant_key
from .profiles import Profile, Profiles, Sampler
from .tables import Travel
from .trip import LEVELS, Trip

COMBOS = list(product(LENSES["alloc"], LENSES["occ"], LENSES["nonco2"]))
SCOPES = ("todate", "all")


def ckey(combo: tuple[str, str, str]) -> str:
    return "|".join(combo)


def quantiles(xs) -> list[float]:
    s = sorted(xs)
    n = len(s)

    def q(p: float) -> float:
        return s[min(n - 1, max(0, round(p * (n - 1))))]

    return [round(q(0.05), 2), round(q(0.5), 2), round(q(0.95), 2)]


def variants(d: tuple[str, ...]) -> list[tuple[str, tuple[str, str, str]]]:
    """(variant key, a representative full combo) for each distinct value of the given dims."""
    seen: dict[str, tuple[str, str, str]] = {}
    for combo in COMBOS:
        seen.setdefault(variant_key(d, *combo), combo)
    return list(seen.items())


def run(trip: Trip, profiles: Profiles, today: dt.date, draws: int, seed: int) -> dict:
    sampler = Sampler(random.Random(seed))
    travels: list[Travel] = trip.legs + [r for o in trip.options for r in o.rows]
    prof: dict[str, Profile] = {t.id: profiles.resolve(t) for t in travels}
    tdims = {t.id: dims(t, prof[t.id]) for t in travels}
    tvars = {t.id: variants(tdims[t.id]) for t in travels}
    vkey_of = {(t.id, ckey(c)): variant_key(tdims[t.id], *c) for t in travels for c in COMBOS}

    dates = sorted({t.date for t in trip.legs if t.date}
                   | {j.date for lvl in LEVELS for j in trip.journeys[lvl] if j.date and j.option}
                   | {today})
    di = {d: i for i, d in enumerate(dates)}
    nd = len(dates)
    local: dict[str, list[Travel]] = {}      # local travel per waypoint
    for t in trip.legs:
        if t.from_ == t.to:
            local.setdefault(t.from_, []).append(t)
    # local travel at a place an alternative skips is part of that journey (and swapped with it, in
    # the scopes where the journey is); the rest counts in both worlds
    def swaps(j, s: str) -> bool:
        return bool(j.option) and (s == "all" or (j.date is not None and j.date <= today))
    kept = {(lvl, s): [t for lts in local.values() for t in lts
                       if not any(swaps(j, s) and t in j.legs for j in trip.journeys[lvl])]
            for lvl in LEVELS for s in SCOPES}

    store: dict[tuple, array] = defaultdict(lambda: array("d"))

    for _ in range(draws):
        sampler.new_draw()
        val: dict[tuple[str, str], float] = {}
        for t in travels:
            for vk, (a, o, n) in tvars[t.id]:
                v = kg(t, prof[t.id], sampler, a, o, n)
                val[(t.id, vk)] = v
                store[("travel", t.id, vk)].append(v)

        for combo in COMBOS:
            ck = ckey(combo)
            v = {t.id: val[(t.id, vkey_of[(t.id, ck)])] for t in travels}
            leg_delta = [0.0] * nd
            act = {"todate": 0.0, "all": 0.0}
            for t in trip.legs:
                leg_delta[di[t.date]] += v[t.id]
                act["all"] += v[t.id]
                if t.date <= today:
                    act["todate"] += v[t.id]
            for s in SCOPES:
                for wid, lts in local.items():
                    store[("local", wid, ck, s)].append(sum(v[t.id] for t in lts if s == "all" or t.date <= today))
                if local:
                    for lvl in LEVELS:
                        store[("local_total", lvl, ck, s)].append(
                            sum(v[t.id] for t in kept[(lvl, s)] if s == "all" or t.date <= today))
            opt_total = {o.id: sum(v[r.id] for r in o.rows) for o in trip.options}
            for oid, tot in opt_total.items():
                store[("option", oid, ck)].append(tot)

            for level in LEVELS:
                fly = dict(act)
                fly_delta = list(leg_delta)
                for ji, j in enumerate(trip.journeys[level]):
                    a_sum = sum(v[t.id] for t in j.legs)
                    f_sum = opt_total[j.option.id] if j.option else a_sum
                    store[("journey", level, ji, ck, "actual")].append(a_sum)
                    store[("journey", level, ji, ck, "flying")].append(f_sum)
                    store[("journey", level, ji, ck, "diff")].append(f_sum - a_sum)
                    if j.option and j.date:
                        fly["all"] += f_sum - a_sum
                        if j.date <= today:
                            fly["todate"] += f_sum - a_sum
                        fly_delta[di[j.date]] += f_sum - a_sum
                    elif j.option:      # no date at all: only part of the full scope
                        fly["all"] += f_sum - a_sum
                for s in SCOPES:
                    store[("total", level, ck, s, "actual")].append(act[s])
                    store[("total", level, ck, s, "flying")].append(fly[s])
                    store[("total", level, ck, s, "avoided")].append(fly[s] - act[s])
                ca = cf = 0.0
                for i in range(nd):
                    ca += leg_delta[i]
                    cf += fly_delta[i]
                    store[("cum", level, ck, i, "actual")].append(ca)
                    store[("cum", level, ck, i, "flying")].append(cf)
                    store[("cum", level, ck, i, "avoided")].append(cf - ca)

    q = {k: quantiles(arr) for k, arr in store.items()}
    out: dict = {
        "profiles": prof,
        "dims": tdims,
        "travel": {t.id: {vk: q[("travel", t.id, vk)] for vk, _c in tvars[t.id]} for t in travels},
        "option": {o.id: {ckey(c): q[("option", o.id, ckey(c))] for c in COMBOS} for o in trip.options},
        "journeys": {lvl: [{ckey(c): {s: q[("journey", lvl, ji, ckey(c), s)] for s in ("actual", "flying", "diff")}
                            for c in COMBOS} for ji in range(len(trip.journeys[lvl]))] for lvl in LEVELS},
        "totals": {f"{lvl}|{ckey(c)}|{s}": {k: q[("total", lvl, ckey(c), s, k)] for k in ("actual", "flying", "avoided")}
                   for lvl in LEVELS for c in COMBOS for s in SCOPES},
        "local": [{"waypoint": wid, "legs": [t.id for t in lts],
                   "q": {f"{ckey(c)}|{s}": q[("local", wid, ckey(c), s)] for c in COMBOS for s in SCOPES}}
                  for wid, lts in local.items()],
        "local_total": {f"{lvl}|{ckey(c)}|{s}": q[("local_total", lvl, ckey(c), s)]
                        for lvl in LEVELS for c in COMBOS for s in SCOPES} if local else {},
        "cumulative": {f"{lvl}|{ckey(c)}": [
            {"date": d.isoformat(), **{k: q[("cum", lvl, ckey(c), i, k)] for k in ("actual", "flying", "avoided")}}
            for i, d in enumerate(dates)] for lvl in LEVELS for c in COMBOS},
    }
    return out
