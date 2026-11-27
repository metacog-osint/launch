"""site_src/same.js (the History tab's "same closures" filter, near=), run in Node on made-up records. Its numbers
must stay those of launch/payloads.py's closure signature. Skipped where Node is not installed."""
import json
import pathlib
import shutil
import subprocess
import unittest

from launch import notam, payloads

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAME = (ROOT / "site_src" / "same.js").as_uri()
NODE = shutil.which("node")

SCRIPT = """
import * as S from %s;
import { readFileSync } from "node:fs";
const inp = JSON.parse(readFileSync(0, "utf8"));
const out = { consts: [S.SIG_NM, S.NEAR_PAD_NM] };
out.centres = inp.recs.map((r) => S.centres(r, r._events || []));
out.targets = inp.recs.map((r) => S.targets(r, r._events || []));
out.near = inp.recs.map((r) => S.near(S.centres(r, r._events || []), inp.points));
out.read = S.read(inp.addr);
out.write = S.write([[28.246, 102.0249], [-5.5, 179.999]]);
out.ring = S.centroid(inp.ring);
out.nm = S.nm([0, 0], [1, 0]);
console.log(JSON.stringify(out));
"""

SQ = lambda lon, lat, d=0.2: [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]

RECS = [
    # a: pad at Xichang, one charted area at the pad (centroid given), one Joey0609 area ~300 NM downrange.
    {"id": "a", "pad": [102.03, 28.25], "_events": [{"areas": [{"centroid": [102.05, 28.2], "ring": SQ(102.05, 28.2)}]}],
     "joey_notices": [{"rings": [SQ(106.0, 25.0)]}]},
    # b: only a pad closure: targets fall back to it.
    {"id": "b", "pad": [102.03, 28.25], "closures": [{"ring": SQ(102.1, 28.3)}]},
    # c: a published notice (one ring), an archive notice with two, a ring too short to count.
    {"id": "c", "published_notices": [{"ring": SQ(106.3, 25.2)}], "archive_notices": [{"rings": [SQ(-80, 28), [[0, 0], [1, 1]]]}]},
    # d: nothing.
    {"id": "d"},
]


@unittest.skipUnless(NODE, "node not installed")
class TestSame(unittest.TestCase):
    def run_js(self, inp):
        r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % json.dumps(SAME)], input=json.dumps(inp),
                           capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        return json.loads(r.stdout)

    def test_same_closures(self):
        ring = [[179.5, 10], [-179.5, 10], [-179.5, 11], [179.5, 11], [179.5, 10]]
        o = self.run_js({"recs": RECS, "points": [[25.0, 106.0]], "ring": ring,
                         "addr": "25,106; 28.246,102.0249;bad;91,0;-5.5,-180"})
        self.assertEqual(o["consts"], [payloads.SIG_NM, payloads.NEAR_PAD_NM])
        self.assertEqual([len(c) for c in o["centres"]], [2, 1, 2, 0])
        # a: the pad area is left out; b: only a pad area, so it is used and flagged.
        self.assertEqual(o["targets"][0], {"points": [[25.0, 106.0]], "atPad": False})
        self.assertEqual(o["targets"][1], {"points": [[28.3, 102.1]], "atPad": True})
        self.assertEqual(o["targets"][3], {"points": [], "atPad": False})
        # c's published notice is ~19 NM from a's downrange area; b's only area is ~300 NM away.
        self.assertEqual(o["near"], [True, False, True, False])
        self.assertEqual(o["read"], [[25, 106], [28.25, 102.02], [-5.5, -180]])
        self.assertEqual(o["write"], "28.25,102.02;-5.5,180")
        # The same centre as notam.centroid() in Python, across the antimeridian too.
        self.assertEqual([round(x, 6) for x in o["ring"]], [round(x, 6) for x in notam.centroid(ring)])
        self.assertAlmostEqual(o["nm"], notam.haversine_nm(0, 0, 1, 0), delta=0.5)


if __name__ == "__main__":
    unittest.main()
