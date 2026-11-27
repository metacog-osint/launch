import unittest
from datetime import datetime, timezone

from launch import schedule, unlisted

NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)
SITES = {"Jiuquan": {"pad": [100.3, 41.0], "launches": 40, "median_min": 9.0, "q1_min": 8.0, "q3_min": 10.0}}
RING = [[100.0, 40.8], [100.6, 40.8], [100.6, 41.2], [100.0, 41.2], [100.0, 40.8]]


def area(key="A1/26", start="2026-11-29T21:06:00Z", end="2026-11-29T21:36:00Z", **kw):
    return {"source": "faa-nms", "id": key, "ring": RING, "windows": [{"start": start, "end": end}], **kw}


def listed(net="2026-11-29T21:15:00Z", precision="Minute", lat=41.0, lon=100.3, name="LM-2D"):
    return {"name": name, "net": net, "net_precision": precision, "lat": lat, "lon": lon}


class Closures(unittest.TestCase):
    def run_it(self, areas, records=(), **kw):
        return unlisted.closures(list(areas), list(records), SITES, NOW, **kw)

    def test_closure_with_no_listing(self):
        rows = self.run_it([area()])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["site"]), ("unlisted:A1/26", "Jiuquan"))
        self.assertEqual(rows[0]["evidence"], "closure with no listing")

    def test_listed_launch_in_window_removes_it(self):
        self.assertEqual(self.run_it([area()], [listed()]), [])

    def test_listed_launch_elsewhere_does_not(self):
        self.assertEqual(len(self.run_it([area()], [listed(lat=19.6, lon=110.9)])), 1)

    def test_reserve_day_of_a_listed_launch_is_left_out(self):
        a = area()
        a["windows"].append({"start": "2026-11-30T21:06:00Z", "end": "2026-11-30T21:36:00Z"})
        self.assertEqual(self.run_it([a], [listed(net="2026-11-30T21:15:00Z")]), [])

    def test_month_listing_is_named_not_treated_as_a_match(self):
        rows = self.run_it([area()], [listed(net="2026-11-30T00:00:00Z", precision="Month", name="Kuaizhou")])
        self.assertEqual(rows[0]["maybe_listed"], ["Kuaizhou"])

    def test_no_schedule_read_means_no_rows(self):
        self.assertEqual(self.run_it([area()], schedule_ok=False), [])

    def test_past_horizon_and_long_and_ended_windows_are_out(self):
        self.assertEqual(self.run_it([area(start="2026-12-06T21:06:00Z", end="2026-12-06T21:36:00Z")]), [])
        self.assertEqual(self.run_it([area(end="2026-11-30T05:00:00Z")]), [])
        self.assertEqual(self.run_it([area(start="2026-11-20T21:06:00Z", end="2026-11-20T21:36:00Z")]), [])

    def test_far_from_any_site_is_out(self):
        far = area()
        far["ring"] = [[x + 60, y] for x, y in RING]
        self.assertEqual(self.run_it([far]), [])

    def test_amateur_tfr_is_out(self):
        self.assertEqual(self.run_it([area(detail={"activity": "amateur/high-power rocketry (FAA 91.143)"})]), [])

    def test_area_placed_on_a_listed_launch_elsewhere_is_out(self):
        placed = [{"area": "A1/26", "level": "time and place"}]
        self.assertEqual(self.run_it([area()], matches=placed), [])
        self.assertEqual(len(self.run_it([area()], matches=[{"area": "A1/26", "level": "time"}])), 1)

    def test_non_launch_notam_is_out(self):
        self.assertEqual(self.run_it([area(off_live="military exercise")]), [])

    def test_area_naming_a_listed_launch_is_out(self):
        named = [{"area": "A1/26", "level": "time", "named": "NG-25"}]
        self.assertEqual(self.run_it([area()], matches=named), [])

    def test_areas_opening_together_are_one_row(self):
        rows = self.run_it([area("A1/26"), area("A2/26", start="2026-11-29T21:20:00Z", end="2026-11-29T21:50:00Z"),
                            area("A3/26", start="2026-11-30T09:00:00Z", end="2026-11-30T09:30:00Z")])
        self.assertEqual(len(rows), 2)
        self.assertEqual([n["key"] for n in rows[0]["notices"]], ["A1/26", "A2/26"])
        self.assertEqual(rows[0]["end"], "2026-11-29T21:50:00Z")



