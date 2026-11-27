"""Offline tests for the Ascent move's lanes (19 Nov 2026): the multi-source schedule (launch/schedule.py), the
headlines (launch/news.py), the LL2 ledger (launch/ll2ledger.py), the side-by-side check with Orbit
(launch/compare.py) and their wiring in tools/launch.py. Fixtures ll2_upcoming.json and snapi_articles.json are
Orbit's (real replies of 13-15 Nov 2026); ledger pages are built here in LL2's detailed shape."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from launch import compare, ll2ledger, news, schedule  # noqa: E402

_spec = importlib.util.spec_from_file_location("launch_cli_ascent", ROOT / "tools" / "launch.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

FIX = ROOT / "tests" / "fixtures"
NOW = datetime(2026, 11, 13, 23, 0, tzinfo=timezone.utc)


def rec(i: int, net: str, status: str = "Success", updated: str | None = None) -> dict:
    return {"id": f"id-{i:03d}", "name": f"Rocket | Mission {i}", "net": net, "net_precision": {"name": "Second"},
            "window_start": net, "window_end": net, "status": {"abbrev": status, "name": status},
            "last_updated": updated or net,
            "launch_service_provider": {"name": "Provider", "type": {"name": "Commercial"},
                                        "country": [{"alpha_2_code": "US"}]},
            "rocket": {"configuration": {"full_name": "Rocket"}},
            "mission": {"name": f"Mission {i}", "type": "Communications", "description": "x" * 900,
                        "orbit": {"abbrev": "LEO", "name": "Low Earth Orbit"}},
            "pad": {"name": "Pad 1", "latitude": "28.5", "longitude": "-80.6",
                    "location": {"name": "Cape", "country": {"alpha_2_code": "US"}}},
            "url": f"https://ll.thespacedevs.com/2.3.0/launches/id-{i:03d}/", "image": {"image_url": "x.jpg"}}


def page(*rows) -> bytes:
    return json.dumps({"count": len(rows), "results": list(rows)}).encode()


def day(n: int, h: int = 0) -> str:
    return f"2024-01-{n:02d}T{h:02d}:00:00Z"


def rows_of(*recs) -> list[dict]:
    return [schedule.ll2_row(r) for r in recs]


class Schedule(unittest.TestCase):
    def setUp(self):
        self.rows = schedule.ll2_parse((FIX / "ll2_upcoming.json").read_bytes())

    def test_parse_fixture(self):
        self.assertEqual(len(self.rows), 4)
        r = self.rows[0]
        self.assertEqual(r["id"], "0f867f0c-5422-4d44-93b8-d7faaae7019b")
        for k in ("net", "status", "vehicle", "provider_countries", "lat", "lon", "ll2_url", "last_updated"):
            self.assertIn(k, r)
        self.assertNotIn("image", r)
        self.assertLessEqual(len(r["mission_description"]), 600)
        with self.assertRaises(ValueError):
            schedule.ll2_parse(b'{"detail": "Request was throttled."}')

    def test_url_is_one_request_with_horizon(self):
        q = parse_qs(urlparse(schedule.ll2_url(NOW)).query)
        self.assertEqual(q["mode"], ["detailed"])
        self.assertEqual(q["net__lte"], ["2026-11-27T23:00:00Z"])

    def test_ids_are_launchs_own_and_never_change(self):
        st = schedule.empty()
        rep = schedule.ingest(st, "ll2", self.rows, "2026-11-13T22:00:00Z", link_key="ll2_url")
        self.assertEqual(len(rep["new"]), 4)
        r = st["records"][0]
        self.assertEqual(r["id"], "upcoming:ll2:" + self.rows[0]["id"])
        self.assertEqual(r["sources"], ["ll2"])
        self.assertEqual(r["evidence"], ["listed"])
        self.assertEqual(r["by_source"]["ll2"]["link"], self.rows[0]["ll2_url"])
        # A NET slip is logged; the id stays.
        moved = [dict(self.rows[0], net="2026-11-14T03:00:00Z")] + self.rows[1:]
        rep = schedule.ingest(st, "ll2", moved, "2026-11-14T00:00:00Z")
        self.assertEqual(rep["new"], [])
        self.assertEqual(rep["changed"][r["id"]], {"net": [self.rows[0]["net"], "2026-11-14T03:00:00Z"]})
        self.assertEqual(st["records"][0]["id"], r["id"])
        self.assertEqual(st["records"][0]["net"], "2026-11-14T03:00:00Z")
        self.assertEqual(len(st["records"][0]["changes"]), 1)

    def test_unlisted_is_kept_and_marked_then_relisted(self):
        st = schedule.empty()
        schedule.ingest(st, "ll2", self.rows, "t1")
        rep = schedule.ingest(st, "ll2", self.rows[1:], "t2")
        gone = "upcoming:ll2:" + self.rows[0]["id"]
        self.assertEqual(rep["unlisted"], [gone])
        r = schedule.resolve(st, gone)
        self.assertEqual(len(st["records"]), 4)                     # never dropped
        self.assertEqual((r["by_source"]["ll2"]["listed"], r["by_source"]["ll2"]["unlisted_at"]), (False, "t2"))
        self.assertNotIn(gone, [x["id"] for x in schedule.active(st, NOW)])
        rep = schedule.ingest(st, "ll2", self.rows, "t3")
        self.assertEqual(rep["relisted"], [gone])
        self.assertTrue(r["by_source"]["ll2"]["listed"])

    def test_join_keeps_the_first_id(self):
        # A launch first seen from another source (a closure, say) keeps its id when LL2 lists it.
        st = schedule.empty()
        schedule.ingest(st, "notice", [{"id": "n1", "name": "Launch from a notice", "net": "2026-11-20T00:00:00Z"}],
                        "2026-11-10T00:00:00Z", evidence="notice")
        schedule.ingest(st, "ll2", [self.rows[3]], "2026-11-12T00:00:00Z")
        kept = schedule.join(st, "upcoming:ll2:" + self.rows[3]["id"], "upcoming:notice:n1", "2026-11-12T01:00:00Z",
                             "same pad and window")
        self.assertEqual(kept["id"], "upcoming:notice:n1")
        self.assertEqual(kept["sources"], ["notice", "ll2"])
        self.assertEqual(kept["refs"], {"notice": "n1", "ll2": self.rows[3]["id"]})
        self.assertEqual(kept["name"], self.rows[3]["name"])          # LL2's fields come first (PRECEDENCE)
        self.assertEqual(len(st["records"]), 1)
        self.assertIs(schedule.resolve(st, "upcoming:ll2:" + self.rows[3]["id"]), kept)
        # The next LL2 read lands on the kept record, not a new one.
        rep = schedule.ingest(st, "ll2", [self.rows[3]], "2026-11-13T00:00:00Z")
        self.assertEqual(rep["new"], [])

    def test_union_newer_wins_changes_kept_duplicate_refs_joined(self):
        a, b = schedule.empty(), schedule.empty()
        schedule.ingest(a, "ll2", self.rows[:2], "t1")
        b = json.loads(json.dumps(a))
        schedule.ingest(b, "ll2", [dict(self.rows[0], status="Go")] + self.rows[1:2], "t2")
        u = schedule.union(a, b)
        self.assertEqual(len(u["records"]), 2)
        r = schedule.resolve(u, "upcoming:ll2:" + self.rows[0]["id"])
        self.assertEqual(r["status"], "Go")
        self.assertEqual(len(r["changes"]), 1)
        self.assertEqual(u["reads"]["ll2"], "t2")
        # Two copies of one LL2 id under different record ids (a lost alias) become one, the first seen keeping its id.
        c = schedule.empty()
        schedule.ingest(c, "x", [{"id": "x1", "net": self.rows[0]["net"]}], "t0", evidence="notice")
        c["records"][0]["refs"]["ll2"] = self.rows[0]["id"]
        u = schedule.union(a, c)
        ids = [r["id"] for r in u["records"]]
        self.assertIn("upcoming:x:x1", ids)
        self.assertNotIn("upcoming:ll2:" + self.rows[0]["id"], ids)
        self.assertEqual(u["aliases"]["upcoming:ll2:" + self.rows[0]["id"]], "upcoming:x:x1")

    def test_active_is_the_live_view(self):
        st = schedule.empty()
        schedule.ingest(st, "ll2", self.rows, "t1", link_key="ll2_url")
        act = schedule.active(st, NOW)
        self.assertTrue(act)
        self.assertTrue(all(x["id"].startswith("upcoming:ll2:") for x in act))
        self.assertIn("ll2", act[0]["links"])
        self.assertNotIn("by_source", act[0])

    def test_public_record_keeps_the_latest_net_moves(self):
        """25 Nov 2026: the Live tab's board says how often a NET moved and the latest move."""
        moves = [{"at": f"2026-11-1{i}T00:00:00Z", "source": "ll2",
                  "fields": {"net": [f"2026-11-2{i}T00:00:00Z", f"2026-11-2{i + 1}T00:00:00Z"]}} for i in range(5)]
        other = {"at": "2026-11-19T00:00:00Z", "source": "ll2", "fields": {"status": ["TBD", "Go"]}}
        out = schedule._public({"id": "x", "changes": [moves[4], other, *moves[:4]]})
        self.assertEqual(out["net_changes"], 5)
        self.assertEqual([m["at"] for m in out["net_moves"]], [m["at"] for m in moves[2:]])   # oldest first, last 3
        self.assertEqual(out["net_moves"][-1], {"at": "2026-11-14T00:00:00Z", "from": "2026-11-24T00:00:00Z",
                                                "to": "2026-11-25T00:00:00Z"})
        self.assertEqual(schedule._public({"id": "y"})["net_moves"], [])


