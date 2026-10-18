"""The trip's structure: ordered waypoints, legs, alternative options and journeys per level.

- Waypoints are typed by hand: `destination` (a place you'd have gone anyway) or `stop`.
- An alternative *option* is a chain of `alt` rows sharing an option name. It replaces every leg
  between its first and last waypoint. Intermediate points (e.g. "Paris Orly") are plain text. A
  flight may start or end at a waypoint's airport instead ("TFN" for El Medano with "TFS TFN").
- Level "destination": one journey per pair of consecutive destinations, compared against the
  main option spanning exactly that pair.
- Level "stop": inside each destination span, stop-level options (at least one end is a stop) are
  used when they tile the whole span; otherwise the destination-level option is the fallback.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from . import geo
from .tables import Issue, Travel, Waypoint

LEVELS = ("destination", "stop")


@dataclass
class Option:
    id: str
    rows: list[Travel]
    start: str
    end: str
    level: str
    main: bool

    @property
    def label(self) -> str:
        points = [self.rows[0].from_] + [r.to for r in self.rows]
        return " → ".join(points)


@dataclass
class Journey:
    level: str
    start: str
    end: str
    legs: list[Travel]
    option: Option | None
    extras: list[Option] = field(default_factory=list)
    date: dt.date | None = None

    def planned(self, today: dt.date) -> bool:
        return self.date is None or self.date > today


@dataclass
class Trip:
    waypoints: list[Waypoint]
    pos: dict[str, int]
    legs: list[Travel]
    options: list[Option]
    journeys: dict[str, list[Journey]]
    issues: list[Issue]

    def name(self, wid: str) -> str:
        i = self.pos.get(wid)
        return self.waypoints[i].name if i is not None else wid


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class Resolver:
    """Map a from/to text to waypoint ids: the exact id, else the name, else the waypoints that list
    the airport code written in the text. Calling it gives the id only when that is unambiguous."""

    def __init__(self, waypoints: list[Waypoint]):
        self.ids = {w.id.lower(): w.id for w in waypoints}
        self.names: dict[str, list[str]] = defaultdict(list)
        self.codes: dict[str, list[str]] = defaultdict(list)
        for w in waypoints:
            self.names[_norm(w.name)].append(w.id)
            for c in w.airports:
                self.codes[c].append(w.id)

    def candidates(self, text: str) -> list[str]:
        key = _norm(text)
        if key in self.ids:
            return [self.ids[key]]
        if key in self.names:
            return self.names[key]
        return list(dict.fromkeys(w for c in geo.written_codes(text) for w in self.codes.get(c, [])))

    def __call__(self, text: str) -> str | None:
        hits = self.candidates(text)
        return hits[0] if len(hits) == 1 else None


def order_waypoints(waypoints: list[Waypoint], legs: list[Travel], resolve, issues: list[Issue]) -> list[Waypoint]:
    """Order by arrival date. Missing dates are taken from the legs; ties follow the legs."""
    incoming: dict[str, list[dt.date]] = defaultdict(list)
    outgoing: dict[str, list[dt.date]] = defaultdict(list)
    edges: set[tuple[str, str]] = set()
    for t in legs:
        a, b = resolve(t.from_), resolve(t.to)
        if a and a == b:
            continue        # local travel around one place says nothing about the order
        if a and t.date:
            outgoing[a].append(t.date)
        if b and t.date:
            incoming[b].append(t.date)
        if a and b:
            edges.add((a, b))

    def key(iw: tuple[int, Waypoint]):
        i, w = iw
        arrive = w.arrive or (max(incoming[w.id]) if incoming[w.id] else None)
        depart = w.depart or (min(outgoing[w.id]) if outgoing[w.id] else None)
        if arrive is None:
            if outgoing[w.id] or i == 0:
                arrive = dt.date.min          # the start of the trip
            else:
                issues.append(Issue("waypoints", w.id, "no date and no legs: placed at the end; add an arrive date"))
                arrive = dt.date.max
        return (arrive, depart or dt.date.max)

    keyed = sorted(((key(iw), iw) for iw in enumerate(waypoints)), key=lambda x: (x[0], x[1][0]))
    # break ties between waypoints with identical dates using the leg graph
    out: list[Waypoint] = []
    i = 0
    while i < len(keyed):
        j = i
        while j + 1 < len(keyed) and keyed[j + 1][0] == keyed[i][0]:
            j += 1
        group = [iw[1] for _k, iw in keyed[i:j + 1]]
        out.extend(_topo(group, edges) if len(group) > 1 else group)
        i = j + 1
    return out


def _topo(group: list[Waypoint], edges: set[tuple[str, str]]) -> list[Waypoint]:
    ids = {w.id for w in group}
    indeg = {w.id: 0 for w in group}
    for a, b in edges:
        if a in ids and b in ids:
            indeg[b] += 1
    out, pending = [], list(group)
    while pending:
        nxt = next((w for w in pending if indeg[w.id] == 0), pending[0])
        pending.remove(nxt)
        out.append(nxt)
        for a, b in edges:
            if a == nxt.id and b in indeg:
                indeg[b] -= 1
    return out


def _chain(rows: list[Travel]) -> list[Travel] | None:
    """Order an option's rows so that each row starts where the previous one ended."""
    if len(rows) == 1:
        return rows
    ends = {_norm(r.to) for r in rows}
    starts = [r for r in rows if _norm(r.from_) not in ends]
    if len(starts) != 1:
        return None
    chain, left = [starts[0]], [r for r in rows if r is not starts[0]]
    while left:
        nxt = [r for r in left if _norm(r.from_) == _norm(chain[-1].to)]
        if len(nxt) != 1:
            return None
        chain.append(nxt[0])
        left.remove(nxt[0])
    return chain


