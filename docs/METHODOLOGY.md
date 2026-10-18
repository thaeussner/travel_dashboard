# Emissions methodology

> Draft, 2026-10-18; implemented in `travel_dashboard/` with factors in `config/emissions.toml`. Values marked ✓ were checked against
> the cited source on 2026-10-18. The rest are working estimates to replace with better data.
> Architecture context: [PLAN.md §6](PLAN.md).

## 1. What is counted

- **Unit:** kg CO₂e per passenger, *well-to-wheel* (WTW; for ships, "well-to-wake"). That covers
  producing the fuel or electricity plus using it. CH₄ and N₂O are converted with GWP100.
- **Excluded by default:**
  - building vehicles, ships and infrastructure
  - accommodation, food, and getting to stations and airports
  
  Most published factors (DESNZ, SNCF, ISO 14083) are operational WTW, so this keeps them comparable.
  Lifecycle values exist for some modes (mobitool) and are shown as a note, not mixed in. They roughly
  triple the very low rail numbers because rail infrastructure dominates its lifecycle.
- **Electricity (rail) is location-based:** the national average grid mix is the central value.
  Operators' market-based claims (green certificates) set the low end of the range. Certificates don't
  change what the grid physically emits, and a single rule keeps SNCF, Renfe and SBB comparable.
  Chalmers' *Travel & Climate* takes the same position.

## 2. Choices vs. uncertainty

The central design idea. Two different things make an emissions number uncertain:

| | **Lenses** (method choices) | **Uncertainty** (parameters) |
|---|---|---|
| what | defensible ways of counting that disagree | values we don't know precisely |
| examples | comparison grain · ferry passenger/freight allocation · typical vs. observed occupancy · aviation non-CO₂ in or out | emission factors · distances · engine load · fuel use · size of the non-CO₂ effect |
| shown as | switches that change every number on the page | 90 % intervals (p5–p95) within the selected lens |
| combined how | never: each combination is a separate scenario | Monte Carlo, 4,000 draws |

Two rules follow:

- **Lenses are symmetric.** A lens applies to actual and counterfactual travel alike. The one asymmetry
  is unavoidable: you can only observe occupancy on vehicles you actually used, so flights you didn't
  take always get typical load factors.
- **Robustness is shown, not claimed.** The headline is computed under all 36 lens combinations, and
  the page shows that spread next to the selected value.

## 3. The comparison: your legs against your alternatives

### 3.1 Same destinations, alternatives chosen by hand

The comparison keeps the places you visited and asks how you would realistically have got between
them otherwise. You enter those alternatives yourself as `alt` rows. Usually they are flights with
their real routings (e.g. via Paris for the French Antilles), but any mode works: a slower ferry, a
car, a bus. The comparison doesn't model a different trip you might have taken if you flew. That
question has no defensible answer.

### 3.2 Waypoints, legs and alternatives

- **Waypoints** are typed by hand:
  - **destination:** a place you would have gone anyway
  - **stop:** exists only because of how you travelled; Hendaye is the canonical example

  There is no rule based on nights.
- **Legs** connect waypoints: what actually happened.
- **An alternative option** is a chain of `alt` rows sharing one name. It replaces every leg between
  its first and last waypoint. Connection points such as "Paris Orly" are plain text, not waypoints.
- **Several options** may cover the same span, e.g. direct vs. via Madrid, or flight vs. car. The one
  marked **main** counts; the others are shown next to it for comparison.
- **Local trips** start and end at the same waypoint, e.g. driving around La Palma. They belong to no
  journey and have no alternative, so they count the same in both worlds. They appear in the totals,
  in the "Local travel" row and under their waypoint on the route.

### 3.3 Two levels (lens)

| level | journeys | alternative used |
|---|---|---|
| **Destinations** (default) | each pair of consecutive destinations | the main option spanning exactly that pair |
| **Every stop** | inside each destination span, the finest chain of stop-level options covering it | falls back to the destination-level option where stop-level options don't cover the whole span |

- An option is **stop-level** when at least one of its ends is a stop.
- These options are reported and not used:
  - a destination-level option that skips a destination
  - a stop-level option that crosses a destination
- A journey without any alternative counts the same in both worlds, so no saving is claimed for it.
  Local trips are the typical case.

A single flight from home to the final destination (Switzerland → Caribbean) is deliberately not a
level. Nobody spending a month on Tenerife would have flown past it.

