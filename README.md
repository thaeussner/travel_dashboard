# Flight-free travel

A personal dashboard for a slow trip:

- **Costs:** CHF amounts by date, category and country.
- **Emissions:** each leg, against the realistic alternatives you would have taken instead.

It's a static site on GitHub Pages. Friends can view it; only you can edit.

## Setup (once)

1. Push this repo to GitHub.
2. In the repo, go to **Settings → Pages → Build and deployment** and set **Source: GitHub Actions**.
3. The workflow in `.github/workflows/build.yml` tests, builds and deploys on every push. It also
   runs once a day.
4. The site appears at `https://thaeussner.github.io/travel_dashboard/`.

## Enable editing on your phone

1. Create a fine-grained token at
   [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new):
   - **Repository access:** only `travel_dashboard`
   - **Permissions → Contents:** Read and write
   - **Expiration:** up to a year
2. Open the site and tap **Owner** at the bottom of any page. Paste the token.
3. The token stays in that browser only. Friends don't have it, so they can't edit. If the phone is
   lost, revoke the token on GitHub.
4. Add the site to the home screen. On iPhone: Share → Add to Home Screen.

Edits are saved to the CSV files in `data/` straight away. If you're offline, they wait on the phone
and go up when you're back online. Charts for friends update after the next build, about 2 minutes
later.

## Data (plain CSV, editable by hand too)

| file | columns |
|---|---|
| `data/costs.csv` | `id, date, amount, category, country` |
| `data/waypoints.csv` | `id, name, type, country, arrive, depart, note, airport` |
| `data/travel.csv` | `id, type, option, main, date, from, to, mode, vehicle, km, occ_max, occ_obs, fuel_l, engine_h, note` |

**Costs:**

- `amount` is CHF.
- `category` is one of groceries, coffee, treats, activities, accommodation, transport,
  restaurants, other.

**Waypoints:**

- `type` is `destination` (a place you'd have gone anyway) or `stop`.
- `airport` lists the IATA codes of the airports a flight from here would use, e.g. `SPC` or
  `TFS TFN`. The first is the default.

**Travel:**

- `type` is `leg` (it happened) or `alt` (an alternative).
- Alternative rows with the same `option` name form one alternative, e.g. a flight connecting in
  Paris. The alternative replaces every leg between its first and last waypoint.
- `main = 1` marks the alternative that counts for that span.
- A leg with the same `from` and `to` is a local trip, e.g. driving around La Palma. It has no
  alternative and counts the same in both worlds. In the form, tick "Local trip".
- `from` and `to` are waypoint ids. Intermediate points of an alternative can be plain text. A
  flight alternative may also start or end at an airport its waypoint lists, e.g. `TFN` for
  El Médano (`TFS TFN`), so you can write the whole connection in codes: `TFN → BCN → CDG → FDF`.
- `km` is entered by hand. For flights, either enter the great-circle distance or leave `km`
  empty: the build then computes it from airport codes, i.e. the waypoint's `airport` or a code in
  a via point such as `BCN` or `Barcelona (BCN)`. It is also optional when `fuel_l` or `engine_h`
  is given.
- `occ_max` and `occ_obs` are capacity and observed head count.
- `fuel_l` is litres burnt by the whole vehicle (sailing, car).
- `engine_h` is engine and generator hours on a sailing yacht, used when the litres are unknown.
  Add about half an hour per hour of dinghy use: the dinghy is not a mode of its own.
- `vehicle` picks the data. Use a ship or train name ("Marie Curie", "TGV Lyria"), an aircraft
  ("A320") or a car with its fuel ("Citroën C1 (95)"). The form shows what it matched.

**Emission factors and vessels** live in `config/emissions.toml`, each with its source. The
reasoning is in `docs/METHODOLOGY.md`. The site's Method page explains it in plain language, with
the trip's own ferries as examples and a table of the default factor of every mode.

## Local preview

No dependencies beyond Python ≥ 3.12.

```bash
python -m travel_dashboard build --data examples/trip --today 2026-10-18   # example trip
python -m travel_dashboard build                                           # your data/
python -m travel_dashboard serve                                           # http://localhost:8000
python -m travel_dashboard check                                           # list data issues
python -m unittest discover -s tests
```
