"""site_src/facets.js (the History tab's FIR and "Notices joined by" facets), run in Node on made-up records and on the
built data/launches.json. Skipped where Node is not installed."""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACETS = (ROOT / "site_src" / "facets.js").as_uri()
NODE = shutil.which("node")

SCRIPT = """
import * as F from %s;
import { readFileSync } from "node:fs";
const recs = JSON.parse(readFileSync(0, "utf8"));
const out = recs.map((r) => ({ firs: F.firs(r, r._events || []), joined: F.joinedBy(r) }));
out.push({ notes: Object.keys(F.JOIN_NOTES).length });
out.push({ owners: [F.owners({ payloads: { owners: ["ESA/NASA", "NASA", "SPXS?", "-"] } }), F.owners({})] });
console.log(JSON.stringify(out));
"""

RECORDS = [
    {"id": "a", "status": "launched", "join": {"pass": 1, "hours": 0.2, "nm": 3, "same": True},
     "_events": [{"notams": [{"number": "A0001/26", "q": {"fir": "ZSHA"}}, {"number": "A0002/26", "q": None}]}],
     "nfc_notices": [{"fir": "ZGZU/ZJSA"}], "nfc_join": {"by": "tag"},
     "joey_notices": [{"fir": "ZSHA", "locations": ["ZSHA", "ZPKM"], "join": {"by": "notam"}},
                      {"fir": "ZLHW", "locations": [], "join": {"by": "window"}}]},
    {"id": "b", "status": "upcoming", "closures": [{"area": "A6107/26 ZLHW"}, {"area": "navarea-xii-836-26"},
                                                    {"area": "FDC 6/9861"}, {"area": "B5029/26"}]},
    {"id": "c", "status": "launched", "published_notices": [{"issuer": "Philippines (RPHI)"}],
     "archive_notices": [{"kind": "faa-tfr", "join": {"by": "window"}}], "forum": [{"url": "x"}],
     "chart_joins": [{"pass": 0}, {"pass": 4}], "nfc_join": {"by": "slip"}},
    {"id": "d", "status": "notice", "_events": [{"notams": [{"q": {"fir": "RPHI"}}]}]},
    {"id": "e", "status": "launched", "saved_notices": [{"firs": ["KZAK", "not-a-fir"]}]},
    {"id": "f", "status": "launched"},
]


@unittest.skipUnless(NODE, "node not installed")
class TestFacets(unittest.TestCase):
    def run_js(self, recs):
        r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % json.dumps(FACETS)], input=json.dumps(recs),
                           capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        return json.loads(r.stdout)

    def test_made_up_records(self):
        a, b, c, d, e, f, notes, own = self.run_js(RECORDS)
        self.assertEqual(a["firs"], ["ZGZU", "ZJSA", "ZLHW", "ZPKM", "ZSHA"])
        self.assertEqual(a["joined"], ["Charted notice: same time and place", "NotamForChina: lists this launch",
                                       "Notice: same NOTAM number and FIR", "Notice: its window holds the launch"])
        # A closure's FIR is the code after the NOTAM number; navigational warnings and TFRs have none.
        self.assertEqual(b["firs"], ["ZLHW"])
        self.assertEqual(b["joined"], ["Live closure coincided"])
        self.assertEqual(c["firs"], ["RPHI"])
        self.assertEqual(c["joined"], ["Charted notice: same NOTAM number", "Charted notice: no pad charted, nearest in time",
                                       "NotamForChina: same vehicle and site within 72 h",
                                       "Notice: its window holds the launch", "Forum thread",
                                       "Published notice (reviewed copy)"])
        self.assertEqual(d, {"firs": ["RPHI"], "joined": ["Notice with no identified launch"]})
        self.assertEqual(e, {"firs": ["KZAK"], "joined": ["Notice saved in this browser"]})
        self.assertEqual(f, {"firs": ["No FIR"], "joined": ["No notice joined"]})
        self.assertEqual(notes, {"notes": 9})
        self.assertEqual(own, {"owners": [["ESA", "NASA", "SPXS"], ["None listed"]]})

    @unittest.skipUnless((ROOT / "site" / "data" / "launches.json").exists(), "site/ not built")
    def test_built_data_every_value_is_worded(self):
        recs = json.loads((ROOT / "site" / "data" / "launches.json").read_text(encoding="utf-8"))["records"]
        out = self.run_js(recs)[:-2]   # the last two lines are the script's own checks
        firs = {v for o in out for v in o["firs"]}
        self.assertTrue(all(v == "No FIR" or (len(v) == 4 and v.isalpha() and v.isupper()) for v in firs), firs)
        joined = {v for o in out for v in o["joined"]}
        self.assertNotIn("undefined", " ".join(joined))
        self.assertGreater(len(joined), 3)


if __name__ == "__main__":
    unittest.main()