### 3.4 Timing and scope

A journey switches to its alternative on the date of its **last** leg. Savings are therefore only
claimed for completed journeys. "Trip so far" counts everything dated up to today; "including planned
travel" adds the prefilled future.

### 3.5 Distances

Distances are entered by hand:

- **Trains, buses and ships:** route km, e.g. the operator's figure (68 nm = 126 km for Los
  Cristianos–La Palma).
- **Flights:** great-circle km. The model adds 8 % for routing (range 4–12 %).
  - Leave `km` empty and the build computes the great-circle distance between the airports at both
    ends: the waypoint's `airport`, or a code in a via point (`BCN`, `Barcelona (BCN)`).
  - Airports come from `data/reference/airports.csv`: 4,008 airports with scheduled service, from
    OurAirports (public domain). Refresh it with `python -m travel_dashboard airports`.

When estimating rail or road km from a map's straight line, multiply by the network circuity:
about 1.45 for rail and 1.25 for road in France, Spain and Switzerland (Heinold & Makowski 2026).

### 3.6 Left out on purpose

- Airport and station access trips: small, and partly cancelling.
- Rebound effects: the money or time saved by flying.

## 4. Per-mode methods (summary)

| mode | method | central (g CO₂e/pkm) | range | grade |
|---|---|---|---|---|
| TGV / TGV Lyria | factor × timetable km | 2.3 / 2.5 | 1.4–6 | C |
| Spanish rail (AVE, Alvia) | factor × km | 8 / 11 | 3.6 (Renfe, market-based) – 25 | C |
| Coach | factor × road km | 32 | 25–48 | C/D |
| Local bus | factor × km | ~130–157 | wide; depends on load | D |
| Car / taxi | 209 g per vehicle-km (petrol, WTW) ÷ occupants | — | — | C/D |
| Ferry | ship model × allocation lens × occupancy lens (§5) | — | — | B–D |
| Sailing yacht | litres of diesel × 3.29 ÷ crew | — | 50–400 L per crossing | A when logged |
| Flight (counterfactual, or actual if you ever fly) | per-flight fuel model + non-CO₂ lens (§6) | — | — | C |

**Occupancy.** Every mode is modelled per vehicle, then divided by the people on board:

- **"Typical":** the load factor behind the published factor or the vessel's data.
- **"As observed":** your head count (`occ_obs`) against the capacity (`occ_max`).

So a near-empty bus or ferry counts against you under "As observed". Rows without a head count are
the same under both settings.

**Distances** are entered by hand (§3.5).

### 4.1 Rail

| source | value | scope |
|---|---|---|
| SNCF Info GES (2025 data) ✓ | TGV 2.1 (INOUI 2.3, OUIGO 1.4) · Lyria 2.5 · Intercités 4.8 · TER 19 · France–Spain 5.5 | WTW, location-based French mix (51.9 g/kWh) |
| SNCF incl. rolling stock ✓ | TGV 3.0 · Intercités 6.1 · TER 23.7 | + maintenance and manufacture |
| ADEME Base Carbone (2022 data) ✓ | TGV 2.93 · Intercités 7.5 · TER 27.7 | incl. train manufacture |
| Renfe (2025) ✓ | 3.58, company-wide | market-based (100 % renewable certificates) |
| EEA / CE Delft (2018 data) ✓ | high-speed 15.8 · conventional 41.2 · all 33.4 | location-based, EU grids |
| mobitool v3.1 ✓ | Swiss train 7.0 (4.8 of it infrastructure) · TGV 12.5 | full lifecycle |

The Spanish values (AVE 8, Alvia 11) are location-based estimates: about 150 g/kWh grid (Ember, 2025
lifecycle) times typical energy use. Renfe's 3.6 is the low end.

### 4.2 Road

| mode | source | value | notes |
|---|---|---|---|
| Coach | DESNZ 2025 ✓ | 27.8 TTW + 6.6 WTT = 34.3 WTW | assumes 17.6 passengers |
| Coach | DESNZ 2026 ✓ | 39.5 TTW | method changed (National Express data), so pick the vintage deliberately |
| Coach | FlixBus 2025 ✓ | Iberia 27.2 · France 25.5 | actual passenger-km |
| Local bus | DESNZ 2025 ✓ | outside London 157 WTW | assumes 11 passengers. Island buses (TITSA) sit somewhere in 60–160 depending on load. |
| Car | DESNZ 2025 ✓ | g per vehicle-km, WTW, read from the vehicle text (see below) | divided by occupants. The page shows 209 (alone) and 52 (four aboard) as references. |