def build(waypoints: list[Waypoint], travel: list[Travel], issues: list[Issue]) -> Trip:
    resolve = Resolver(waypoints)
    raw_legs = [t for t in travel if t.is_leg]
    ordered = order_waypoints(waypoints, raw_legs, resolve, issues)
    pos = {w.id: i for i, w in enumerate(ordered)}
    wtype = {w.id: w.type for w in ordered}

    # legs: endpoints must be waypoints
    legs: list[Travel] = []
    for t in raw_legs:
        a, b = resolve(t.from_), resolve(t.to)
        if not a or not b:
            missing = t.from_ if not a else t.to
            issues.append(Issue("travel", t.id, f"leg endpoint {missing!r} is not a waypoint id; leg skipped", "error"))
            continue
        t.from_, t.to = a, b
        if a == b:
            pass            # local travel: counted in both worlds, never replaced by an alternative
        elif pos[b] <= pos[a]:
            issues.append(Issue("travel", t.id, "leg goes backwards in the waypoint order; check the dates"))
        elif pos[b] - pos[a] > 1:
            issues.append(Issue("travel", t.id, "leg skips a waypoint in between"))
        legs.append(t)
    legs.sort(key=lambda t: (pos[t.from_], t.date or dt.date.max))
    linked = {(pos[t.from_], pos[t.to]) for t in legs if t.from_ != t.to}
    for i in range(len(ordered) - 1):
        if not any(a <= i and b >= i + 1 for a, b in linked):
            issues.append(Issue("waypoints", ordered[i + 1].id,
                                f"no leg between {ordered[i].name} and {ordered[i + 1].name}"))

    # options: chains of alt rows
    groups: dict[str, list[Travel]] = defaultdict(list)
    for t in travel:
        if not t.is_leg:
            groups[t.option].append(t)
    options: list[Option] = []
    for name, rows in groups.items():
        chain = _chain(rows)
        if chain is None:
            issues.append(Issue("travel", name, "the rows of this alternative don't form one chain; option skipped", "error"))
            continue
        starts, ends = resolve.candidates(chain[0].from_), resolve.candidates(chain[-1].to)
        if not starts or not ends:
            where = chain[0].from_ if not starts else chain[-1].to
            issues.append(Issue("travel", name, f"{where!r} is not a waypoint, nor an airport listed on one: an alternative "
                                                "must start and end at waypoints; option skipped", "error"))
            continue
        # a name or airport may fit several waypoints (e.g. a second visit): take the shortest span
        pairs = sorted(((a, b) for a in starts for b in ends if pos[a] < pos[b]),
                       key=lambda ab: (pos[ab[1]] - pos[ab[0]], pos[ab[0]]))
        if not pairs:
            issues.append(Issue("travel", name, "alternative ends before it starts; option skipped", "error"))
            continue
        a, b = pairs[0]
        if len(pairs) > 1:
            issues.append(Issue("travel", name, f"{chain[0].from_!r} → {chain[-1].to!r} fits several waypoints; "
                                                f"using {a} → {b}"))
        chain[0].from_, chain[-1].to = a, b
        level = "destination" if wtype[a] == "destination" and wtype[b] == "destination" else "stop"
        options.append(Option(name, chain, a, b, level, any(r.main for r in rows)))

    journeys = _journeys(ordered, pos, wtype, legs, options, issues)
    return Trip(ordered, pos, legs, options, journeys, issues)


