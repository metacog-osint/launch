"""Payload reference rates (launch/payloads.py) and the payloads command: offline, synthetic records."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import payloads  # noqa: E402

PAD = [102.03, 28.25]          # Xichang
OTHER_PAD = [100.29, 40.96]    # Jiuquan
AREA = [[107.5, 26.9], [108.0, 26.9], [108.0, 26.6], [107.5, 26.6], [107.5, 26.9]]   # ~330 NM east-south-east
FAR = [[60.0, -10.0], [61.0, -10.0], [61.0, -11.0], [60.0, -11.0], [60.0, -10.0]]


def past(i, prog, inc=35.0, pad=PAD, site="Xichang", veh="LM-2D", ring=None, mtype="Military / intelligence", **kw):
    r = {"id": f"gcat:2025-{i:03d}", "status": "launched", "kind": "Orbital", "time": f"2025-{1 + i % 12:02d}-10T01:00:00Z",
         "vehicle": veh, "site": site, "pad": pad, "inc": inc, "programmes": [prog] if prog else [], "mtype": mtype,
         "payload": f"{prog} {i}", "sources": ["gcat"]}
    if ring:
        r["joey_notices"] = [{"ring": ring, "start": None, "end": None}]
    r.update(kw)
    return r


def upcoming(uuid="u1", veh="LM-2D", pad=PAD, site="Xichang", time="2026-12-01T09:00:00Z"):
    return {"id": f"ll2:{uuid}", "ll2": uuid, "status": "upcoming", "kind": "Orbital", "time": time, "vehicle": veh,
            "site": site, "pad": pad, "mtype": payloads.UNKNOWN, "programmes": [], "label": f"{veh} | Unknown Payload",
            "sources": ["ll2"]}


def snap_for(uuid="u1", inc=35.2, ring=AREA, nm=330):
    return {"generated_at": "2026-11-30T00:00:00Z", "areas": [{"ring": ring}],
            "matches": [{"launch": uuid, "level": "time and place", "distance_nm": nm, "area_i": 0, "area": "A1/26",
                         "inclination_est": inc, "inclination_basis": "test"}]}


class ClopperPearson(unittest.TestCase):
    def test_known_values(self):
        lo, hi = payloads.clopper_pearson(5, 10)
        self.assertAlmostEqual(lo, 0.1871, places=3)
        self.assertAlmostEqual(hi, 0.8129, places=3)
        self.assertEqual(payloads.clopper_pearson(0, 10)[0], 0.0)
        self.assertAlmostEqual(payloads.clopper_pearson(0, 10)[1], 0.3085, places=3)
        lo, hi = payloads.clopper_pearson(3, 3)
        self.assertAlmostEqual(lo, 0.2924, places=3)
        self.assertEqual(hi, 1.0)
        lo, hi = payloads.clopper_pearson(30, 32)     # 94% (79-99%)
        self.assertEqual((round(lo * 100), round(hi * 100)), (79, 99))

    def test_large_n_does_not_underflow(self):
        lo, hi = payloads.clopper_pearson(500, 1000)
        self.assertTrue(0.46 < lo < 0.5 < hi < 0.54)


class Steps(unittest.TestCase):
    def setUp(self):
        self.recs = ([past(i, "Yaogan", ring=AREA) for i in range(6)] + [past(10 + i, "Shiyan", inc=50.0) for i in range(4)]
                     + [past(20, "Yaogan", pad=OTHER_PAD, site="Jiuquan")]
                     + [past(30, None, mtype=payloads.UNKNOWN)])

    def test_narrowing(self):
        res = payloads.build(self.recs + [upcoming()], snap_for(), {})
        self.assertEqual(len(res), 1)
        steps = {s["step"]: s for s in res[0]["steps"]}
        self.assertEqual(steps["vehicle and site"]["n"], 10)            # Jiuquan and the unknown are left out
        self.assertEqual(steps["vehicle and site"]["unknown"], 1)
        self.assertEqual(steps["vehicle and site"]["series"][0], {"class": "Yaogan", "k": 6, "rate": 0.6,
                                                                  "lo": 0.262, "hi": 0.878})
        self.assertEqual(steps["inclination"]["n"], 6)
        self.assertEqual(steps["closure signature"]["n"], 6)
        self.assertEqual(res[0]["forecast_step"], "closure signature")
        self.assertNotIn("vehicle, any site", steps)
        self.assertLessEqual(len(steps["vehicle and site"]["last"]), payloads.LAST_N)

    def test_signature_reads_charted_areas_and_far_areas_do_not_match(self):
        recs = [past(i, "Yaogan") for i in range(3)] + [past(5 + i, "Shiyan", chart=[f"hist:c{i}"]) for i in range(3)]
        charted = {f"hist:c{i}": {"areas": [{"centroid": [107.75, 26.75]}]} for i in range(3)}
        res = payloads.build(recs + [upcoming()], snap_for(), charted)[0]
        sig = next(s for s in res["steps"] if s["step"] == "closure signature")
        self.assertEqual((sig["n"], sig["series"][0]["class"]), (3, "Shiyan"))
        res = payloads.build(recs + [upcoming()], snap_for(ring=FAR), charted)[0]
        sig = next(s for s in res["steps"] if s["step"] == "closure signature")
        self.assertEqual(sig["n"], 0)
        self.assertFalse(sig["used"])
        self.assertEqual(res["forecast_step"], "inclination")

    def test_pad_area_gives_no_signature_and_time_only_gives_no_inclination(self):
        res = payloads.build(self.recs + [upcoming()], snap_for(nm=10), {})[0]
        self.assertIsNone(res["implied_inclination"])
        self.assertEqual([s["step"] for s in res["steps"]], ["vehicle and site"])

    def test_wider_class_when_site_has_too_few(self):
        res = payloads.build(self.recs + [upcoming(pad=[111.8, 21.6], site="Yangjiang (sea launch)")], {}, {})[0]
        steps = {s["step"]: s for s in res["steps"]}
        self.assertEqual(steps["vehicle and site"]["n"], 0)
        self.assertEqual(steps["vehicle, any site"]["n"], 11)
        self.assertEqual(res["forecast_step"], "vehicle, any site")

    def test_only_unknown_payloads_and_only_earlier_launches(self):
        named = dict(upcoming("u2"), mtype="Earth observation")
        later = past(40, "Gaofen", time="2027-01-01T00:00:00Z")
        res = payloads.build(self.recs + [upcoming(), named, later], snap_for(), {})
        self.assertEqual([r["ll2"] for r in res], ["u1"])
        self.assertNotIn("Gaofen", [x["class"] for x in res[0]["steps"][0]["series"]])


class Scoring(unittest.TestCase):
    def test_brier(self):
        self.assertEqual(payloads.brier({"A": 1.0}, "A"), 0.0)
        self.assertEqual(payloads.brier({"A": 0.6, "B": 0.4}, "A"), 0.32)
        self.assertEqual(payloads.brier({"A": 0.6, "B": 0.4}, "C"), 1.52)

    def test_forecast_once_per_change_then_one_outcome(self):
        recs = [past(i, "Yaogan") for i in range(4)] + [past(10, "Shiyan")]
        up = upcoming()
        res = payloads.build(recs + [up], {}, {})
        led = payloads.score([], res, recs + [up], "2026-11-30T00:00:00Z")
        self.assertEqual([e["kind"] for e in led], ["forecast"])
        self.assertEqual((led[0]["top"], led[0]["probs"]), ("Yaogan", {"Yaogan": 0.8, "Shiyan": 0.2}))
        self.assertEqual(payloads.score(led, res, recs + [up], "2026-11-30T06:00:00Z"), [])     # unchanged
        flown = dict(up, status="launched", mtype="Military / intelligence", programmes=["Yaogan"], payload="Yaogan 50")
        new = payloads.score(led, [], recs + [flown], "2026-12-02T00:00:00Z")
        self.assertEqual(len(new), 1)
        o = new[0]
        self.assertEqual((o["kind"], o["actual"], o["top_right"], o["p_actual"], o["brier"]),
                         ("outcome", "Yaogan", True, 0.8, 0.08))
        self.assertEqual(payloads.score(led + new, [], recs + [flown], "2026-12-03T00:00:00Z"), [])  # scored once
        self.assertEqual(payloads.summary(led + new), {"scored": 1, "top_right": 1, "mean_brier": 0.08})

    def test_forecast_after_launch_is_not_scored(self):
        recs = [past(i, "Yaogan") for i in range(4)]
        up = upcoming(time="2026-11-29T00:00:00Z")
        led = payloads.score([], payloads.build(recs + [up], {}, {}), recs + [up], "2026-11-30T00:00:00Z")
        flown = dict(up, status="launched", mtype="Military / intelligence", programmes=["Yaogan"])
        self.assertEqual(payloads.score(led, [], recs + [flown], "2026-12-01T00:00:00Z"), [])

    def test_gcat_record_scores_by_its_ll2_id(self):
        recs = [past(i, "Yaogan") for i in range(4)]
        up = upcoming()
        led = payloads.score([], payloads.build(recs + [up], {}, {}), recs + [up], "2026-11-30T00:00:00Z")
        g = past(50, "Shiyan", time="2026-12-01T09:05:00Z", ll2="u1", id="gcat:2026-300")
        new = payloads.score(led, [], recs + [g], "2026-12-02T00:00:00Z")
        self.assertEqual((new[0]["launch"], new[0]["top_right"]), ("gcat:2026-300", False))


class Command(unittest.TestCase):
    def test_writes_rates_and_appends_ledger(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("launch_tool", ROOT / "tools" / "launch.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        recs = [past(i, "Yaogan") for i in range(4)] + [upcoming()]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "launches.json").write_text(json.dumps({"records": recs}), encoding="utf-8")
            (d / "snapshot.json").write_text(json.dumps({"generated_at": "x", "matches": [], "areas": []}), encoding="utf-8")
            out = d / "out"
            led = out / "ledger.jsonl"
            out.mkdir()
            led.write_text('{"kind":"note","keep":true}\n', encoding="utf-8")
            r = tool.run_payloads(d, out, now=datetime(2026, 11, 30, tzinfo=timezone.utc))
            self.assertEqual((r["launches"], r["new_ledger_lines"]), (1, 1))
            lines = led.read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(lines[0]), {"kind": "note", "keep": True})     # earlier lines kept
            self.assertEqual(json.loads(lines[1])["kind"], "forecast")
            doc = json.loads((out / "rates.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["launches"][0]["forecast_step"], "vehicle and site")
            tool.run_payloads(d, out, now=datetime(2026, 11, 30, 6, tzinfo=timezone.utc))
            self.assertEqual(len(led.read_text(encoding="utf-8").splitlines()), 2)

    def test_output_folder_is_ignored(self):
        self.assertIn("history/payloads_source/", (ROOT / ".gitignore").read_text(encoding="utf-8").split())


if __name__ == "__main__":
    unittest.main()
