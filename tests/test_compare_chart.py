"""site_src/chart.js (the History tab's chart builder) and site_src/sidebyside.js (its compare tray), run in Node on
made-up records. Skipped where Node is not installed."""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHART = (ROOT / "site_src" / "chart.js").as_uri()
CMP = (ROOT / "site_src" / "sidebyside.js").as_uri()
NODE = shutil.which("node")

SCRIPT = """
import * as CH from %s;
import * as CMP from %s;
const recs = [
  { id: "a", year: "2024", veh: "Falcon 9", cc: "US", prog: ["Starlink"] },
  { id: "b", year: "2024", veh: "Falcon 9", cc: "US", prog: ["Starlink", "Rideshare"] },
  { id: "c", year: "2026", veh: "Long March 2D", cc: "CN", prog: [] },
  { id: "d", year: "2026", veh: "Soyuz-2.1b", cc: "RU", prog: [] },
  { id: "e", year: "", veh: "", cc: "IN", prog: [] },
];
const out = {};
out.byVeh = CH.aggregate(recs, { x: (r) => r.veh, split: (r) => r.cc, order: ["US", "CN", "RU"] });
out.byYear = CH.aggregate(recs, { x: (r) => r.year, time: "year" });
out.months = CH.aggregate([{ m: "2025-11" }, { m: "2026-02" }], { x: (r) => r.m, time: "month" }).cats.map((c) => c.key);
out.prog = CH.aggregate(recs, { x: (r) => r.prog });
out.top = CH.aggregate(recs, { x: (r) => r.id, top: 2 });
out.splitTop = CH.aggregate(recs, { x: () => "all", split: (r) => r.id, splitTop: 2 });
out.ticks = [CH.ticks(0), CH.ticks(7), CH.ticks(130), CH.ticks(1)];
out.parse = [CH.parseChart("veh.cc", ["veh", "year"], ["", "cc"]), CH.parseChart("year.", ["veh", "year"], ["", "cc"]),
  CH.parseChart("veh.bogus", ["veh"], ["", "cc"]), CH.parseChart("nope.cc", ["veh"], ["cc"]), CH.parseChart(null, ["veh"], [])];
out.param = [CH.chartParam({ by: "veh", split: "cc" }), CH.chartParam({ by: "year", split: "" }), CH.chartParam(null)];
out.ids = [CMP.parseIds("x|y|x||z|w|v"), CMP.parseIds(null)];
out.add = CMP.toggle(["x"], "y");
out.drop = CMP.toggle(["x", "y"], "x");
out.full = CMP.toggle(["a", "b", "c", "d"], "e");
const fields = [{ label: "Vehicle", get: (r) => r.veh }, { label: "Country", get: (r) => r.cc }, { label: "Nothing", get: () => null },
  { label: "Year", get: (r) => r.year }];
out.rows = CMP.rows([recs[0], recs[1]], fields);
out.one = CMP.rows([recs[2]], fields);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node is not installed")
class CompareChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        res = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % (json.dumps(CHART), json.dumps(CMP))],
                             capture_output=True, text=True, check=True)
        cls.o = json.loads(res.stdout)

    def test_counts_by_a_field_split_by_another_in_a_fixed_order(self):
        a = self.o["byVeh"]
        self.assertEqual([c["key"] for c in a["cats"]], ["Falcon 9", "Long March 2D", "Soyuz-2.1b"])
        self.assertEqual(a["cats"][0], {"key": "Falcon 9", "total": 2, "parts": {"US": 2}})
        self.assertEqual(a["series"], ["US", "CN", "RU"])
        self.assertEqual(a["skipped"], 1)

    def test_time_axes_fill_the_empty_years_and_months(self):
        self.assertEqual([(c["key"], c["total"]) for c in self.o["byYear"]["cats"]], [("2024", 2), ("2025", 0), ("2026", 2)])
        self.assertEqual(self.o["months"], ["2025-11", "2025-12", "2026-01", "2026-02"])

    def test_a_launch_with_two_values_counts_in_both_and_says_so(self):
        p = self.o["prog"]
        self.assertTrue(p["multi"])
        self.assertEqual({c["key"]: c["total"] for c in p["cats"]}, {"Starlink": 2, "Rideshare": 1})
        self.assertEqual(p["skipped"], 3)

    def test_bars_and_series_past_the_limit_fold_into_others(self):
        t = self.o["top"]
        self.assertEqual([c["key"] for c in t["cats"]], ["a", "b", "__other"])
        self.assertEqual(t["folded"], 3)
        self.assertEqual(t["cats"][-1]["total"], 3)
        s = self.o["splitTop"]
        self.assertEqual(s["series"], ["a", "b", "__other"])
        self.assertEqual(s["cats"][0]["parts"], {"a": 1, "b": 1, "__other": 3})

    def test_ticks_are_round_and_cover_the_maximum(self):
        z, seven, big, one = self.o["ticks"]
        self.assertEqual(z, [0])
        self.assertEqual(seven, [0, 2, 4, 6, 8])
        self.assertEqual(big, [0, 50, 100, 150])
        self.assertEqual(one, [0, 0.5, 1])

    def test_the_chart_choice_round_trips_through_the_address(self):
        self.assertEqual(self.o["parse"], [{"by": "veh", "split": "cc"}, {"by": "year", "split": ""},
                                           {"by": "veh", "split": ""}, None, None])
        self.assertEqual(self.o["param"], ["veh.cc", "year.", None])

    def test_the_tray_holds_four_without_repeats(self):
        self.assertEqual(self.o["ids"], [["x", "y", "z", "w"], []])
        self.assertEqual(self.o["add"], {"ids": ["x", "y"], "full": False})
        self.assertEqual(self.o["drop"], {"ids": ["y"], "full": False})
        self.assertEqual(self.o["full"], {"ids": ["a", "b", "c", "d"], "full": True})

    def test_side_by_side_rows_mark_differences_and_drop_empty_rows(self):
        rows = {r["label"]: r for r in self.o["rows"]}
        self.assertNotIn("Nothing", rows)
        self.assertFalse(rows["Vehicle"]["differ"])
        self.assertFalse(rows["Country"]["differ"])
        self.assertEqual(rows["Year"]["cells"], ["2024", "2024"])
        self.assertFalse(any(r["differ"] for r in self.o["one"]))


if __name__ == "__main__":
    unittest.main()