**Cars by size and fuel** (DESNZ 2025 ✓, g CO₂e per vehicle-km, combustion + fuel supply):

| size | petrol | diesel | hybrid |
|---|---|---|---|
| small | 183 | 177 | 144 |
| average | 209 | 215 | 161 |

- **What decides the class:** size and fuel are read from the vehicle text. "Citroën C1 (95)" is a
  small petrol car; "Golf TDI" is an average diesel.
- **Per km, the fuel type hardly matters** (about ±3 %). Size does: a small car is about 12 % below
  the average.
- **Per litre, the fuel type does matter.** If you log litres refuelled, petrol (EU 95 E5) is 2.90
  and diesel (EU B7) 3.22 kg CO₂e/L, so diesel is about 11 % more per litre. Logged litres beat any
  factor (grade A).
- **Electric cars:** about 0.19 kWh/km times the grid where they charge.
  - Switzerland and France: about 0.06 kg/kWh.
  - Spanish mainland: about 0.15.
  - Canary Islands: 0.58–0.69 (ULPGC). Renewables were only 19 % of Canary generation in 2023 (REE).
  - So an electric car on La Palma is only 20–30 % below a small petrol car. The range is set at
    15–150 g/km.

### 4.3 How a travel row finds its data

The mode is only the starting point. Each row gets the most specific data available, in this order:

1. **Mode defaults:** `[modes.<mode>]` in `config/emissions.toml`, e.g. a generic ro-pax ferry
   (grade D).
2. **A named vehicle:** the `vehicle` text is matched against the `[[vehicles]]` entries.
   - **How the match works:** whole words, case-insensitive. The first match wins, and the entry's
     mode must agree with the row's.
   - **What it brings:** that service's or ship's own data. For "Balearia / Fred Olsen: Marie Curie"
     that is the Marie Curie's fuel per nautical mile from EU MRV, its 880 places and its typical
     load (grade B).
3. **Cars and planes:**
   - Cars get size and fuel from words in the text (§4.2).
   - Planes get an aircraft class from the aircraft name: A320 is narrow-body, A350 wide-body, ATR a
     turboprop. Without a name, the class is chosen by distance.
4. **Your observations** override typical values:
   - observed and maximum occupancy, used by the "As observed" lens
   - logged litres, which make the row grade A

The trip editor shows the match live under the vehicle field ("Data: Marie Curie · grade B"). The
page's trace names the profile and its sources. To cover a new ship, train or bus, add a
`[[vehicles]]` entry with sources:

- **Ships:** EU MRV publishes fuel, distance and passengers for every ship over 5,000 GT that calls
  at EU ports.
- **Trains and buses:** operators often publish g/pkm.

### 4.4 Sailing

- **Method:** fuel-based. Litres used for motoring and charging × 3.29 kg CO₂e/L ÷ crew.
  - Fuel factors (DESNZ 2025 ✓): fossil diesel 3.29, marine gas oil 3.40 kg CO₂e/L WTW.
  - Log the actual litres and crew size on arrival (grade A).
- **Default when not logged:** 50–400 L per Atlantic crossing.
  - No published average exists; the range is an estimate.
  - An ARC skipper survey (2024 rallies, 234 boats) reports a median of about 3 h/day of engine or
    generator charging.
  - ARC 2025 averaged about 5.5 crew per boat.
  - So 150 L shared by 5.5 crew is about 90 kg per person, or about 18 g/pkm.
- **Not included:** building the boat (on the order of 30 t CO₂e for a 10 m yacht, shared over decades
  and many crews).
- **The marginal view:** the boat would have sailed anyway, so your extra impact is close to zero. That
  view isn't applied anywhere else either (§5.3).

## 5. Ferries

### 5.1 Why ferries are the hard part

Published per-passenger ferry factors range from about **20 to about 1,000 g CO₂e/pkm**. Three things
drive that spread:

1. **Who the ship is for.** A ro-pax ferry carries passengers, cars and freight. On the
   mainland–Canaries line, trailers make up most of the payload. Splitting the fuel between them is the
   biggest single choice.
