# CLAUDE.md

Personal travel dashboard for a multi-month, flight-free trip that started in autumn 2026:
Switzerland → France → Spain → Canary Islands by train, bus and ferry, then sailing to the Caribbean.
It's a static site on GitHub Pages, shared with a few friends. Only the owner edits.

There are two separate pages, each with its own input:

1. **Costs** (`site/costs/`): CHF amount, date, category, country. Averages per day, week, month and
   country. No currency conversion, ever.
2. **Emissions** (`site/emissions/`): legs that happened against hand-picked realistic alternatives,
   with method switches (lenses), Monte Carlo ranges and per-leg arithmetic.

A third page, **Method** (`site/method/`), explains the emissions method in plain language for
friends: the trip's own ferries split three ways (`ship_breakdown` in `model.py`) and a table of
default factors per mode and named vehicle (`factors.py`), both computed in Python.

Docs:

- `docs/METHODOLOGY.md`: the emissions method, defaults and sources. It is the site's reference;
  keep it in sync with the model.
- `docs/PLAN.md`: architecture and roadmap.
- `prototype/`: the first design mockup; reference only.

## How the owner works

- **Input is fully manual.** No GPS and no automatic derivation. The owner wants to backfill and
  prefill waypoints and travel freely, and to decide the realistic alternatives themself.
  Waypoint type (`stop` or `destination`) is set by hand, never by a rule such as number of nights.
- **Mostly on a phone, often offline** (weeks at sea). Never make a change that could lose queued
  edits or silently rewrite their data.
- **Prefers Python** and comes from R. Keep Python readable.
- **Cares about methodology:** ferry allocation, occupancy, comparison level, non-CO₂ effects.
  When a choice is debatable, make it a lens or a documented assumption, never a silent default.

## Architecture

```
owner's browser ──(fine-grained token, GitHub contents API)──► data/*.csv ──push──► GitHub Actions
   site/assets/store.js: offline queue, one commit per table      python -m travel_dashboard build
                                                                        │
friends' browsers ◄── GitHub Pages: site/ + site/data/*.json ◄──────────┘
```

- **Data:** `data/costs.csv`, `data/waypoints.csv`, `data/travel.csv`. The schemas are in
  `travel_dashboard/tables.py`, mirrored in `site/assets/store.js` (`COLUMNS`). Change both together.
- **Travel rows:**
  - `type = leg | alt`.
  - Alternative rows sharing an `option` name form one chain, e.g. via Paris Orly. Intermediate
    points are plain text.
  - A chain starts and ends at waypoints: an id, a name, or an airport code that a waypoint lists
    (`airport` may hold several, e.g. `TFS TFN`). When several waypoints fit, destinations win,
    then the shortest span. `trip.Resolver` and `trip.build` do this; `pointTargets` and
    `chainEnds` in `emissions.js` mirror it for the editor only. `geo.fill_flight_km` keeps the
    code written (`from_code`/`to_code`), because the build then replaces the ends with waypoint ids.
  - Every waypoint lists its airports. The waypoint form fills them in from the place name
    (`airportsFor` over `site/data/airports.json`, written by the build from
    `data/reference/airports.csv`); this is input help only, the CSV holds the codes.
  - An option replaces every leg between its first and last waypoint. `main = 1` picks it when
    several options share a span.
  - A leg with `from == to` is a local trip at that waypoint (e.g. driving around an island). It is
    kept out of waypoint ordering. It counts in both worlds where the alternative goes too; at a
    place an alternative skips, it is part of that journey and counts only as actual travel
    (`montecarlo` keeps `local_total` per level for the "Local travel" row).
- **Levels:**
  - "destination": one journey per pair of consecutive destinations.
  - "stop": stop-level options are used where they tile a whole destination span; otherwise the
    destination-level option is the fallback (`travel_dashboard/trip.py`).
  - "direct": options that skip destinations (CDG → FDF from Paris) replace everything between
    their ends, which may be stops; elsewhere the destination-level journeys, and a cut-off piece
    (Zurich → Paris) has no alternative. It answers "the trip against flying straight there", by
    the owner's request.
- **Ferries:** use the vessel's typical freight from config. There is no freight input, by the
  owner's choice.
- **Sailing:** litres (`fuel_l`, grade A), else engine hours (`engine_h` × L/h, grade B), else a
  default per km. The dinghy is not a mode: its outboard use goes into the engine hours, by the
  owner's choice. `km` is optional when litres or engine hours are given.
- **Owner-only editing:** the edit UI is hidden unless a token is stored in that browser
  (`body.owner`). The token is the actual protection.

