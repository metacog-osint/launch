"""A source that stops listing a launch no longer supplies its fields or counts as listing it (launch/schedule.py
`listed_by`, launch/unlisted.py `_listing`, launch/feed.py `_upcoming_item`, tools/launch.py `ll2_upcoming`)."""
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from launch import feed, rll, schedule, unlisted  # noqa: E402
import test_unlisted as T  # noqa: E402

_spec = importlib.util.spec_from_file_location("launch_cli_listed_by", ROOT / "tools" / "launch.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

NOW = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)


def ll2_row(net):
    return {"id": "u1", "name": "Falcon 9 Block 5 | Starlink Group X", "net": net, "net_precision": "Minute",
            "lat": 28.56, "lon": -80.58, "status": "Go", "status_name": "Go for Launch", "vehicle": "Falcon 9 Block 5",
            "pad": "Space Launch Complex 40", "location": "Cape Canaveral SFS, FL, USA", "provider": "SpaceX",
            "ll2_url": "https://ll.thespacedevs.com/2.3.0/launches/u1/"}


def rll_row(net):
    return {"id": "9001", "name": "Starlink X", "net": net, "net_precision": "Minute", "lat": None, "lon": None,
            "status": "", "vehicle": "Falcon 9", "pad": "SLC-40", "location": "Cape Canaveral SFS",
            "provider": "SpaceX", "rll_url": "https://www.rocketlaunch.live/launch/x"}


class TwoSourcesFirstDrops(unittest.TestCase):
    """LL2 and RocketLaunch.Live list one launch and are joined; LL2 then stops listing it while RocketLaunch.Live
    moves it two days later."""

    def run_once(self, store, a, b, at):
        schedule.ingest(store, "ll2", a, at, link_key="ll2_url")
        rows = [dict(x) for x in b]
        rll.place(rows, store)
        schedule.ingest(store, "rll", rows, at, link_key="rll_url")
        for x, y in rll.pairs(store):
            schedule.join(store, y, x, at, "same launch")
        return schedule.active(store, NOW)

    def test_fields_and_listing_follow_the_source_still_listing(self):
        store = schedule.empty()
        view = self.run_once(store, [ll2_row("2026-11-28T10:00:00Z")], [rll_row("2026-11-28T10:00:00Z")],
                             "2026-11-26T00:00:00Z")
        self.assertEqual(len(view), 1)
        self.assertEqual(view[0]["listed_by"], ["ll2", "rll"])
        view = self.run_once(store, [], [rll_row("2026-11-30T12:00:00Z")], "2026-11-26T06:00:00Z")
        self.assertEqual(len(view), 1)
        v = view[0]
        self.assertEqual(v["net"], "2026-11-30T12:00:00Z")
        self.assertEqual(v["name"], "Starlink X")
        self.assertEqual(v["listed_by"], ["rll"])
        self.assertIn("ll2", v["refs"])  # the record keeps every source it ever had
        summary = feed._upcoming_item(v, "2026-11-26T06:00:00Z", "2026-11-26T06:00:00Z", {},
                                      store["reads"])["properties"]["summary"]
        self.assertTrue(summary.startswith("RocketLaunch.Live lists Starlink X for 2026-11-30 12:00 UTC"), summary)
        self.assertNotIn("Launch Library 2", summary)

    def test_ll2_upcoming_leaves_out_a_record_ll2_stopped_listing(self):
        store = schedule.empty()
        self.run_once(store, [ll2_row("2026-11-28T10:00:00Z")], [rll_row("2026-11-28T10:00:00Z")],
                      "2026-11-26T00:00:00Z")
        snap = {"schedule": {"records": schedule.active(store, NOW)}}
        self.assertEqual([r["id"] for r in cli.ll2_upcoming(snap)], ["u1"])
        self.run_once(store, [], [rll_row("2026-11-30T12:00:00Z")], "2026-11-26T06:00:00Z")
        snap = {"schedule": {"records": schedule.active(store, NOW)}}
        self.assertEqual(cli.ll2_upcoming(snap), [])

    def test_a_record_no_source_lists_keeps_its_first_reading(self):
        store = schedule.empty()
        self.run_once(store, [ll2_row("2026-11-28T10:00:00Z")], [rll_row("2026-11-28T10:00:00Z")],
                      "2026-11-26T00:00:00Z")
        self.run_once(store, [], [], "2026-11-26T06:00:00Z")
        rec = store["records"][0]
        self.assertEqual(schedule.listed_by(rec), [])
        self.assertEqual(rec["name"], "Falcon 9 Block 5 | Starlink Group X")
        self.assertEqual(schedule.active(store, NOW), [])


class ClosureJoinedThenDropped(unittest.TestCase):
    """A closure record joined to an LL2 listing; LL2 then drops the launch while the notice stays in force. The
    record must read as a closure with no listing again and stay in the live view every run."""

    def run_once(self, store, ll2_rows, at):
        schedule.ingest(store, "ll2", ll2_rows, at)
        rows = unlisted.closures([T.area()], schedule.active(store, T.NOW), T.SITES, T.NOW)
        unlisted.apply(store, rows, T.SITES, at)
        return rows, schedule.active(store, T.NOW)

    def test_stable_across_runs(self):
        store = schedule.empty()
        row = {"id": "u1", "name": "LM-2D", "net": "2026-11-29T21:15:00Z", "net_precision": "Minute",
               "lat": 41.0, "lon": 100.3}
        self.run_once(store, [], "2026-11-21T20:00:00Z")
        rows, view = self.run_once(store, [row], "2026-11-22T02:00:00Z")
        self.assertEqual(rows, [])
        self.assertEqual([(v["name"], v["listed_by"]) for v in view], [("LM-2D", ["ll2"])])
        for at in ("2026-11-22T14:00:00Z", "2026-11-22T20:00:00Z", "2026-11-23T02:00:00Z", "2026-11-23T08:00:00Z"):
            rows, view = self.run_once(store, [], at)
            self.assertEqual(len(rows), 1, at)
            self.assertEqual(len(view), 1, at)
            v = view[0]
            self.assertEqual(v["id"], "upcoming:closure:A1/26")
            self.assertEqual(v["listed_by"], ["closure"])
            self.assertEqual(v["net"], "2026-11-29T21:06:00Z")
            self.assertTrue(v["name"].startswith("Closure with no listed launch"), v["name"])
            item = feed._upcoming_item(v, at, at, {}, store["reads"])["properties"]
            self.assertTrue(item["title"].startswith("Closure with no listed launch"), item["title"])

    def test_listing_reads_listed_by_and_store_records(self):
        self.assertFalse(unlisted._listing({"listed_by": ["closure"], "evidence": ["listed"]}))
        self.assertTrue(unlisted._listing({"listed_by": ["closure", "rll"]}))
        rec = {"sources": ["closure", "ll2"], "evidence": ["closure with no listing", "listed"],
               "by_source": {"closure": {"listed": True}, "ll2": {"listed": False}}}
        self.assertFalse(unlisted._listing(rec))
        self.assertTrue(unlisted._listing(T.listed()))  # a bare row still counts as listed


if __name__ == "__main__":
    unittest.main()