def ll2(uid="u1", net="2026-11-29T21:15:00Z", precision="Minute", lat=41.0, lon=100.3, name="LM-2D"):
    return {"id": uid, "name": name, "net": net, "net_precision": precision, "lat": lat, "lon": lon}


class ClosureRecords(unittest.TestCase):
    """Ascent step 1b: closure rows as records in the multi-source upcoming store."""

    def rows(self, areas, records=()):
        return unlisted.closures(list(areas), list(records), SITES, NOW)

    def test_row_becomes_a_closure_record(self):
        store = schedule.empty()
        rep = unlisted.apply(store, self.rows([area()]), SITES, "2026-11-21T20:00:00Z")
        self.assertEqual(rep["new"], ["upcoming:closure:A1/26"])
        r = store["records"][0]
        self.assertEqual((r["sources"], r["evidence"]), (["closure"], ["closure with no listing"]))
        self.assertEqual((r["net"], r["net_precision"], r["location"]), ("2026-11-29T21:06:00Z", "closure window", "Jiuquan"))
        self.assertEqual((r["lat"], r["lon"]), (41.0, 100.3))
        pub = schedule.active(store, NOW)[0]
        self.assertEqual(pub["closure"]["notices"], ["A1/26"])
        self.assertTrue(pub["closure"]["listed"])

    def test_closure_records_are_not_listings(self):
        store = schedule.empty()
        unlisted.apply(store, self.rows([area()]), SITES, "2026-11-21T20:00:00Z")
        again = self.rows([area()], schedule.active(store, NOW))
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["maybe_listed"], [])

    def test_regrouped_row_keeps_its_record(self):
        store = schedule.empty()
        unlisted.apply(store, self.rows([area("A2/26")]), SITES, "2026-11-21T20:00:00Z")
        # An earlier notice joins the same group: the row's first key is now A1/26, the record stays A2/26's.
        rows = self.rows([area("A1/26", start="2026-11-29T21:00:00Z"), area("A2/26")])
        rep = unlisted.apply(store, rows, SITES, "2026-11-21T21:00:00Z")
        self.assertEqual(rep["new"], [])
        self.assertEqual(len(store["records"]), 1)
        self.assertEqual(store["records"][0]["by_source"]["closure"]["notices"], ["A1/26", "A2/26"])

    def test_gone_row_is_kept_and_marked(self):
        store = schedule.empty()
        unlisted.apply(store, self.rows([area()]), SITES, "2026-11-21T20:00:00Z")
        rep = unlisted.apply(store, [], SITES, "2026-11-21T21:00:00Z")
        self.assertEqual(rep["unlisted"], ["upcoming:closure:A1/26"])
        self.assertEqual(len(store["records"]), 1)
        self.assertEqual(schedule.active(store, NOW), [])

    def test_later_listing_joins_and_first_id_is_kept(self):
        store = schedule.empty()
        unlisted.apply(store, self.rows([area()]), SITES, "2026-11-21T20:00:00Z")
        schedule.ingest(store, "ll2", [ll2()], "2026-11-22T20:00:00Z")
        listed = schedule.active(store, NOW)
        rows = self.rows([area()], listed)
        self.assertEqual(rows, [])  # the listed launch now explains the closure
        rep = unlisted.apply(store, rows, SITES, "2026-11-22T20:00:00Z")
        self.assertEqual(rep["joined"], [{"kept": "upcoming:closure:A1/26", "closure": "upcoming:closure:A1/26",
                                          "listed": "upcoming:ll2:u1"}])
        self.assertEqual(len(store["records"]), 1)
        r = store["records"][0]
        self.assertEqual(r["id"], "upcoming:closure:A1/26")
        self.assertEqual(r["refs"], {"closure": "A1/26", "ll2": "u1"})
        self.assertEqual(r["name"], "LM-2D")  # LL2's fields show once it lists the launch
        self.assertEqual(schedule.resolve(store, "upcoming:ll2:u1")["id"], "upcoming:closure:A1/26")
        # The next LL2 read finds the joined record by its own id, and nothing is made twice.
        rep2 = schedule.ingest(store, "ll2", [ll2(net="2026-11-29T21:20:00Z")], "2026-11-22T21:00:00Z")
        self.assertEqual((rep2["new"], len(store["records"])), ([], 1))
        self.assertEqual(len(schedule.active(store, NOW)), 1)

    def test_day_only_or_far_listing_does_not_join(self):
        store = schedule.empty()
        unlisted.apply(store, self.rows([area()]), SITES, "2026-11-21T20:00:00Z")
        schedule.ingest(store, "ll2", [ll2("u1", net="2026-11-29T00:00:00Z", precision="Day"),
                                       ll2("u2", lat=19.6, lon=110.9)], "2026-11-22T20:00:00Z")
        rows = self.rows([area()], schedule.active(store, NOW))
        self.assertEqual(rows[0]["maybe_listed"], ["LM-2D"])
        rep = unlisted.apply(store, rows, SITES, "2026-11-22T20:00:00Z")
        self.assertEqual(rep["joined"], [])
        self.assertEqual(len(store["records"]), 3)


