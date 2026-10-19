"""The trip's structure: ordered waypoints, legs, alternative options and journeys per level.

- Waypoints are typed by hand: `destination` (a place that would have been visited anyway) or `stop`.
- An alternative *option* is a chain of `alt` rows sharing an option name. It replaces every leg
  between its first and last waypoint. Intermediate points (e.g. "Paris Orly") are plain text. A
  flight may start or end at a waypoint's airport instead ("TFN" for El Medano with "TFS TFN").
- Level "destination": one journey per pair of consecutive destinations, compared against the
  main option spanning exactly that pair.
- Level "stop": stop-level options (at least one end is a stop) replace the legs they span, e.g.
  an inter-island flight for the ferry; the rest of that journey counts the same in both worlds.
  Journeys without stop-level options keep their destination-level option.
- Level "direct": options that skip destinations (e.g. one flight Paris → Martinique) replace
  everything between their ends; elsewhere the destination-level option is the fallback. A piece
  cut off by a direct option (Zurich → Paris before a flight from Paris) has no alternative.
- Local travel (from == to) counts in both worlds where the alternative also goes. At a place an
  alternative skips, it belongs to that journey and only counts as actual travel.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from . import geo
from .tables import Issue, Travel, Waypoint

LEVELS = ("destination", "stop", "direct")


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
    skipped: list[str] = field(default_factory=list)   # waypoints strictly inside, which the alternative skips

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
        # a name or airport may fit several waypoints (TFN for every stop on Tenerife, a second visit):
        # a reading that stays between two destinations first, then destination ends, then the
        # shortest span. So SVQ → TFN is the ferry Huelva → Santa Cruz, not a flight past La Palma.
        def rank(ab: tuple[str, str]) -> tuple:
            skips = any(wtype[w.id] == "destination" for w in ordered[pos[ab[0]] + 1:pos[ab[1]]])
            return (skips, -sum(wtype[x] == "destination" for x in ab), pos[ab[1]] - pos[ab[0]], pos[ab[0]])
        pairs = sorted(((a, b) for a in starts for b in ends if pos[a] < pos[b]), key=rank)
        if not pairs:
            issues.append(Issue("travel", name, "alternative ends before it starts; option skipped", "error"))
            continue
        a, b = pairs[0]
        if len(pairs) > 1 and rank(pairs[1])[:3] == rank(pairs[0])[:3]:
            issues.append(Issue("travel", name, f"{chain[0].from_!r} → {chain[-1].to!r} fits several waypoints "
                                                f"equally well; using {a} → {b}. Write waypoint ids to choose."))
        chain[0].from_, chain[-1].to = a, b
        skips_dest = any(wtype[w.id] == "destination" for w in ordered[pos[a] + 1:pos[b]])
        level = ("direct" if skips_dest else
                 "destination" if wtype[a] == "destination" and wtype[b] == "destination" else "stop")
        options.append(Option(name, chain, a, b, level, any(r.main for r in rows)))

    journeys = _journeys(ordered, pos, legs, options, issues)
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
    """Legs of the journey from a to b, with the local travel at the places in between.

    Local travel at a and b stays out: the alternative goes there too, so it counts in both worlds."""
    return [t for t in legs if (pos[a] <= pos[t.from_] and pos[t.to] <= pos[b] and t.from_ != t.to)
            or (t.from_ == t.to and pos[a] < pos[t.from_] < pos[b])]


def _date(legs: list[Travel], option: Option | None) -> dt.date | None:
    dates = [t.date for t in legs if t.date]
    if dates:
        return max(dates)
    if option:
        odates = [r.date for r in option.rows if r.date]
        return max(odates) if odates else None
    return None


def _journey(level: str, a: str, b: str, legs, pos, ordered, picked) -> Journey:
    main, extras = picked
    jl = _legs_between(legs, pos, a, b)
    skipped = [w.id for w in ordered[pos[a] + 1:pos[b]]] if main else []
    return Journey(level, a, b, jl, main, extras, _date(jl, main), skipped)


def _journeys(ordered, pos, legs, options, issues) -> dict[str, list[Journey]]:
    dests = [w.id for w in ordered if w.type == "destination"]
    spans = list(zip(dests, dests[1:]))
    by_level: dict[str, dict[tuple[str, str], list[Option]]] = {lvl: defaultdict(list) for lvl in LEVELS}
    for o in options:
        if o.level == "stop" and not any(pos[a] <= pos[o.start] and pos[o.end] <= pos[b] for a, b in spans):
            issues.append(Issue("travel", o.id, "stop-level alternative lies outside the destinations; not used"))
            continue
        by_level[o.level][(o.start, o.end)].append(o)

    out: dict[str, list[Journey]] = {lvl: [] for lvl in LEVELS}
    for a, b in spans:
        out["destination"].append(_journey("destination", a, b, legs, pos, ordered,
                                           _pick(by_level["destination"].get((a, b), []), issues)))
    for lvl, longest in (("stop", False), ("direct", True)):
        picked = {span: _pick(opts, issues) for span, opts in by_level[lvl].items()}
        out[lvl] = _overlay(lvl, ordered, pos, dests, legs, out["destination"], picked, longest, issues)
    return out


OVERLAP = {"stop": "overlaps another alternative between stops; not used under Every stop",
           "direct": "overlaps another alternative that skips destinations; not used under Direct"}


def _overlay(level, ordered, pos, dests, legs, dest_journeys, options, longest, issues) -> list[Journey]:
    """Journeys of the stop and direct levels: each option replaces the legs between its ends.

    Every stop swaps single hops (an inter-island flight for the ferry); Direct replaces whole
    stretches across destinations. Overlapping options give way to the one marked main, then to
    the longer (Direct) or the shorter (Every stop) one. Elsewhere the destination-level journeys
    stay, and a piece an option cuts off (Zurich → Paris before a flight from Paris) is a journey
    without alternative, the same in both worlds."""
    def span(kv) -> int:
        return pos[kv[0][1]] - pos[kv[0][0]]
    chosen: list[tuple[str, str, tuple]] = []
    for (s, e), picked in sorted(options.items(), key=lambda kv: (not kv[1][0].main, -span(kv) if longest else span(kv),
                                                                  pos[kv[0][0]])):
        if all(pos[e] <= pos[cs] or pos[s] >= pos[ce] for cs, ce, _ in chosen):
            chosen.append((s, e, picked))
        else:
            issues.append(Issue("travel", picked[0].id, OVERLAP[level]))
    chosen.sort(key=lambda c: pos[c[0]])
    by_span = {(j.start, j.end): j for j in dest_journeys}

    def plain(x: int, y: int) -> list[Journey]:
        """Positions x..y without options of this level: destination journeys, plus the cut-off pieces."""
        inside = [d for d in dests if x <= pos[d] <= y]
        marks = [x] + [pos[d] for d in inside] + [y]
        out = []
        for p, q in zip(marks, marks[1:]):
            if p >= q:
                continue
            a, b = ordered[p].id, ordered[q].id
            j = by_span.get((a, b))
            out.append(Journey(level, a, b, j.legs, j.option, j.extras, j.date, j.skipped) if j
                       else _journey(level, a, b, legs, pos, ordered, (None, [])))
        return out

    if not dests:
        return []
    lo = min([pos[dests[0]]] + [pos[s] for s, _, _ in chosen])
    hi = max([pos[dests[-1]]] + [pos[e] for _, e, _ in chosen])
    out, cursor = [], lo
    for s, e, picked in chosen:
        out += plain(cursor, pos[s])
        out.append(_journey(level, s, e, legs, pos, ordered, picked))
        cursor = pos[e]
    return out + plain(cursor, hi)