2. **Speed.** High-speed craft (35–40 kn) burn about as much fuel per nautical mile as big conventional
   ships, but carry far less freight to share it with:

   | ship type | fuel per nautical mile (EU MRV) |
   |---|---|
   | Fred. Olsen fast craft | 139–214 kg |
   | conventional ro-pax | 125–257 kg |

3. **Occupancy.** The Bencomo Express averaged about 260 passengers per sailing in 2025, 30 % of its
   859 places. On your crossing there were about 150.

### 5.2 Ship model

**Formula:** `E_sailing = fuel per nautical mile × nautical miles × WTW factor`

**Data hierarchy:**

- **A:** the operator's per-sailing fuel.
- **B:** the vessel's annual **EU MRV** report. It's public per ship: fuel, CO₂, distance, hours at
  sea and passengers. Every ship over 5,000 GT calling at EU ports reports.
- **C:** generic values for the ship class.

**Fuel factors:**

| fuel | t CO₂e per t fuel (WTW) | basis |
|---|---|---|
| MGO | 3.88 | 3.206 t CO₂/t (IMO 4th GHG Study) + 14.4 g CO₂e/MJ fuel supply (FuelEU Maritime) |
| residual fuel / VLSFO | ≈ 3.68 | |
| LNG, Otto medium-speed engine | 4.38 | includes FuelEU's default 3.1 % methane slip, so LNG is not automatically better |

### 5.3 The allocation lens

| lens | rule | Bencomo, 17 Oct (≈150 aboard) | Huelva → Tenerife (typical load) |
|---|---|---|---|
| **Per passenger** | everything on the passengers; cargo ignored | ≈ 250 kg | ≈ 2.9 t |
| **ISO 14083** (default) | passenger equivalents, ISO 14083 Annex G (table below) | ≈ 120 kg | ≈ 280 kg |
| **By mass** | passenger + luggage 100 kg · car 1.25 t · freight unit 22.2 t (DESNZ) | ≈ 18 kg | ≈ 21 kg |

ISO 14083 passenger equivalents (peq), per item:

| item | peq |
|---|---|
| passenger | 1 |
| car | 1.3 |
| van | 1.3–3.5 |
| rigid truck | 10 |
| articulated truck | 18 |
| unaccompanied trailer | 14 |
| bus | 10 |

**Per passenger** is an upper bound, and misleading for a freight ro-pax. For the long Huelva line it
says one passenger caused 2.9 t, because it ignores the 100 trailers on board.

**Why ISO 14083 is the default.** It is the current international standard for transport emissions,
and passenger equivalents are its recommended procedure for ferries that carry vehicles. The GLEC
Framework uses the same table. Passenger equivalents mix mass and volume, which reflects that cabins,
lounges and restaurants take space without weighing much. The result sits between the two extremes.

**Reference points** (shown on the Method page, not as lenses):

- **DESNZ foot passenger: 23 g/pkm WTW.** Mass-based, built on 2007 UK operator data; passengers get
  "just under 12 %".
- **Chalmers Travel & Climate: 186 g/pkm.** Revenue-based allocation.
- **The operators' own EU MRV allocation.** Bencomo 2025: 719 g/pkm TTW, with 76 % of emissions on
  passengers (about 110 kg WTW for your crossing). Volcán de Tinamar: 36 g/pkm, 1 %.
  - The same ship's passenger share swung from 22 % (2024) to 76 % (2025). The operators' allocation
    method is undisclosed and changes, so it serves as a cross-check only.

Published comparisons confirm the size of the spread. For one EU ro-pax (IVL 2018), the passenger
share was 12 % by mass, 57 % by area-plus-mass and 69 % by area: a factor of 5.6 in g/pkm.

### 5.4 The occupancy lens

- **Typical:** the line's average passengers aboard, from MRV passenger-miles where available,
  otherwise a class default.
- **As observed** (default): your head count (`occ_obs`) against the capacity (`occ_max`).
- **Freight** is always the vessel's typical load from `config/emissions.toml` (the owner's
  choice: no per-trip freight input).
- **Why observed is the default:**
  - ISO 14083 prefers primary data over defaults.
  - It is conservative for a savings claim. A half-empty ferry counts against you.
- **How occupancy interacts with allocation:**
  - Per passenger and ISO: the passenger's share scales roughly with 1 / passengers.
  - By mass: occupancy hardly matters, because cargo dominates the mass.
