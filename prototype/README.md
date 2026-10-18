# Prototype (throwaway)

A design mockup of the emissions page, used to agree on concepts before building the real thing
(see `docs/PLAN.md`).

- `emissions-mockup.html`: the page. It is an artifact fragment without a `<head>`, published privately
  at https://claude.ai/artifact/DJHjUU6ApWnB9fgiLedwA7.
- `mock_model.py`: a pure-stdlib illustrative model.
  - It computes every number on the page for a *plausible* version of the trip: Monte Carlo with shared
    parameters and all 36 lens combinations.
  - Run `python prototype/mock_model.py` to recompute and re-inject the data into the page.
  - `mock_data.json` is the same data, for inspection.

The route, dates and vessels on legs other than the Bencomo Express are guesses. Treat the numbers as
illustrative until the real logbook data exists. Not production code: the real engine follows
`docs/METHODOLOGY.md` and lives in `src/`.