class News(unittest.TestCase):
    def test_links_only_and_by_record(self):
        body = (FIX / "snapi_articles.json").read_bytes()
        ids = ["7bdc412b-c965-4517-a131-f57a01189803", "0f867f0c-5422-4d44-93b8-d7faaae7019b"]
        doc = news.parse(body, ids)
        self.assertTrue(doc["articles"])
        for a in doc["articles"]:
            self.assertEqual(set(a), {"title", "site", "url", "published_at", "launches"})
            self.assertTrue(a["url"].startswith("http"))
        self.assertLessEqual(len(doc["by_launch"][ids[0]]), news.PER_LAUNCH)
        recs = [{"id": "upcoming:ll2:" + ids[0], "refs": {"ll2": ids[0]}}, {"id": "upcoming:x:1", "refs": {"x": "1"}}]
        heads = news.for_records(doc, recs)
        self.assertEqual(list(heads), ["upcoming:ll2:" + ids[0]])
        self.assertNotIn("launches", heads["upcoming:ll2:" + ids[0]][0])
        self.assertIn("launch=" + ids[0], news.url(ids))


class Ledger(unittest.TestCase):
    def test_step_verifies_and_extends(self):
        doc = ll2ledger.empty()
        rep = ll2ledger.step(doc, page(rec(1, day(1)), rec(2, day(3))), "t0")
        self.assertEqual((rep["added"], rep["verified"]), (2, None))
        self.assertEqual(parse_qs(urlparse(ll2ledger.next_url(doc)).query)["net__gte"], [day(3)])
        rep = ll2ledger.step(doc, page(rec(2, day(3), "Failure"), rec(3, day(4))), "t1")
        self.assertEqual((rep["added"], rep["verified"]), (1, "ok"))
        self.assertEqual(rep["changed"]["id-002"]["status"], ["Success", "Failure"])
        self.assertEqual(doc["changes"][-1]["id"], "id-002")
        self.assertTrue(all(r["read_at"] for r in doc["launches"]))
        self.assertNotIn("mission_description", doc["launches"][0])
        with self.assertRaises(ValueError):
            ll2ledger.step(doc, b'{"detail": "throttled"}', "t2")
        self.assertEqual(len(doc["launches"]), 3)

    def test_open_launch_looked_up_once(self):
        doc = ll2ledger.empty()
        ll2ledger.step(doc, page(rec(1, day(1), "Go"), rec(2, day(2))), "t0")
        calls = []

        def lookup(i):
            calls.append(i)
            return json.dumps(rec(1, day(1), "Success")).encode()
        rep = ll2ledger.step(doc, page(rec(2, day(2))), "t1", lookup)
        self.assertEqual(calls, ["id-001"])
        self.assertEqual(rep["open_checked"], {"id": "id-001", "status": "Success"})
        self.assertEqual(rep["requests"], 2)

    def test_seed_from_orbit_and_union(self):
        orbit = {"schema": "orbit-ledger/1", "start": ll2ledger.START, "updated_at": "t0", "caught_up": True,
                 "launches": [dict(schedule.ll2_row(rec(1, day(1))), mission_description=None)],
                 "changes": [{"at": "t0", "id": "id-001", "fields": {"status": ["Go", "Success"]}}]}
        orbit["launches"][0].pop("mission_description")
        s = ll2ledger.seed(orbit, "abc", "t5")
        self.assertEqual(s["seeded_from"]["rows"], 1)
        self.assertEqual(s["changes"][0]["source"], "orbit")
        mine = json.loads(json.dumps(s))
        ll2ledger.step(mine, page(rec(1, day(1), "Failure"), rec(2, day(2))), "t6")
        u = ll2ledger.union(s, mine)                                   # Launch's own read wins over the seed
        self.assertEqual([r["status"] for r in u["launches"]], ["Failure", "Success"])
        self.assertEqual(len(u["changes"]), 2)
        self.assertEqual(u["seeded_from"]["sha256"], "abc")
        self.assertIsNone(ll2ledger.union(None, {}))
        self.assertEqual([r["id"] for r in ll2ledger.after(u, "2024-01-01")], ["id-002"])