- **The marginal view** ("the ship sails anyway, so my extra impact is about zero") is not offered for
  any mode. Applied consistently, it would also zero out the flights and say nothing.

### 5.5 Worked example: Bencomo Express, 17 Oct 2026 (illustrative)

The crossing:

```
fuel      145 kg MGO/nm (EU MRV 2025) × 68 nm         ≈ 9.9 t MGO
emissions 9.9 t × 3.88 t CO₂e/t (well-to-wake)        ≈ 38 t CO₂e for the crossing
```

Your share under each lens:

| lens | calculation | your share |
|---|---|---|
| Per passenger | 38 t ÷ 150 passengers | ≈ 250 kg |
| ISO 14083 | 38 t ÷ (150 + ~165 peq for ~75 vehicles, ~5 % trucks) | ≈ 120 kg |
| By mass | 0.1 t ÷ (15 t of passengers + ~180 t of vehicles), × 38 t | ≈ 18 kg |

The alternative, a Binter ATR 72-600 from La Palma (SPC) to Tenerife North (TFN): ≈ 30 kg CO₂ only,
≈ 34 kg with non-CO₂.

The ferry emitted more than the flight under 4 of the 6 allocation × occupancy combinations.

### 5.6 What this means for the trip so far (illustrative)

Under the default lens (ISO 14083, as observed, with non-CO₂):

- **Huelva → Tenerife:** the 33-hour ro-pax crossing (≈ 280 kg) costs about as much as the Edelweiss
  flight Zürich → Tenerife it replaces (≈ 230 kg CO₂ only, ≈ 365 kg with non-CO₂).
- **The two fast-ferry island hops** (≈ 90–120 kg each) are three to four times the Binter flights.
- **Net:** the trip *so far* is roughly break-even with flying. The savings depend almost entirely on
  how ferries are counted: from −2.4 t (per passenger) to +0.45 t (by mass).
- **The Atlantic sail** changes the picture. It's ≈ 120 kg, against ≈ 1.4 t for flying via Paris.

The page shows this through the robustness strip rather than hiding it.

## 6. Flights

### 6.1 Per-flight fuel model

**Fuel per passenger:**

```
fuel per passenger = (LTO fuel + cruise fuel per km × flown km) × (1 − freight share) / (seats × load factor)
CO₂e               = fuel × (3.16 × M + 0.54)
```

- **M** is the non-CO₂ multiplier, applied to combustion CO₂ only (1 under *CO₂ only*).
- **0.54** is the upstream fuel-supply factor (myclimate uses 0.538).

**Per-flight rather than per-km factors:** connections and short hops each pay a take-off and landing
overhead. Distance-band factors like DESNZ's capture that only roughly.

**Aircraft classes:**

| class | example | seats | load factor |
|---|---|---|---|
| narrow-body jet | A320 family | 174–186 | 85 % (IATA 2025: European carriers 84 %) |
| wide-body jet | A330neo / A350, leisure layouts | 300–430 | 83 % |
| turboprop | ATR 72-600 | 72 | ~72 % |

**Distance:** great circle + 8 % routing uplift (DESNZ; range 4–12 %). ICAO instead adds 50, 100 or
125 km depending on distance.

**Calibration:** central values land within about 10 % of DESNZ 2026 (international, economy).

| route | model: CO₂ only / with non-CO₂ | DESNZ 2026 |
|---|---|---|
| ZRH–TFS | ≈ 230 kg / ≈ 365 kg | 248 / 385 |
| ORY–FDF | ≈ 560 kg / ≈ 900 kg | long-haul economy 643 / 971 |
| TFN–SPC | ≈ 30 kg / ≈ 34 kg | domestic band 24 / 37 |

**Other calculators** (references only):

| calculator | non-CO₂ approach | ZRH–TFS |
|---|---|---|
| myclimate | ×3 since Nov 2023 | ≈ 524 kg |
| atmosfair | ×3, only for CO₂ emitted above 9 km | |
| ICAO | CO₂ only | |

### 6.2 Non-CO₂ effects (lens)

What the science says:

- **Lee et al. 2021.** Non-CO₂ effects (contrails, NOx) are about two-thirds of aviation's net
  warming. The ratio of total effect to CO₂ alone depends on the metric:

  | metric | ERF | GWP20 | GWP50 | GWP100 | GTP | GWP* |
  |---|---|---|---|---|---|---|
  | ratio | 2.9 | 4.0 | 2.3 | 1.7 | 1.0–1.3 | ≈ 3.0 |

