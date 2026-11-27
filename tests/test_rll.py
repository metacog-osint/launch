"""Offline tests for RocketLaunch.Live as a second schedule source (launch/rll.py): parsing the free tier's reply,
the join to Launch Library 2 records, coordinates from LL2 at the same place, the wiring in tools/launch.py and the
feed items. Replies are built here in the API's shape (fields as read on 26 Nov 2026), not copied from it."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from launch import feed, rll, schedule  # noqa: E402

_spec = importlib.util.spec_from_file_location("launch_cli_rll", ROOT / "tools" / "launch.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

NOW = datetime(2026, 11, 26, 21, 0, tzinfo=timezone.utc)
READ = "2026-11-26T21:00:00Z"


def launch(i, t0, vehicle="Falcon 9", location="Vandenberg SFB", pad="SLC-4E", name=None, **kw):
    return {"id": i, "sort_date": str(int(datetime.fromisoformat(t0.replace("Z", "+00:00")).timestamp())),
            "name": name if name is not None else f"Mission {i}",
            "provider": {"id": 1, "name": "SpaceX", "slug": "spacex"},
            "vehicle": {"id": 1, "name": vehicle, "slug": "v"},
            "pad": {"id": 1, "name": pad, "location": {"id": 1, "name": location, "country": "United States"}},
            "missions": [{"id": 1, "name": f"Payload {i}", "description": "x"}],
            "win_open": kw.get("win_open"), "t0": kw.get("t0_override", t0), "win_close": kw.get("win_close"),
            "est_date": kw.get("est", {"month": None, "day": None, "year": None, "quarter": None}),
            "slug": f"m-{i}", "modified": "2026-11-25T12:00:00+00:00", "suborbital": False, "result": -1}


def reply(*launches):
    return json.dumps({"valid_auth": False, "count": len(launches), "limit": 5, "total": len(launches),
                       "last_page": 1, "result": list(launches)}).encode()


def ll2(i, net, vehicle="Falcon 9 Block 5", location="Vandenberg SFB, CA, USA", pad="Space Launch Complex 4E",
        lat=34.632, lon=-120.611, precision="Minute"):
    return {"id": f"ll2-{i}", "name": f"{vehicle} | Mission {i}", "net": net, "net_precision": precision,
            "window_start": net, "window_end": net, "status": "Go", "status_name": "Go for Launch",
            "provider": "SpaceX", "vehicle": vehicle, "mission": f"Mission {i}", "pad": pad, "location": location,
            "pad_country": "US", "lat": lat, "lon": lon, "ll2_url": f"https://ll.example/{i}/"}


def no_release(url, timeout=120):
    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


class Parse(unittest.TestCase):
    def test_rows(self):
        rows = rll.parse(reply(launch(5079, "2026-11-27T00:05Z", "Electron", "Rocket Lab Launch Complex, Mahia Peninsula",
                                      "LC-1B", name='"Night Owls Never Sleep"', win_open="2026-11-27T00:00Z"),
                               launch(6328, "2026-11-27T13:00Z", "Unconfirmed Vehicle", "Taiyuan Satellite Launch Center",
                                      "", name="Yaogan 50 Group TBD")))
        a, b = rows
        self.assertEqual((a["id"], a["name"], a["net"], a["net_precision"]),
                         ("5079", "Night Owls Never Sleep", "2026-11-27T00:05:00Z", "Minute"))
        self.assertEqual(a["window_start"], "2026-11-27T00:00:00Z")
        self.assertEqual(a["rll_url"], "https://www.rocketlaunch.live/launch/m-5079")
        self.assertEqual((a["status"], a["lat"]), ("", None))
        self.assertEqual(b["vehicle"], "")           # "Unconfirmed Vehicle" is no vehicle
        self.assertEqual(set(schedule.FIELDS) - set(a), set())

    def test_dated_by_sort_date_when_no_time(self):
        x = launch(1, "2026-12-15T00:00Z", t0_override=None, est={"month": 12, "day": None, "year": 2026, "quarter": None})
        (r,) = rll.parse(reply(x))
        self.assertEqual((r["net"], r["net_precision"]), ("2026-12-15T00:00:00Z", "Month"))

    def test_bad_reply(self):
        with self.assertRaises(ValueError):
            rll.parse(b'{"error": "x"}')


class Join(unittest.TestCase):
    def test_words_and_vehicles(self):
        self.assertEqual(rll.place_words("Rocket Lab Launch Complex, Mahia Peninsula"), {"mahia"})
        self.assertEqual(rll.place_words("Taiyuan Satellite Launch Center, People's Republic of China"), {"taiyuan"})
        self.assertTrue(rll.same_vehicle("Falcon 9", "Falcon 9 Block 5"))
        self.assertTrue(rll.same_vehicle("", "Long March 6A"))
        self.assertFalse(rll.same_vehicle("Long March 6A", "Long March 6C"))

    def store(self, *rll_rows):
        store = schedule.empty()
        schedule.ingest(store, "ll2", [ll2(1, "2026-11-29T04:39:00Z"),
                                       ll2(2, "2026-11-29T15:47:00Z", location="Cape Canaveral SFS, FL, USA",
                                           pad="Space Launch Complex 40", lat=28.56, lon=-80.58)],
                        "2026-11-26T20:00:00Z", link_key="ll2_url")
        rows = rll.parse(reply(*rll_rows))
        rll.place(rows, store)
        schedule.ingest(store, "rll", rows, READ, link_key="rll_url")
        return store

    def test_same_launch_joins_and_ll2_id_kept(self):
        store = self.store(launch(6329, "2026-11-29T04:39Z", name="USSF-380"),
                           launch(6226, "2026-11-29T17:00Z", location="Cape Canaveral SFS", pad="SLC-40"))
        pairs = rll.pairs(store)
        self.assertEqual(sorted(pairs), [("upcoming:rll:6226", "upcoming:ll2:ll2-2"),
                                         ("upcoming:rll:6329", "upcoming:ll2:ll2-1")])
        for a, b in pairs:
            schedule.join(store, b, a, READ, "test")
        self.assertEqual(len(store["records"]), 2)
        r = schedule.resolve(store, "upcoming:rll:6329")
        self.assertEqual(r["id"], "upcoming:ll2:ll2-1")
        self.assertEqual(r["sources"], ["ll2", "rll"])
        self.assertEqual(r["vehicle"], "Falcon 9 Block 5")   # LL2's fields come first

    def test_other_place_time_or_vehicle_does_not_join(self):
        store = self.store(launch(1, "2026-11-29T04:39Z", location="Kennedy Space Center"),
                           launch(2, "2026-11-29T09:00Z"),
                           launch(3, "2026-11-29T04:40Z", vehicle="Minotaur IV"))
        self.assertEqual(rll.pairs(store), [])

    def test_a_record_ll2_stopped_listing_is_no_candidate(self):
        store = schedule.empty()
        schedule.ingest(store, "ll2", [ll2(1, "2026-11-25T04:39:00Z"), ll2(2, "2026-11-29T15:47:00Z")],
                        "2026-11-24T20:00:00Z")
        schedule.ingest(store, "ll2", [ll2(2, "2026-11-29T15:47:00Z")], "2026-11-26T20:00:00Z")  # ll2-1 flew
        schedule.ingest(store, "rll", rll.parse(reply(launch(9, "2026-11-25T05:30Z"))), READ)
        self.assertEqual(rll.pairs(store), [])

    def test_two_equal_candidates_join_neither(self):
        store = schedule.empty()
        schedule.ingest(store, "ll2", [ll2(1, "2026-11-29T04:00:00Z"), ll2(2, "2026-11-29T05:00:00Z")],
                        "2026-11-26T20:00:00Z")
        schedule.ingest(store, "rll", rll.parse(reply(launch(9, "2026-11-29T04:30Z"))), READ)
        self.assertEqual(rll.pairs(store), [])

    def test_coordinates_from_ll2_at_the_same_place(self):
        store = self.store(launch(7, "2026-12-03T10:00Z", vehicle="Minotaur IV"))
        r = schedule.resolve(store, "upcoming:rll:7")
        self.assertEqual((r["lat"], r["lon"]), (34.632, -120.611))
        store = self.store(launch(8, "2026-12-03T10:00Z", location="Plesetsk Cosmodrome"))
        self.assertIsNone(schedule.resolve(store, "upcoming:rll:8")["lat"])


class Wiring(unittest.TestCase):
    def test_update_schedule_reads_both_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            rows = rll.parse(reply(launch(6329, "2026-11-29T04:39Z"), launch(77, "2026-11-30T02:00Z",
                                                                             location="Wenchang Space Launch Site",
                                                                             vehicle="Long March 7")))
            snap = {"generated_at": READ, "lanes": {"schedule": {"status": "ok"}, "rll": {"status": "ok"}},
                    "schedule": {"read_at": "2026-11-26T20:00:00Z", "rows": [ll2(1, "2026-11-29T04:39:00Z")]},
                    "rll": {"read_at": READ, "credit": rll.CREDIT, "rows": rows}, "news": {}}
            store = cli.update_schedule(snap, d, NOW, no_release)
            self.assertEqual(snap["lanes"]["rll"]["ingest"]["joined"], 1)
            self.assertEqual(len(store["records"]), 2)
            ids = sorted(r["id"] for r in snap["schedule"]["records"])
            self.assertEqual(ids, ["upcoming:ll2:ll2-1", "upcoming:rll:77"])
            self.assertEqual(snap["schedule"]["credits"]["rll"], "Data by RocketLaunch.Live")
            # Only LL2-listed records go to matching; the RocketLaunch.Live-only one does not.
            self.assertEqual([x["id"] for x in cli.ll2_upcoming(snap)], ["ll2-1"])
            # A failed rll lane leaves the store as it was.
            snap2 = {"generated_at": READ, "lanes": {"schedule": {"status": "failed"}, "rll": {"status": "failed"}},
                     "schedule": snap["schedule"], "rll": snap["rll"]}
            self.assertEqual(len(cli.update_schedule(snap2, d, NOW, no_release)["records"]), 2)

    def test_lane_is_one_request(self):
        seen = []

        def get(url, timeout=120):
            seen.append(url)
            return reply(launch(1, "2026-11-28T00:00Z"))
        with tempfile.TemporaryDirectory() as tmp:
            out, recs = cli._lane_rll(Path(tmp), {}, get)
        self.assertEqual(seen, [rll.API])
        self.assertEqual(out["rll"]["credit"], "Data by RocketLaunch.Live")
        self.assertEqual(len(out["rll"]["rows"]), 1)


class Feed(unittest.TestCase):
    def test_items_cite_their_listing_sources(self):
        from tic_doctrine import contract, registers
        store = schedule.empty()
        schedule.ingest(store, "ll2", [ll2(1, "2026-11-29T04:39:00Z")], "2026-11-26T20:00:00Z", link_key="ll2_url")
        rows = rll.parse(reply(launch(6329, "2026-11-29T04:39Z"),
                               launch(77, "2026-11-30T02:00Z", location="Wenchang Space Launch Site",
                                      vehicle="Long March 7", name="TBD")))
        schedule.ingest(store, "rll", rows, READ, link_key="rll_url")
        for a, b in rll.pairs(store):
            schedule.join(store, b, a, READ, "test")
        snap = {"generated_at": READ, "lanes": {},
                "schedule": {"read_at": "2026-11-26T20:00:00Z", "reads": dict(store["reads"]),
                             "records": schedule.active(store, NOW)}}
        feats = {f["properties"]["id"]: f for f in feed.build_feed(snap)["features"]}
        items = {k: f["properties"] for k, f in feats.items()}
        self.assertEqual(sorted(items), ["launch:upcoming:ll2:ll2-1", "launch:upcoming:rll:77"])
        both, own = items["launch:upcoming:ll2:ll2-1"], items["launch:upcoming:rll:77"]
        self.assertEqual([s["id"] for s in both["sources"]], ["ll2-thespacedevs", "rocketlaunch-live"])
        self.assertIn("Launch Library 2 and RocketLaunch.Live list", both["summary"])
        self.assertIn("(status Go for Launch; NET precision Minute)", both["summary"])
        self.assertEqual([s["id"] for s in own["sources"]], ["rocketlaunch-live"])
        self.assertEqual(own["sources"][0]["url"], "https://www.rocketlaunch.live/launch/m-77")
        self.assertEqual(own["sources"][0]["accessed_at"], READ)
        self.assertIn("Data by RocketLaunch.Live", own["summary"])
        self.assertNotIn("()", own["title"])
        regs = registers.ids(ROOT / "doctrine")
        for k, f in feats.items():
            errs = [m for _, sev, m in contract.check(f, regs) if sev == "error"]
            self.assertEqual(errs, [], k)


if __name__ == "__main__":
    unittest.main()