class Compare(unittest.TestCase):
    def test_upcoming_same_and_explained(self):
        a = [{"id": "1", "net": "2026-11-15T00:00:00Z", "status": "Go", "last_updated": "u1"},
             {"id": "2", "net": "2026-11-16T00:00:00Z", "status": "Go", "last_updated": "u1"},
             {"id": "3", "net": "2026-11-16T00:00:00Z", "status": "TBD", "last_updated": "u1"}]
        b = [dict(a[0]), dict(a[1], net="2026-11-17T00:00:00Z", last_updated="u2"), dict(a[2], status="Go")]
        up = compare.upcoming(a, "2026-11-14T00:00:00Z", b, "2026-11-14T06:00:00Z")
        self.assertEqual((up["both"], up["n_differ"], up["unexplained"]), (3, 2, 1))
        self.assertEqual(compare.row("t", up, {"status": "compared"})["verdict"], "differs")
        same = compare.upcoming(a, "2026-11-14T00:00:00Z", [dict(x) for x in a], "2026-11-14T06:00:00Z")
        self.assertEqual(compare.row("t", same, {"status": "compared"})["verdict"], "same")
        late = compare.upcoming(a, "2026-11-14T00:00:00Z", a[:2], "2026-11-14T06:00:00Z")
        self.assertEqual(late["n_only_orbit"], 1)
        self.assertEqual(compare.row("t", late, {"status": "compared"})["verdict"], "listed by one only")

    def test_ledger_up_to_the_older_newest(self):
        o = {"launches": [{"id": "1", "net": "a"}, {"id": "2", "net": "b"}], "updated_at": "x"}
        l = {"launches": [{"id": "1", "net": "a", "read_at": "r"}, {"id": "2", "net": "b"}, {"id": "3", "net": "c"}]}
        led = compare.ledger(o, l)
        self.assertEqual((led["both"], led["n_only_launch"], led["launch_own"], led["n_differ"]), (2, 0, 1, 0))
        self.assertEqual(compare.ledger(None, l)["status"], "no ledger")

    def test_union_keeps_every_run(self):
        d = compare.union({"runs": [{"at": "t1"}]}, {"runs": [{"at": "t2"}, {"at": "t1"}]})
        self.assertEqual([r["at"] for r in d["runs"]], ["t1", "t2"])
        self.assertEqual(d["started_at"], "t1")


