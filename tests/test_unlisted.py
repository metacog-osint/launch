import unittest
from datetime import datetime, timezone

from launch import unlisted

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


if __name__ == "__main__":
    unittest.main()
