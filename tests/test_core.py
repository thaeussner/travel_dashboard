"""Tests for parsing, the emission model and the trip structure. Run: python -m unittest discover -s tests"""

import datetime as dt
import tempfile
import textwrap
import unittest
from pathlib import Path

from travel_dashboard import factors, geo, trip as trip_mod
from travel_dashboard.model import kg
from travel_dashboard.profiles import Profiles, Sampler
from travel_dashboard.tables import Issue, Travel, Waypoint, read_costs, read_travel, read_waypoints

ROOT = Path(__file__).resolve().parent.parent
PROFILES = Profiles.load(ROOT / "config" / "emissions.toml")
AIRPORTS = geo.load_airports(ROOT / "data" / "reference" / "airports.csv")
CENTRAL = Sampler(None)


def write(tmp: str, name: str, text: str) -> Path:
    p = Path(tmp) / name
    p.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return p


def leg(id, frm, to, mode, km, date="2026-10-01", **kw) -> Travel:
    return Travel(id=id, type="leg", from_=frm, to=to, mode=mode, km=km, date=dt.date.fromisoformat(date), **kw)


def alt(id, option, frm, to, mode="plane", km=1000, main=False, **kw) -> Travel:
    return Travel(id=id, type="alt", from_=frm, to=to, mode=mode, km=km, option=option, main=main, **kw)


def wp(id, type, arrive=None, depart=None) -> Waypoint:
    d = lambda s: dt.date.fromisoformat(s) if s else None  # noqa: E731
    return Waypoint(id, id.title(), type, "", d(arrive), d(depart))


class TestTables(unittest.TestCase):
    def test_costs_fix_ups_and_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "costs.csv", """
                id,date,amount,category,country
                a,2026-10-01,"4,50",coffe,Spain
                b,2026-10-02,12,snacks,
                c,not-a-date,3,coffee,Spain
            """)
            issues: list[Issue] = []
            rows = read_costs(p, issues)
        self.assertEqual([r.id for r in rows], ["a", "b"])
        self.assertEqual((rows[0].amount, rows[0].category), (4.5, "coffee"))
        self.assertEqual((rows[1].category, rows[1].country), ("other", "Unknown"))
        self.assertEqual([i.id for i in issues if i.level == "error"], ["c"])

    def test_waypoint_and_travel_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = write(tmp, "waypoints.csv", """
                id,name,type,country,arrive,depart,note
                ,Hendaye,overnight,France,2026-09-26,2026-09-27,
            """)
            t = write(tmp, "travel.csv", """
                id,type,option,main,date,from,to,mode,vehicle,km,occ_max,occ_obs,fuel_l,note
                L1,leg,,,2026-09-26,a,b,Fast Ferry,,126,859,900,,
                L2,leg,,,,a,b,train,,100,,,,
                A1,alt,,yes,,a,b,flight,,500,,,,
            """)
            issues: list[Issue] = []
            wps, travel = read_waypoints(w, issues), read_travel(t, issues)
        self.assertEqual((wps[0].id, wps[0].type), ("hendaye", "stop"))
        self.assertEqual([x.id for x in travel], ["L1", "A1"])
        self.assertEqual(travel[0].mode, "fast_ferry")
        self.assertEqual((travel[1].mode, travel[1].option, travel[1].main), ("plane", "A1", True))
        self.assertTrue(any("above the maximum" in i.message for i in issues))