## Commands

Plain Python ≥ 3.12, standard library only. CI uses 3.14.

```bash
python -m travel_dashboard build [--data examples/trip] [--today YYYY-MM-DD] [--draws N]
python -m travel_dashboard check            # validate data, list issues (exit 1 on errors)
python -m travel_dashboard serve            # http://localhost:8000 (build first)
python -m travel_dashboard airports         # refresh data/reference/airports.csv (OurAirports, 4,008 airports)
python -m unittest discover -s tests        # test_build uses examples/trip
```

## Layout

```
config/            emissions.toml (all factors, vessels, flight classes), settings.toml (repo, draws, default lens)
data/              the owner's CSVs; reference/airports.csv (IATA → coordinates); examples/trip/ for demos and tests
travel_dashboard/  tables.py (parse/validate), geo.py (airports, km from codes), profiles.py (config → per-travel parameters, shared sampling),
                   model.py (per-passenger kg, traces, ship breakdown), trip.py (ordering, options, journeys per level),
                   montecarlo.py (36 lens combos × draws), factors.py (default factor table), costs.py,
                   export.py (JSON contract), cli.py
site/              index.html, costs/, emissions/, method/, assets/ (app.css, common.js, store.js, editor.js,
                   costs.js, emissions.js, home.js, method.js), vendor/d3.v7.9.0.min.js, sw.js,
                   manifest.webmanifest, icons/, data/ (generated, gitignored)
tests/             test_core.py (parsing, model, trip), test_build.py (contract and invariants)
```

## Invariants (don't break these)

1. **Python owns every assumption.** Factors, allocation, uncertainty and the alternative logic
   live in Python. Page JS may filter, group and sum rows. The one exception is costs: the page sums
   them itself so new entries show at once, and there are no assumptions in them to own.
2. **Factors only in `config/emissions.toml`,** each with a source. No magic numbers in code.
   Vehicles match by whole-word regex, first match wins, so keep specific entries above generic ones.
   Cars get size and fuel from words in the vehicle text (`[cars]`). `describeProfile` in
   `emissions.js` mirrors this matching only to show a hint in the form, so keep both in sync.
3. **Lenses are not uncertainty.** Level, ferry share, occupancy and non-CO₂ are precomputed
   scenarios. Monte Carlo ranges apply within one scenario. Parameters are shared within a draw. Each
   lens applies to legs and alternatives alike.
4. **Traceable numbers.** Every travel row has a trace (central values), sources and a grade (A–D).
5. **Units.**
   - Emissions: kg CO₂e per passenger, well-to-wheel.
   - Distances: km as entered. For flights that is great-circle km, and the model adds routing.
   - Money: CHF.
   - Dates: ISO.
6. **Fail soft.** Bad rows become issues in `site/data/*.json` (the owner sees them in the editor),
   never a failed build.
7. **Deterministic.** The seed is fixed, so the same data gives the same numbers.
8. **Privacy.** No secrets in the repo. The token lives only in the owner's browser `localStorage`.

## Recurring tasks

- **"Backfill these legs, costs or alternatives":**
  - edit the CSVs directly; keep ids stable, and use waypoint ids in `from`/`to`
  - then run `python -m travel_dashboard check`
- **"I'm on vessel/train X":**
  - research it: EU MRV fuel per nautical mile, capacity, average load for ships; operator factors
    for trains and buses
  - add a `[[vehicles]]` entry with sources
  - add or extend a test
- **Changing the JSON contract:**
  - update `export.py` and the JS reading it in the same change
  - keep `tests/test_build.py` passing
- **Adding a page or asset:** add it to `SHELL` in `site/sw.js` and bump `CACHE`, so phones that
  have the app installed pick it up.

## Environment

- Windows 11; PowerShell is the default shell, Git Bash is available.
- No Node, uv or gh. For a JS syntax check, VS Code's Electron can run as Node:
  `ELECTRON_RUN_AS_NODE=1 "$LOCALAPPDATA/Programs/Microsoft VS Code/Code.exe" --check file.mjs`
  (copy `.js` to `.mjs`, because the modules use top-level await).
- Headless screenshots: `msedge --headless=new --screenshot=out.png --window-size=1280,2000 <url>`,
  with a served site because ES modules need http. Windows clamps windows to ~500 px wide, so check
  phone widths through 390 px iframes.
- Remote: `git@github.com:thaeussner/travel_dashboard.git`, branch `main`. The phone commits too, so
  run `git pull --rebase` before pushing.
