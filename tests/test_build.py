"""End-to-end: build the example trip and check the data contract and its invariants."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from travel_dashboard import export
from travel_dashboard.cli import main
from travel_dashboard.profiles import Profiles
from travel_dashboard.tables import read_all

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "trip"
TODAY = dt.date(2026, 10, 18)
DEFAULTS = {"level": "destination", "alloc": "iso", "occ": "observed", "nonco2": "full", "scope": "all"}


def build(draws: int = 300) -> dict:
    tables = read_all(EXAMPLE)
    profiles = Profiles.load(ROOT / "config" / "emissions.toml")
    return export.emissions_json(tables, profiles, TODAY, draws, 1, DEFAULTS)


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build()

    def test_quantiles_are_ordered(self):
        for key, t in self.data["totals"].items():
            for series, q in t.items():
                self.assertLessEqual(q[0], q[1], (key, series))
                self.assertLessEqual(q[1], q[2], (key, series))

    def test_all_lens_combinations_present(self):
        self.assertEqual(len(self.data["totals"]), 2 * 3 * 2 * 2 * 2)
        self.assertEqual(len(self.data["cumulative"]), 2 * 3 * 2 * 2)

    def test_cumulative_ends_at_totals(self):
        for key, cum in self.data["cumulative"].items():
            last = cum[-1]
            total = self.data["totals"][f"{key}|all"]
            self.assertAlmostEqual(last["actual"][1], total["actual"][1], places=1)
            self.assertAlmostEqual(last["avoided"][1], total["avoided"][1], places=1)

    def test_to_date_excludes_planned_travel(self):
        t = self.data["totals"]
        self.assertLess(t["destination|iso|observed|full|todate"]["actual"][1],
                        t["destination|iso|observed|full|all"]["actual"][1])

    def test_ferry_share_drives_the_spread(self):
        t = self.data["totals"]
        per_pax = t["destination|passenger|typical|full|todate"]["avoided"][1]
        mass = t["destination|mass|typical|full|todate"]["avoided"][1]
        self.assertLess(per_pax, 0)
        self.assertGreater(mass, 0)

    def test_local_travel_counts_in_both_worlds(self):
        self.assertGreater(self.data["local_total"]["iso|observed|full|all"][1], 0)
        self.assertEqual([t["id"] for t in self.data["travels"] if t["local"]], ["L10"])
        for level in self.data["journeys"].values():
            for j in level:
                self.assertNotIn("L10", j["legs"])

    def test_deterministic(self):
        a, b = build(100), build(100)
        self.assertEqual(a["totals"], b["totals"])

    def test_cli_build_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main(["build", "--data", str(EXAMPLE), "--today", TODAY.isoformat(), "--draws", "50", "--out", tmp])
            self.assertEqual(rc, 0)
            for name in ("emissions.json", "costs.json", "meta.json"):
                self.assertTrue(json.loads((Path(tmp) / name).read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