class TestModel(unittest.TestCase):
    def test_factor_mode_uses_published_factor_at_typical_load(self):
        t = leg("L", "a", "b", "train", 610, vehicle="TGV Lyria", occ_max=507)
        p = PROFILES.resolve(t)
        self.assertEqual(p.label, "TGV Lyria")
        self.assertAlmostEqual(kg(t, p, CENTRAL, occ="typical"), 610 * 2.5 / 1000)

    def test_observed_occupancy_rescales(self):
        t = leg("L", "a", "b", "coach", 100, occ_max=50, occ_obs=10)
        p = PROFILES.resolve(t)
        typical = kg(t, p, CENTRAL, occ="typical")
        observed = kg(t, p, CENTRAL, occ="observed")
        self.assertAlmostEqual(observed / typical, 50 * 0.5 / 10)

    def test_ferry_allocation_order(self):
        t = leg("L", "a", "b", "fast_ferry", 126, vehicle="Bencomo Express", occ_max=859, occ_obs=150)
        p = PROFILES.resolve(t)
        vals = {a: kg(t, p, CENTRAL, alloc=a, occ="observed") for a in ("passenger", "iso", "mass")}
        self.assertGreater(vals["passenger"], vals["iso"])
        self.assertGreater(vals["iso"], vals["mass"])
        # ISO: 38.3 t over 150 passengers + ~160 passenger-equivalents of vehicles
        self.assertAlmostEqual(vals["iso"], 123, delta=3)

    def test_flight_classes_and_non_co2(self):
        tp = alt("A", "o", "a", "b", km=139, vehicle="ATR 72-600")
        wide = alt("B", "o", "a", "b", km=6852, vehicle="A350")
        guess = alt("C", "o", "a", "b", km=6852)
        self.assertEqual(PROFILES.resolve(tp).flight_class, "turboprop")
        self.assertEqual(PROFILES.resolve(wide).flight_class, "wide")
        self.assertEqual(PROFILES.resolve(guess).flight_class, "wide")
        p = PROFILES.resolve(wide)
        self.assertGreater(kg(wide, p, CENTRAL, nonco2="full"), kg(wide, p, CENTRAL, nonco2="co2"))

    def test_sail_engine_hours(self):
        t = leg("S", "a", "b", "sail", 5300, occ_obs=5, engine_h=40)
        p = PROFILES.resolve(t)
        self.assertEqual(p.grade, "B")
        self.assertAlmostEqual(kg(t, p, CENTRAL, occ="observed"), 40 * 2.5 * 3.33 / 5)

    def test_ship_breakdown_matches_model(self):
        from travel_dashboard.model import ship_breakdown
        t = leg("F", "a", "b", "ferry", 1300, vehicle="Marie Curie", occ_max=880, occ_obs=200)
        p = PROFILES.resolve(t)
        b = ship_breakdown(t, p, "observed")
        for alloc in ("passenger", "iso", "mass"):
            self.assertAlmostEqual(b["methods"][alloc]["kg"], kg(t, p, CENTRAL, alloc=alloc, occ="observed"), delta=0.1)
        self.assertAlmostEqual(sum(b["methods"]["iso"]["shares"]), 1, places=3)

    def test_word_matching(self):
        # 'ter' (French regional trains) must not match 'Tenerife'
        self.assertIsNone(PROFILES.match_vehicle("train", "Tren de Tenerife"))
        self.assertEqual(PROFILES.match_vehicle("train", "TER Nouvelle-Aquitaine")["name"], "TER")
        self.assertEqual(PROFILES.match_vehicle("fast_ferry", "Fred. Olsen · Bencomo Express")["name"], "Bencomo Express")

    def test_sail_uses_logged_fuel(self):
        t = leg("L", "a", "b", "sail", 5300, occ_obs=5, fuel_l=150)
        p = PROFILES.resolve(t)
        self.assertEqual(p.grade, "A")
        self.assertAlmostEqual(kg(t, p, CENTRAL, occ="observed"), 150 * 3.33 / 5)   # marine diesel, no biofuel


