"""launch/overfly.py: the countries a History flight path's ground track crosses."""
import json
import pathlib
import unittest

from launch import catalog, overfly

ROOT = pathlib.Path(__file__).resolve().parents[1]


def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


# Made-up countries along the equator: AA from 0 to 10 E, BB from 10 to 20 E with an enclave CC kept without a hole,
# DD from 25 to 30 E, EE in two pieces either side of a 0.2-degree channel (12 NM), FF either side of the antimeridian.
WORLD = overfly.World({"countries": [
    {"cc": "AA", "rings": [square(0, -5, 10, 5)]},
    {"cc": "BB", "rings": [square(10, -5, 20, 5)]},
    {"cc": "CC", "rings": [square(14, -1, 16, 1)]},
    {"cc": "DD", "rings": [square(25, -5, 30, 5)]},
    {"cc": "EE", "rings": [square(40, -5, 45, 5), square(45.2, -5, 50, 5)]},
    {"cc": "FF", "rings": [square(175, -5, 180, 5), square(-180, -5, -175, 5)]},
]})
DEG_NM = overfly.R_NM * 3.141592653589793 / 180


class LookupTest(unittest.TestCase):
    def test_points(self):
        self.assertEqual(WORLD.at(5, 0), "AA")
        self.assertEqual(WORLD.at(12, 0), "BB")
        self.assertEqual(WORLD.at(15, 0), "CC")  # the enclave, not its neighbour
        self.assertIsNone(WORLD.at(22, 0))
        self.assertEqual(WORLD.at(184, 0), "FF")  # a longitude past 180, as the map's lines run
        self.assertEqual(WORLD.at(-177, 0), "FF")


class RunsTest(unittest.TestCase):
    def test_due_east_along_the_equator(self):
        over = overfly.runs(WORLD, overfly.track_samples(1, 0, 90, 29 * DEG_NM))
        self.assertEqual([r["cc"] for r in over], ["AA", "BB", "CC", "BB", "DD"])
        aa, bb = over[0], over[1]
        self.assertEqual(aa["from"], 0)
        self.assertAlmostEqual(aa["to"], 9 * DEG_NM, delta=overfly.SAMPLE_NM)
        self.assertAlmostEqual(bb["from"], 9 * DEG_NM, delta=overfly.SAMPLE_NM)
        dd = over[-1]
        self.assertAlmostEqual(dd["from"], 24 * DEG_NM, delta=overfly.SAMPLE_NM)

    def test_short_gap_is_closed(self):
        over = overfly.runs(WORLD, overfly.track_samples(41, 0, 90, 8 * DEG_NM))
        self.assertEqual([r["cc"] for r in over], ["EE"])

    def test_over_the_antimeridian(self):
        over = overfly.runs(WORLD, overfly.line_samples([[176, 0], [-176, 0]]))
        self.assertEqual([r["cc"] for r in over], ["FF"])
        self.assertAlmostEqual(over[0]["to"], 8 * DEG_NM, delta=overfly.SAMPLE_NM)

    def test_charted_paths_merge(self):
        rec = {"path": {"kind": "drawn", "az": 90, "nm": None}, "pad": [1, 0]}
        over = overfly.overflight(WORLD, rec, [[[1, 0], [12, 0]], [[1, 0.5], [14, 0.5], [27, 0.5]]])
        self.assertEqual([[r["cc"] for r in p] for p in over], [["AA", "BB", "CC", "BB", "DD"], ["AA", "BB"]])  # longest first

    def test_nothing_to_read(self):
        self.assertIsNone(overfly.overflight(WORLD, {}, []))
        self.assertIsNone(overfly.overflight(WORLD, {"path": {"kind": "drawn"}}, []))
        self.assertIsNone(overfly.overflight(WORLD, {"path": {"kind": "estimated", "az": 90, "nm": 100}, "pad": None}, []))
        self.assertEqual(overfly.overflight(WORLD, {"path": {"kind": "estimated", "az": 90, "nm": 100}, "pad": [21, 0]}, []), [[]])


class KitTest(unittest.TestCase):
    """The kit's real outlines."""

    @classmethod
    def setUpClass(cls):
        cls.w = overfly.World(json.loads((ROOT / "doctrine" / "kit" / "geo" / "countries.json").read_text(encoding="utf-8")))

    def test_places(self):
        for (lon, lat), cc in {(116.4, 39.9): "CN", (-80.6, 28.56): "US", (28.2, -29.5): "LS", (25, -30): "ZA",
                               (121.5, 25.0): "TW", (126.9, 37.5): "KR", (125.75, 39.03): "KP", (-175, 67): "RU",
                               (0, 0): None}.items():
            self.assertEqual(self.w.at(lon, lat), cc, (lon, lat))

    def test_baikonur_north_east(self):
        # Baikonur to the north-east: Kazakhstan, then Russia.
        over = overfly.runs(self.w, overfly.track_samples(63.3, 45.92, 53.7, 1500))
        self.assertEqual([r["cc"] for r in over][:2], ["KZ", "RU"])
        self.assertEqual(over[0]["from"], 0)


class CatalogTest(unittest.TestCase):
    def test_index_carries_over(self):
        hist = {"events": [{"id": "hist:x", "layer": "Previous Russian Launches", "kind": "launch", "actor": "RU",
                            "label": "x", "cancelled": False, "time": "2024-05-01T10:00:00Z", "time_basis": "time",
                            "pad": [1, 0], "areas": [], "paths": [[[1, 0], [27, 0]]], "points": [], "notams": [],
                            "texts": [], "links": []}]}
        idx = catalog.build_index(hist, {"since": "2023-01-01", "sites": {}, "launches": [], "closures": []}, [], [],
                                  "2026-11-15T00:00:00Z", world=WORLD)
        rec = next(r for r in idx["records"] if r.get("path"))
        self.assertEqual([[r["cc"] for r in p] for p in rec["over"]], [["AA", "BB", "CC", "BB", "DD"]])
        idx = catalog.build_index(hist, {"since": "2023-01-01", "sites": {}, "launches": [], "closures": []}, [], [],
                                  "2026-11-15T00:00:00Z")
        self.assertNotIn("over", next(r for r in idx["records"] if r.get("path")))


if __name__ == "__main__":
    unittest.main()