def _pick(opts: list[Option], issues: list[Issue]) -> tuple[Option | None, list[Option]]:
    if not opts:
        return None, []
    mains = [o for o in opts if o.main]
    if len(mains) > 1:
        issues.append(Issue("travel", mains[1].id, f"several alternatives marked main for the same span; using {mains[0].id}"))
    main = mains[0] if mains else opts[0]
    return main, [o for o in opts if o is not main]


def _legs_between(legs: list[Travel], pos: dict[str, int], a: str, b: str) -> list[Travel]:
    """Legs of the journey from a to b. Local travel (from == to) belongs to no journey."""
    return [t for t in legs if t.from_ != t.to and pos[a] <= pos[t.from_] and pos[t.to] <= pos[b]]


def _date(legs: list[Travel], option: Option | None) -> dt.date | None:
    dates = [t.date for t in legs if t.date]
    if dates:
        return max(dates)
    if option:
        odates = [r.date for r in option.rows if r.date]
        return max(odates) if odates else None
    return None


def _journeys(ordered, pos, wtype, legs, options, issues) -> dict[str, list[Journey]]:
    dests = [w.id for w in ordered if w.type == "destination"]
    spans = list(zip(dests, dests[1:]))
    by_span: dict[tuple[str, str], list[Option]] = defaultdict(list)
    for o in options:
        if o.level == "destination":
            if (o.start, o.end) not in spans:
                issues.append(Issue("travel", o.id, "alternative skips a destination; it is only used if it spans "
                                                    "two consecutive destinations"))
                continue
            by_span[(o.start, o.end)].append(o)
        else:
            inside = [w for w in ordered[pos[o.start] + 1:pos[o.end]] if wtype[w.id] == "destination"]
            if inside or not any(pos[a] <= pos[o.start] and pos[o.end] <= pos[b] for a, b in spans):
                issues.append(Issue("travel", o.id, "stop-level alternative crosses a destination; not used"))
                continue
            by_span[(o.start, o.end)].append(o)

    out: dict[str, list[Journey]] = {"destination": [], "stop": []}
    for a, b in spans:
        jlegs = _legs_between(legs, pos, a, b)
        main, extras = _pick(by_span.get((a, b), []), issues)
        dest_j = Journey("destination", a, b, jlegs, main, extras, _date(jlegs, main))
        out["destination"].append(dest_j)

        # finest tiling of [a, b] by stop-level options
        inner = [w.id for w in ordered[pos[a]:pos[b] + 1]]
        edges = {(x, y): _pick(opts, issues) for (x, y), opts in by_span.items()
                 if (x, y) != (a, b) and x in inner and y in inner}
        best: dict[str, list[tuple[str, str]] | None] = {a: []}
        for x in inner:
            if best.get(x) is None:
                continue
            for (s, e) in edges:
                if s == x and pos[e] > pos[x]:
                    cand = best[x] + [(s, e)]
                    if best.get(e) is None or len(cand) > len(best[e]):
                        best[e] = cand
        tiling = best.get(b)
        if tiling:
            for s, e in tiling:
                tl = _legs_between(legs, pos, s, e)
                o, ex = edges[(s, e)]
                out["stop"].append(Journey("stop", s, e, tl, o, ex, _date(tl, o)))
        else:
            out["stop"].append(Journey("stop", a, b, jlegs, main, extras, dest_j.date))
    return out