class TestTrip(unittest.TestCase):
    def setUp(self):
        self.wps = [
            wp("home", "destination", None, "2026-09-26"),
            wp("s1", "stop", "2026-09-26", "2026-09-26"),
            wp("s2", "stop", "2026-09-26", "2026-09-26"),
            wp("d1", "destination", "2026-09-28", "2026-10-10"),
            wp("d2", "destination", "2026-10-10", None),
        ]
        self.legs = [
            leg("L1", "home", "s1", "train", 300, "2026-09-26"),
            leg("L2", "s1", "s2", "train", 200, "2026-09-26"),
            leg("L3", "s2", "d1", "ferry", 900, "2026-09-27"),
            leg("L4", "d1", "d2", "fast_ferry", 120, "2026-10-10"),
        ]

    def test_ordering_breaks_date_ties_with_legs(self):
        shuffled = [self.wps[2], self.wps[0], self.wps[4], self.wps[1], self.wps[3]]
        t = trip_mod.build(shuffled, self.legs, [])
        self.assertEqual([w.id for w in t.waypoints], ["home", "s1", "s2", "d1", "d2"])

    def test_destination_level_uses_main_option(self):
        alts = [alt("A1", "direct", "home", "d1"), alt("A2", "via", "home", "Hub"), alt("A3", "via", "Hub", "d1", main=True)]
        t = trip_mod.build(self.wps, self.legs + alts, [])
        j = t.journeys["destination"][0]
        self.assertEqual((j.option.id, [o.id for o in j.extras]), ("via", ["direct"]))
        self.assertEqual([x.id for x in j.legs], ["L1", "L2", "L3"])
        self.assertEqual(j.date, dt.date(2026, 9, 27))

    def test_stop_level_tiles_or_falls_back(self):
        alts = [alt("A1", "direct", "home", "d1"),
                alt("S1", "first", "home", "s1", main=True), alt("S2", "rest", "s1", "d1", main=True)]
        t = trip_mod.build(self.wps, self.legs + alts, [])
        self.assertEqual([j.option.id for j in t.journeys["stop"][:2]], ["first", "rest"])
        # without the second tile the destination-level alternative is used
        t2 = trip_mod.build(self.wps, self.legs + alts[:2], [])
        self.assertEqual(t2.journeys["stop"][0].option.id, "direct")

    def test_local_travel_stays_out_of_journeys(self):
        local = leg("C1", "d1", "d1", "car", 300, "2026-10-03", occ_obs=2)
        alts = [alt("A1", "direct", "home", "d1"), alt("A2", "hop", "d1", "d2")]
        issues: list[Issue] = []
        t = trip_mod.build(self.wps, self.legs + [local] + alts, issues)
        self.assertEqual([w.id for w in t.waypoints], ["home", "s1", "s2", "d1", "d2"])
        self.assertIn("C1", [x.id for x in t.legs])
        for level in t.journeys.values():
            for j in level:
                self.assertNotIn("C1", [x.id for x in j.legs])
        self.assertFalse(any(i.id == "C1" for i in issues))

    def test_broken_options_are_reported(self):
        issues: list[Issue] = []
        alts = [alt("A1", "gap", "home", "X"), alt("A2", "gap", "Y", "d1"),
                alt("A3", "skip", "home", "d2")]
        t = trip_mod.build(self.wps, self.legs + alts, issues)
        self.assertEqual([o.id for o in t.options], ["skip"])
        self.assertIsNone(t.journeys["destination"][0].option)
        msgs = " ".join(i.message for i in issues)
        self.assertIn("one chain", msgs)
        self.assertIn("skips a destination", msgs)