- **Teoh et al. 2024.** Contrail forcing is about 44 % below Lee's estimate, and about 2 % of flights
  cause 80 % of contrail warming. Any per-flight multiplier is therefore very uncertain.

What others use:

| who | approach |
|---|---|
| DESNZ | ×1.7 (GWP100) |
| myclimate | ×3 |
| atmosfair | ×3 above 9 km |
| Chalmers | ×1.5 |
| German UBA | 1.5 for domestic flights |
| Nordic harmonised guide (2026) | ≥ 1.7, with a parallel 3.0 |
| Swiss BAFU (2026) | 1–3×, disclosed qualitatively |
| EU MRV non-CO₂ monitoring (since 2025) | weather-based per flight, no fixed factor |

The lens has two settings:

- **CO₂ only**, or
- **+ non-CO₂** (default), with these multipliers:

  | flights | low | central | high |
  |---|---|---|---|
  | jets over 500 km | 1.2 | 1.7 | 3.0 |
  | jets under 500 km | 1.0 | 1.3 | 2.0 |
  | turboprops | 1.0 | 1.1 | 1.4 |

  Turboprops cruise low, where contrails rarely form. UBA's distance-dependent factors show the same
  taper.

Including non-CO₂ is the default because climate impact is the point. Its large uncertainty is shown
as a range, not hidden.

### 6.3 Realistic routings (checked October 2026)

- **ZRH–TFS:** Edelweiss, daily A320, about 4h35. easyJet flies from Geneva and Basel.
- **TFN–SPC:** Binter ATR 72-600, about 30 min, many flights a day.
- **Switzerland → Biarritz:** seasonal direct flights only, roughly June–October.
- **Canaries → Caribbean: no nonstop flights.** Realistic connections:
  - Martinique and Guadeloupe via Paris: Orly with Air Caraïbes or Corsair, CDG with Air France.
  - Barbados, St Lucia and Antigua via London Gatwick (BA).
  - Dominican Republic and Cuba via Madrid.
  
  The hub roughly doubles the distance: TFS–ORY–FDF is 9,664 km against 4,809 km direct.

## 7. Uncertainty propagation

- Each uncertain parameter has a `low / central / high` triple, sampled as a triangular distribution.
  Right-skewed parameters get an asymmetric triangle.
- **Shared draws.** A parameter that is physically the same everywhere is drawn once per Monte Carlo
  draw and reused for every leg that uses it: one TGV factor, one non-CO₂ multiplier, one vessel's fuel
  use. Totals and, crucially, the *difference* "avoided = flying − actual" then get honest intervals.
  Independent draws per leg would understate the spread of totals and misstate the spread of
  differences.
- **Reporting:** p5 / median / p95. Values are rounded to two significant figures on the page, so
  "250 kg" is not falsely precise. Medians of parts don't add up exactly to the median of the total;
  the tables say so.

## 8. Data-quality grades

| grade | meaning | typical case |
|---|---|---|
| A | measured fuel or operator data for that trip | yacht litres logged, ferry operator's per-sailing figure |
| B | vessel- or service-specific model | Bencomo Express from engine power, speed and crossing time |
| C | operator or country-specific factor | SNCF TGV factor, Renfe |
| D | generic factor and/or estimated distance | generic ro-pax, coach without operator data |

## 9. Proposed defaults (to confirm)

| lens / choice | proposed default | why | alternatives on the page |
|---|---|---|---|
| Comparison level | **Destinations** (types set by hand) | matches "where would I have gone anyway" | Every stop |
| Ferry share | **ISO 14083 passenger equivalents** | the standard's recommendation; sits between the extremes | Per passenger, By mass |
| Occupancy | **As observed** where logged | ISO 14083 data hierarchy; conservative for savings | Typical |
| Flights | **+ non-CO₂**, ×1.7 central (1.2–3) | climate impact; Lee et al. 2021 GWP100, as DESNZ | CO₂ only |
| Electricity | location-based grid mix | physical emissions; one rule for all operators | (range low end: market-based) |
| Boundary | WTW, no infrastructure or vehicle manufacture | comparable with published factors | lifecycle shown as a note |

Methodological questions for you:

