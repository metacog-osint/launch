"""site_src/traj.js (the Paste tab's trajectory analysis), run in Node. Skipped where Node is not installed."""
import json
import pathlib
import shutil
import subprocess
import unittest

from launch import history

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAJ = (ROOT / "site_src" / "traj.js").as_uri()
NODE = shutil.which("node")

SCRIPT = """
import * as T from %s;
const out = {};
out.inc = [[28.5, 90], [51.8845, 347.9], [45.92, 63.3], [19.6, 175], [-2.3, 0]].map(([lat, az]) => T.inclination(lat, az));
out.bearing = [T.bearing([0, 0], [0, 10]), T.bearing([0, 0], [10, 0]), T.bearing([0, 0], [-10, 0]), T.bearing([179, 0], [-179, 0])];
out.dist = T.distNm([0, 0], [0, 1]);
out.mirror = [T.mirrorAzimuth(10), T.mirrorAzimuth(350), T.mirrorAzimuth(90)];
out.types = [5, 51.6, 90, 97.4, 98.5, 103, 140].map(T.orbitType);
out.centre = T.areaCentre([[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]);
out.straight = T.analyse([0, 0], [{ label: "far", point: [0, 20] }, { label: "near", point: [0, 10] }]);
out.dogleg = T.analyse([0, 0], [{ label: "far", point: [0, 20] }, { label: "off", point: [5, 10] }]);
out.behind = T.analyse([0, 0], [{ label: "far", point: [0, 20] }, { label: "back", point: [0, -5] }]);
out.big = T.analyse([0, 0], [{ label: "far", point: [0, 20] }, { label: "wide", ring: [[0.5, 9], [1.5, 9], [1.5, 11], [0.5, 11], [0.5, 9]] }]);
out.one = T.analyse([0, 0], [{ label: "only", point: [3, 3] }]);
out.near = T.nearestSites([{ name: "A", lon: 0, lat: 0 }, { name: "B", lon: 10, lat: 0 }, { name: "C", lon: 1, lat: 0 }], [2, 0], 2).map((x) => x.site.name);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node is not installed")
class TrajTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % json.dumps(TRAJ)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise AssertionError(r.stderr)
        cls.o = json.loads(r.stdout)

    def test_inclination_matches_history_py(self):
        for (lat, az), got in zip([(28.5, 90), (51.8845, 347.9), (45.92, 63.3), (19.6, 175), (-2.3, 0)], self.o["inc"]):
            self.assertAlmostEqual(got, history.inclination(lat, az), delta=0.051)
        self.assertAlmostEqual(self.o["inc"][0], 28.5, places=6)   # due east: the pad's latitude
        self.assertAlmostEqual(self.o["inc"][1], 97.4, delta=0.1)  # Vostochny's sun-synchronous corridor
        self.assertAlmostEqual(self.o["inc"][4], 90.0, places=6)   # due north: polar

    def test_bearing_and_distance(self):
        b = self.o["bearing"]
        self.assertAlmostEqual(b[0], 0, places=6)
        self.assertAlmostEqual(b[1], 90, places=6)
        self.assertAlmostEqual(b[2], 270, places=6)
        self.assertAlmostEqual(b[3], 90, places=6)  # east across the antimeridian
        self.assertAlmostEqual(self.o["dist"], 60.04, delta=0.05)  # one degree of latitude

    def test_mirror_and_types(self):
        self.assertEqual([round(x, 6) for x in self.o["mirror"]], [170, 190, 90])
        self.assertEqual(self.o["types"], ["Near-equatorial", "Prograde", "Near-polar",
                                           "Retrograde, sun-synchronous range", "Retrograde, sun-synchronous range",
                                           "Retrograde", "Retrograde"])

    def test_area_centre(self):
        c = self.o["centre"]
        self.assertAlmostEqual(c["centre"][0], 0, places=6)
        self.assertAlmostEqual(c["centre"][1], 0, places=6)
        self.assertAlmostEqual(c["radius"], 84.9, delta=0.2)

    def test_rows_nearest_first_and_path(self):
        s = self.o["straight"]
        self.assertEqual([r["label"] for r in s["rows"]], ["near", "far"])
        self.assertEqual(s["path"][0], [0, 0])
        self.assertTrue(s["dogleg"]["tested"])
        self.assertFalse(s["dogleg"]["flagged"])

    def test_dogleg(self):
        d = self.o["dogleg"]["dogleg"]
        self.assertTrue(d["flagged"])
        self.assertEqual(d["worst"]["label"], "off")
        self.assertGreater(d["worst"]["line"]["off"], 250)

    def test_behind_the_pad(self):
        d = self.o["behind"]["dogleg"]
        self.assertTrue(d["flagged"])
        self.assertTrue(d["worst"]["line"]["behind"])

    def test_a_wide_area_the_line_crosses_is_on_it(self):
        self.assertFalse(self.o["big"]["dogleg"]["flagged"])  # centre 1 deg off, but the area reaches the line

    def test_one_area_is_not_tested(self):
        self.assertFalse(self.o["one"]["dogleg"]["tested"])

    def test_nearest_sites(self):
        self.assertEqual(self.o["near"], ["C", "A"])


if __name__ == "__main__":
    unittest.main()