class TestGeoAndCars(unittest.TestCase):
    def test_airport_codes(self):
        self.assertEqual(geo.airport_code("Barcelona (BCN)", {}, AIRPORTS), "BCN")
        self.assertEqual(geo.airport_code("bcn", {}, AIRPORTS), "BCN")
        self.assertEqual(geo.airport_code("la-palma", {"la-palma": "SPC"}, AIRPORTS), "SPC")
        self.assertIsNone(geo.airport_code("Paris Orly", {}, AIRPORTS))

    def test_fill_flight_km_from_codes(self):
        wps = [Waypoint("zurich", "Zürich", "destination", airport="ZRH"), Waypoint("lp", "La Palma", "destination")]
        rows = [alt("A1", "o", "zurich", "BCN", km=None), alt("A2", "o", "BCN", "lp", km=None)]
        issues: list[Issue] = []
        out = geo.fill_flight_km(rows, wps, AIRPORTS, issues)
        self.assertEqual([t.id for t in out], ["A1"])               # lp has no airport: reported, skipped
        self.assertAlmostEqual(out[0].km, 850, delta=15)
        self.assertEqual(out[0].km_note, "great circle ZRH–BCN")
        self.assertEqual([i.id for i in issues], ["A2"])

    def test_car_class_from_vehicle_text(self):
        self.assertEqual(PROFILES.car_class("Citroën C1 (95)"), ("small", "petrol"))
        self.assertEqual(PROFILES.car_class("VW Golf TDI"), ("average", "diesel"))
        self.assertEqual(PROFILES.car_class("Toyota Yaris Hybrid"), ("small", "hybrid"))
        self.assertEqual(PROFILES.car_class("rental car"), ("average", "petrol"))

    def test_small_petrol_car_and_logged_litres(self):
        t = leg("C", "lp", "lp", "car", 300, occ_obs=2, vehicle="Citroën C1 (95)")
        p = PROFILES.resolve(t)
        self.assertEqual((p.label, p.grade), ("small petrol car", "C"))
        self.assertAlmostEqual(kg(t, p, CENTRAL, occ="observed"), 300 * 0.183 / 2, places=2)
        t2 = leg("C", "lp", "lp", "car", 300, occ_obs=2, vehicle="Citroën C1 (95)", fuel_l=18)
        p2 = PROFILES.resolve(t2)
        self.assertEqual(p2.grade, "A")
        self.assertAlmostEqual(kg(t2, p2, CENTRAL, occ="observed"), 18 * 2.90 / 2, places=2)


class TestFactors(unittest.TestCase):
    TABLE = factors.table(PROFILES, {"alloc": "iso", "nonco2": "full"}, draws=300, seed=1)

    def row(self, title):
        return next(r for r in self.TABLE["rows"] if r["title"] == title)

    def test_defaults_come_from_the_config(self):
        self.assertEqual(self.row("Train")["g"], 15)
        self.assertAlmostEqual(self.row("Car")["g"], 209 / 1.6, places=1)          # average petrol car
        self.assertAlmostEqual(self.row("Sailing yacht")["g"], 3 / 100 * 3.33 / 5.5 * 1000, places=1)
        self.assertEqual(self.row("Walk")["g"], 0)
        for r in self.TABLE["rows"]:
            self.assertLessEqual(r["range"][0], r["range"][1], r["title"])

    def test_flights_and_ferries_match_the_model(self):
        t = leg("F", "a", "b", "plane", 1000)
        p = PROFILES.resolve(t)
        r = self.row("Plane, 1,000 km")
        self.assertAlmostEqual(r["g"], kg(t, p, CENTRAL, nonco2="full"), places=1)   # kg per 1000 km = g/km
        self.assertEqual([o["label"] for o in r["other"]], ["CO₂ only"])
        self.assertIn("Wide-body", self.row("Plane, 7,000 km")["basis"])
        f = self.row("Ferry")
        self.assertEqual([o["label"] for o in f["other"]], ["per passenger", "by mass"])
        self.assertTrue(f["other"][1]["g"] < f["g"] < f["other"][0]["g"])

    def test_every_named_vehicle_is_listed(self):
        named = [r["title"] for r in self.TABLE["rows"] if r["group"] == "named"]
        for v in PROFILES.vehicles:
            self.assertIn(v["name"], named)
        self.assertIn("Small petrol car", named)
        self.assertEqual(self.row("Huelva–Canarias ro-pax")["profile"], "Huelva–Canarias ro-pax")   # forced, not matched


if __name__ == "__main__":
    unittest.main()