1. **Ferry headline.** Are you comfortable with ISO 14083 as the headline? DESNZ's mass method, used in
   much UK reporting, makes ferries look about 10× better.
2. **Observed vs. typical occupancy** as the default. Observed is honest about *your* trip but noisy
   (one head count).
3. **Non-CO₂ central value.** 1.7 (GWP100: DESNZ, UNFCCC convention) or 3 (GWP*/ERF: myclimate,
   atmosfair, SCNAT)?
4. **Getting home.** Once you know how you'll get back, that journey belongs in the comparison too.

## 10. Sources

**Ferries and shipping:**

- **ISO 14083:2023**, Annex G passenger equivalents, via the CLECAT guide. https://www.clecat.org/media/clecat-guide-to-iso-14083---greenhouse-gas-emissions-in-the-transport-sector.pdf
- **GLEC Framework v3.1 (2024).** https://knowledgeplatform.ecta.com/wp-content/uploads/2024/10/GLEC_FRAMEWORK_v3_23_10_24_B.pdf
- **EU MRV public emission reports (EMSA THETIS-MRV), 2024–2025.** https://mrv.emsa.europa.eu/
- **DESNZ 2026 methodology report**, ferries §7.5–7.10. https://assets.publishing.service.gov.uk/media/6a2940543b15d05a7ce3202e/2026-GHG-conversion-factors-methodology-report.pdf
- **IVL / Lighthouse (Fridell et al. 2018):** allocation on ro-pax. https://lighthouse.nu/images/pdf/mrv_webb.pdf
- **IMO Fourth GHG Study 2020:** SFOC and carbon factors.
- **FuelEU Maritime**, Regulation (EU) 2023/1805, Annex II.
- **Fred. Olsen Express**, Bencomo Express fleet page. https://www.fredolsen.es/en/during-your-trip/fleet/bencomo-express

**Flights:**

- **DESNZ 2026** conversion factors. https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026
- **ICAO Carbon Emissions Calculator Methodology v13.1 (2024).**
- **myclimate flight calculator.** https://www.myclimate.org/en/information/about-myclimate/downloads/flight-emission-calculator/
- **atmosfair** method documentation (2021).
- **Lee et al. (2021)**, *Atmospheric Environment* 244:117834. https://doi.org/10.1016/j.atmosenv.2020.117834
- **Teoh et al. (2024)**, *ACP* 24:6071. https://acp.copernicus.org/articles/24/6071/2024/
- **UBA TEXTE 153/2024**, cluster model for aviation non-CO₂. https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/153_2024_texte_clustermodell_flugverkehr.pdf
- **Nordic harmonised guide on flight emissions (2026).** https://exponentialroadmap.org/wp-content/uploads/2026/01/Harmonised-guide-on-quantifying-GHG-emissions-from-flights.pdf
- **IATA load factors 2025.** https://www.iata.org/en/pressroom/2026-releases/2026-01-29-02/

**Land, sailing, general:**

- **DESNZ 2025 and 2026:** GHG conversion factors. https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025
- **SNCF:** Info GES general methodology. https://www.groupe-sncf.com/medias-publics/2024-04/methodologie-generale-infoges.pdf
- **ADEME Base Carbone.** https://data.ademe.fr/datasets/base-carboner
- **CE Delft for EEA (2021):** Methodology for GHG efficiency of transport modes. https://cedelft.eu/wp-content/uploads/sites/2/2021/05/CE_Delft_200258_Methodology_GHG_Efficiency_Transport_Modes.pdf
- **FlixBus (2026):** Avoided emissions methodology. https://corporate.flix.com/wp-content/uploads/2026/03/2025-Avoided-Emissions-Methodology-Document.pdf
- **mobitool v3.1 / Umweltrechner Verkehr.** https://www.energieschweiz.ch/programme/umweltrechner-verkehr/
- **Chalmers, Travel & Climate methodology v5.1 (2026).** https://research.chalmers.se/publication/552384/file/552384_Fulltext.pdf
- **Heinold & Makowski (2026):** circuity of road and rail networks in Europe. *Networks and Spatial Economics* 26(2), doi:10.1007/s11067-026-09729-y
- **Yachting World (2025):** ARC skipper energy survey. https://www.yachtingworld.com/arc/battery-power-onboard-hundreds-of-ocean-crossing-skippers-share-their-secrets-158731
- **searoute (PyPI).** https://pypi.org/project/searoute/