class FlownLaunch(unittest.TestCase):
    """A notice with reserve-day windows: once its launch flew and the schedule dropped it, the notice is that
    launch's, not a closure with no listing."""
    WINDOWS = [{"start": "2026-11-20T21:06:00Z", "end": "2026-11-20T21:36:00Z"},
               {"start": "2026-11-22T21:06:00Z", "end": "2026-11-22T21:36:00Z"}]

    def flown(self, lat=41.0, lon=100.3, net="2026-11-20T21:15:00Z", precision="Minute"):
        return [{"name": "LM-2D", "net": net, "net_precision": precision, "lat": lat, "lon": lon, "status": "Success"}]

    def test_reserve_day_after_the_launch_flew_is_no_row(self):
        a = area(windows=self.WINDOWS)
        self.assertEqual(len(unlisted.closures([a], [], SITES, NOW)), 1)
        self.assertEqual(unlisted.closures([a], [], SITES, NOW, flown=self.flown()), [])

    def test_a_launch_elsewhere_or_outside_the_windows_keeps_the_row(self):
        a = area(windows=self.WINDOWS)
        self.assertEqual(len(unlisted.closures([a], [], SITES, NOW, flown=self.flown(lat=28.5, lon=-80.6))), 1)
        self.assertEqual(len(unlisted.closures([a], [], SITES, NOW, flown=self.flown(net="2026-11-19T10:00:00Z"))), 1)
        self.assertEqual(len(unlisted.closures([a], [], SITES, NOW, flown=self.flown(precision="Day"))), 1)

    def test_recent_flown_from_the_ll2_ledger(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("launch_cli_unlisted",
                                                      Path(__file__).resolve().parents[1] / "tools" / "launch.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        led = {"launches": [{"id": "a", "net": "2026-11-20T21:15:00Z", "status": "Success"},
                            {"id": "b", "net": "2026-11-20T22:00:00Z", "status": "Go"},
                            {"id": "c", "net": "2026-10-01T00:00:00Z", "status": "Success"},
                            {"id": "d", "net": "2026-11-23T00:00:00Z", "status": "Success"}]}
        self.assertEqual([r["id"] for r in cli.recent_flown(led, NOW)], ["a"])
        self.assertEqual(cli.recent_flown(None, NOW), [])


if __name__ == "__main__":
    unittest.main()