class Wiring(unittest.TestCase):
    """tools/launch.py: the stores read back from the release, the seed, a failed pull, the provisional rows."""

    def getter(self, routes):
        def get(url, timeout=120):
            for prefix, body in routes.items():
                if url.startswith(prefix):
                    if isinstance(body, Exception):
                        raise body
                    return body
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return get

    def test_load_store_stops_on_an_unreadable_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            err = urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)
            with self.assertRaises(RuntimeError):
                cli.load_store("ll2-ledger.json", d, self.getter({ll2ledger.RELEASE: err}))
            self.assertEqual(cli.load_store("ll2-ledger.json", d, self.getter({})), (None, None))  # 404: first run
            (d / "ll2-ledger.json").write_text('{"launches": []}', encoding="utf-8")
            local, rel = cli.load_store("ll2-ledger.json", d, self.getter({ll2ledger.RELEASE: err}))
            self.assertEqual((local, rel), ({"launches": []}, None))

    def test_seed_then_pull_then_failed_pull_changes_nothing(self):
        orbit = {"schema": "orbit-ledger/1", "start": ll2ledger.START, "updated_at": "t0", "caught_up": True,
                 "launches": [ll2ledger._clean(schedule.ll2_row(rec(1, day(1))))], "changes": []}
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            routes = {ll2ledger.ORBIT_LEDGER: json.dumps(orbit).encode(),
                      ll2ledger.PREVIOUS: page(rec(1, day(1)), rec(2, day(2)))}
            led, odoc, st = cli.update_ll2_ledger(d, self.getter(routes))
            self.assertEqual(st["status"], "ok")
            self.assertEqual(st["seeded"]["rows"], 1)
            self.assertEqual(len(led["launches"]), 2)
            self.assertTrue((d / "ll2-ledger.json").exists())
            routes[ll2ledger.PREVIOUS] = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
            led2, _, st2 = cli.update_ll2_ledger(d, self.getter(routes))
            self.assertEqual(st2["status"], "failed")
            self.assertEqual(led2["launches"], led["launches"])
            # No ledger anywhere and Orbit's unreadable: not started over from 1 Jan 2024.
            led3, _, st3 = cli.update_ll2_ledger(Path(tmp) / "empty", self.getter({}))
            self.assertIsNone(led3)
            self.assertEqual(st3["status"], "failed")

    def test_schedule_store_and_snapshot_view(self):
        rows = [{k: v for k, v in r.items() if k != "mission_description"}
                for r in schedule.ll2_parse((FIX / "ll2_upcoming.json").read_bytes())]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            snap = {"generated_at": "2026-11-13T22:00:00Z", "lanes": {"schedule": {"status": "ok"}},
                    "schedule": {"read_at": "2026-11-13T22:00:00Z", "rows": rows}, "news": {}}
            store = cli.update_schedule(snap, d, NOW, self.getter({}))
            self.assertEqual(len(store["records"]), 4)
            self.assertNotIn("rows", snap["schedule"])
            self.assertTrue(snap["schedule"]["records"])
            self.assertEqual(snap["lanes"]["schedule"]["ingest"]["new"], 4)
            # A failed lane's carried copy is not applied again.
            snap2 = {"generated_at": "t", "lanes": {"schedule": {"status": "failed"}}, "schedule": snap["schedule"]}
            store2 = cli.update_schedule(snap2, d, NOW, self.getter({}))
            self.assertEqual(store2["reads"]["ll2"], "2026-11-13T22:00:00Z")

    def test_match_reads_launchs_own_schedule(self):
        """Ascent step 4: live.match, the ledger and the site index read Launch's LL2-listed records, keyed by the LL2
        uuid as Orbit's copy was; a record held only by a closure notice is left out."""
        rows = [{k: v for k, v in r.items() if k != "mission_description"}
                for r in schedule.ll2_parse((FIX / "ll2_upcoming.json").read_bytes())]
        with tempfile.TemporaryDirectory() as tmp:
            snap = {"generated_at": "2026-11-13T22:00:00Z", "lanes": {"schedule": {"status": "ok"}},
                    "schedule": {"read_at": "2026-11-13T22:00:00Z", "rows": rows}, "news": {}}
            cli.update_schedule(snap, Path(tmp), NOW, self.getter({}))
        snap["schedule"]["records"].append({"id": "closure:x", "sources": ["closure"], "refs": {"closure": "x"},
                                            "net": "2026-11-14T00:00:00Z", "lat": 28.5, "lon": -80.6})
        up = cli.ll2_upcoming(snap)
        listed = {r["id"]: r for r in rows if schedule.within([r], NOW)}
        self.assertEqual({u["id"] for u in up}, set(listed))
        for u in up:
            for k in ("name", "net", "lat", "lon", "status", "vehicle", "mission", "pad"):
                self.assertEqual(u[k], listed[u["id"]][k], k)
            self.assertEqual(u["ll2_url"], listed[u["id"]]["ll2_url"])

    def test_compare_ends_when_orbit_has_no_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = cli.update_compare({"generated_at": "t", "orbit": {"launches": []}}, {"records": []}, None, None,
                                     Path(tmp), self.getter({}))
            self.assertEqual(out["status"], "ended")
            self.assertFalse(any(Path(tmp).iterdir()))

    def test_ledger_rows_since_gcat_become_provisional_records(self):
        led = {"launches": [dict(schedule.ll2_row(rec(1, "2026-11-01T00:00:00Z"))),
                            dict(schedule.ll2_row(rec(2, "2026-11-12T00:00:00Z"))),
                            dict(schedule.ll2_row(rec(3, "2026-11-12T05:00:00Z", "Go")))]}
        base = {"launches": [{"id": "gcat:2026-200", "source": "gcat", "date": "2026-11-05", "updated": "x"}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "history").mkdir()
            (root / "history" / "ledger.json").write_text(json.dumps(base), encoding="utf-8")
            data = root / "data"
            data.mkdir()
            snap = {"generated_at": "2026-11-13T00:00:00Z", "orbit": {}, "matches": []}
            st = cli.update_ledger(snap, [], data, root, self.getter({}), led)
            self.assertEqual((st["gcat_last"], st["ll2_since_gcat"]), ("2026-11-05", 2))
            out = json.loads((data / "ledger.json").read_text(encoding="utf-8"))
            ll2 = [r for r in out["launches"] if r["id"].startswith("ll2:")]
            self.assertEqual([r["id"] for r in ll2], ["ll2:id-002"])    # flown only; id-003 is still "Go"
            self.assertTrue(ll2[0]["provisional"])



class Feed(unittest.TestCase):
    """Ascent step 3 (25 Nov 2026): the upcoming store's live view as `launch:upcoming:...` feed items."""

    def snap(self):
        store = schedule.empty()
        schedule.ingest(store, "ll2", rows_of(rec(1, "2026-11-14T12:00:00Z", "Go")), "2026-11-13T22:00:00Z",
                        link_key="ll2_url")
        schedule.ingest(store, "closure", [{"id": "A6149/26 ZBPE", "name": "Closure with no listed launch near Taiyuan",
                                            "net": "2026-11-15T04:59:00Z", "net_precision": "closure window",
                                            "window_start": "2026-11-15T04:59:00Z",
                                            "window_end": "2026-11-15T05:28:00Z", "location": "Taiyuan",
                                            "lat": 38.849, "lon": 111.608}],
                        "2026-11-13T22:00:00Z", evidence="closure with no listing")
        store["records"][1]["by_source"]["closure"]["notices"] = ["A6149/26 ZBPE"]
        return store, {"generated_at": "2026-11-13T22:05:00Z", "lanes": {},
                       "schedule": {"read_at": "2026-11-13T22:00:00Z", "records": schedule.active(store, NOW)},
                       "unlisted": [{"notices": [{"key": "A6149/26 ZBPE", "source": "faa-nms"}]}]}

    def items(self, snap):
        from launch import feed
        return {f["properties"]["id"]: f for f in feed.build_feed(snap)["features"]}

    def test_listed_and_closure_items_pass_contract(self):
        from tic_doctrine import contract, registers
        _, snap = self.snap()
        items = self.items(snap)
        self.assertEqual(sorted(items), ["launch:upcoming:closure:A6149/26-ZBPE", "launch:upcoming:ll2:id-001"])
        regs = registers.ids(ROOT / "doctrine")
        for f in items.values():
            errs = [m for _, sev, m in contract.check(f, regs) if sev == "error"]
            self.assertEqual(errs, [], f["properties"]["id"])
            self.assertEqual(f["properties"]["subject_id"], f["properties"]["id"])
            self.assertNotIn(" ", f["properties"]["id"])
        ll2 = items["launch:upcoming:ll2:id-001"]["properties"]
        self.assertEqual(ll2["sources"][0]["id"], "ll2-thespacedevs")
        self.assertEqual(ll2["sources"][0]["url"], "https://ll.thespacedevs.com/2.3.0/launches/id-001/")
        self.assertIn("(status Go; NET precision Second)", ll2["summary"])   # COP reads these words
        self.assertEqual(ll2["event_start"], "2026-11-14T12:00:00Z")
        self.assertNotIn("event_time_precision", ll2)
        self.assertEqual(ll2["measures"]["evidence"], ["listed"])
        cl = items["launch:upcoming:closure:A6149/26-ZBPE"]["properties"]
        self.assertEqual(cl["sources"][0]["id"], "faa-nms")
        self.assertEqual(cl["measures"]["evidence"], ["closure with no listing"])
        self.assertEqual((cl["event_start"], cl["event_end"]), ("2026-11-15T04:59:00Z", "2026-11-15T05:28:00Z"))
        self.assertIn("not that a launch is coming", cl["summary"])
        self.assertEqual(cl["countries"], ["CN"])

    def test_joined_record_keeps_the_closure_id(self):
        store, snap = self.snap()
        rid = store["records"][1]["id"]
        schedule.ingest(store, "ll2", rows_of(rec(1, "2026-11-14T12:00:00Z", "Go"),
                                              rec(2, "2026-11-15T05:08:00Z", "Go")), "2026-11-13T22:30:00Z",
                        link_key="ll2_url")
        schedule.join(store, rid, "upcoming:ll2:id-002", "2026-11-13T22:30:00Z", "test")
        snap["schedule"]["records"] = schedule.active(store, NOW)
        items = self.items(snap)
        joined = items["launch:upcoming:closure:A6149/26-ZBPE"]["properties"]
        self.assertNotIn("launch:upcoming:ll2:id-002", items)
        self.assertTrue(joined["title"].startswith("Scheduled launch: Rocket | Mission 2"))   # LL2's fields show
        self.assertEqual(joined["measures"]["aliases"], ["upcoming:ll2:id-002"])
        self.assertEqual(joined["sources"][0]["id"], "ll2-thespacedevs")

    def test_coarse_and_timeless_records(self):
        _, snap = self.snap()
        r = dict(snap["schedule"]["records"][0], net_precision="Day", id="upcoming:ll2:day")
        snap["schedule"]["records"] = [r, dict(r, id="upcoming:ll2:none", net=None)]
        items = self.items(snap)
        self.assertEqual(list(items), ["launch:upcoming:ll2:day"])
        p = items["launch:upcoming:ll2:day"]["properties"]
        self.assertEqual((p["event_start"], p["event_time_precision"]), ("2026-11-14T00:00:00Z", "day"))


class SiteReadsSchedule(unittest.TestCase):
    """Orbit no longer publishes `upcoming`, so the page must count and draw scheduled launches from
    Launch's own schedule, the same rows ll2_upcoming() matches. Reading snap.orbit.upcoming showed 0 scheduled
    launches beside a list of coincidences with scheduled launches."""

    APP = (ROOT / "site_src" / "app.js").read_text(encoding="utf-8")

    def test_no_read_of_orbit_upcoming(self):
        self.assertNotIn("(snap.orbit || {}).upcoming", self.APP)

    def test_rows_from_schedule_with_ll2_ids(self):
        self.assertIn("(snap.schedule || {}).records", self.APP)
        self.assertIn("id: r.refs.ll2", self.APP)

    def test_same_rows_as_the_matcher(self):
        snap = {"schedule": {"records": [{"id": "a", "name": "A", "refs": {"ll2": "u1"}, "links": {"ll2": "x"}},
                                         {"id": "b", "name": "B", "refs": {}}]}}
        self.assertEqual([u["id"] for u in cli.ll2_upcoming(snap)], ["u1"])


if __name__ == "__main__":
    unittest.main()
