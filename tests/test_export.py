"""site_src/export.js (the History tab's CSV, GeoJSON and KML downloads), run in Node on made-up records and on the
built data/launches.json. Skipped where Node is not installed."""
import csv
import io
import json
import pathlib
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPORT = (ROOT / "site_src" / "export.js").as_uri()
NODE = shutil.which("node")

SCRIPT = """
import * as X from %s;
import { readFileSync } from "node:fs";
const input = JSON.parse(readFileSync(0, "utf8"));
const recs = input.recs;
const events = input.events || { "hist:a": [{ id: "hist:a", paths: [[[170, 10], [-170, 12]]],
  areas: [{ ring: [[175, 0], [-175, 0], [-175, 5], [175, 5], [175, 0]], notam: "A0001/26" }],
  notams: [{ number: "A0001/26" }] }] };
const o = { eventsFor: (r) => (r.chart || []).flatMap((id) => events[id] || []), withAreas: true,
  countryName: (cc) => ({ CN: "China", US: "United States" })[cc] || "Not known",
  link: (id) => "https://example.test/#history?sel=" + id, view: "https://example.test/#history", generated: "2026-11-16T03:00:00Z",
  zone: "America/Chicago", when: (r) => "local " + r.id };
const out = {};
out.split = X.splitLine([[170, 0], [190, 0], [200, 0]]);
out.splitWest = X.splitLine([[-170, 0], [-190, 0]]);
out.inside = X.splitLine([[10, 0], [20, 5]]);
out.ring = X.splitRing([[175, 0], [185, 0], [185, 5], [175, 5], [175, 0]]);
out.ringIn = X.splitRing([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]);
out.geo = X.toGeoJSON(recs, o);
out.csv = X.toCSV(recs, o);
out.kml = X.toKML(recs, o);
out.noAreas = X.toGeoJSON(recs, { ...o, withAreas: false }).features.map((f) => f.properties.feature);
out.name = X.fileName("kml", o.generated);
console.log(JSON.stringify(out));
"""

RECS = [
    {"id": "hist:a", "status": "launched", "time": "2026-03-01T12:30:00Z", "time_basis": "time", "actor": "CN",
     "label": "=HYPERLINK(\"x\")", "vehicle": "LM-2C", "payload": "Test, \"one\"", "programmes": ["Yaogan"],
     "mtype": "Earth observation", "site": "Jiuquan", "pad": [170.0, 10.0], "orbit": "LEO", "inc": 97.4,
     "outcome": "success", "path": {"kind": "drawn", "az": 80, "nm": None, "basis": "path as charted"},
     "sources": ["chart", "gcat"], "chart": ["hist:a"], "gcat": "2026-001",
     "nfc_notices": [{"number": "A0002/26", "ring": [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]}]},
    {"id": "gcat:b", "status": "upcoming", "time": "2026-12-01T00:00:00Z", "time_basis": "date", "actor": "US",
     "label": "B", "vehicle": "Falcon 9", "payload": "Starlink", "programmes": [], "mtype": "LEO broadband constellation",
     "site": "Cape Canaveral", "pad": [-80.5774, 28.5619], "orbit": "LEO",
     "path": {"kind": "estimated", "az": 45, "nm": 100, "basis": "orbit class"}, "sources": ["ll2"]},
    {"id": "hist:c", "status": "notice", "time": None, "time_basis": "none", "actor": None, "label": "No pad",
     "vehicle": None, "payload": None, "programmes": [], "mtype": "Payload not known", "site": None, "pad": None,
     "orbit": "Not known", "sources": ["chart"]},
]


def run(recs, events=None):
    r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % json.dumps(EXPORT)],
                       input=json.dumps({"recs": recs, "events": events}), capture_output=True, text=True,
                       timeout=180, encoding="utf-8")
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def in_range(coords):
    if isinstance(coords[0], (int, float)):
        return -180 <= coords[0] <= 180 and -90 <= coords[1] <= 90
    return all(in_range(c) for c in coords)


@unittest.skipUnless(NODE, "Node is not installed")
class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = run(RECS)

    def test_antimeridian_lines(self):
        self.assertEqual(self.o["split"], [[[170, 0], [180, 0]], [[-180, 0], [-170, 0], [-160, 0]]])
        self.assertEqual(self.o["splitWest"], [[[-170, 0], [-180, 0]], [[180, 0], [170, 0]]])
        self.assertEqual(self.o["inside"], [[[10, 0], [20, 5]]])

    def test_antimeridian_rings(self):
        parts = self.o["ring"]
        self.assertEqual(len(parts), 2)
        for p in parts:
            self.assertEqual(p[0], p[-1])
            self.assertTrue(in_range(p))
        xs = sorted({x for p in parts for x, _ in p})
        self.assertEqual(xs, [-180, -175, 175, 180])
        self.assertEqual(len(self.o["ringIn"]), 1)
        ring = self.o["ringIn"][0]  # anticlockwise (RFC 7946 3.1.6)
        area = sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1))
        self.assertGreater(area, 0)

    def test_geojson(self):
        g = self.o["geo"]
        self.assertEqual(g["type"], "FeatureCollection")
        self.assertIn("CC BY 4.0", g["attribution"])
        kinds = [f["properties"]["feature"] for f in g["features"]]
        self.assertEqual(kinds.count("launch"), 3)
        self.assertEqual(kinds.count("flight path"), 2)
        self.assertEqual(kinds.count("closure area"), 2)  # one charted, one NotamForChina
        for f in g["features"]:
            if f["geometry"]:
                self.assertTrue(in_range(f["geometry"]["coordinates"]), f["properties"])
        a = g["features"][0]
        self.assertEqual(a["geometry"], {"type": "Point", "coordinates": [170, 10]})
        self.assertEqual(a["properties"]["notams"], "A0001/26; A0002/26")
        self.assertEqual(a["properties"]["sources"], "Launch's charted notices; GCAT")
        path = next(f for f in g["features"] if f["properties"]["feature"] == "flight path")
        self.assertEqual(path["geometry"]["type"], "MultiLineString")  # the charted path crosses 180
        self.assertIsNone(g["features"][-1]["geometry"])  # no pad: kept, with no geometry
        self.assertEqual(self.o["noAreas"].count("closure area"), 0)

    def test_csv(self):
        text = self.o["csv"]
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
        self.assertEqual(len(rows), 3)
        self.assertIn("when (America/Chicago)", rows[0])
        a, b, c = rows
        self.assertEqual(a["label"], "'=HYPERLINK(\"x\")")  # a formula is kept as text
        self.assertEqual(a["payload"], 'Test, "one"')
        self.assertEqual(a["time_utc"], "2026-03-01T12:30Z")
        self.assertEqual(a["closure_areas"], "2")
        self.assertEqual(b["time_utc"], "2026-12-01")  # a date stays a date
        self.assertEqual(b["outcome"], "Scheduled")
        self.assertEqual(b["pad_lon"], "-80.5774")  # numbers are not prefixed
        self.assertEqual(c["when (America/Chicago)"], "")
        self.assertEqual(c["pad_lat"], "")

    def test_kml(self):
        root = ET.fromstring(self.o["kml"].encode("utf-8"))
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        self.assertEqual(len(root.findall(".//k:Folder", ns)), 3)
        self.assertIn("CC BY 4.0", root.find("k:Document/k:description", ns).text)
        for c in root.iter("{http://www.opengis.net/kml/2.2}coordinates"):
            for pt in c.text.split():
                x, y = map(float, pt.split(","))
                self.assertTrue(-180 <= x <= 180 and -90 <= y <= 90)
        self.assertEqual(root.find(".//k:TimeStamp/k:when", ns).text, "2026-03-01T12:30Z")
        self.assertEqual(self.o["name"], "launch-history-2026-11-16.kml")


@unittest.skipUnless(NODE, "Node is not installed")
@unittest.skipUnless((ROOT / "site" / "data" / "launches.json").exists(), "site/ not built")
class ExportBuiltDataTest(unittest.TestCase):
    """The whole built list exports, every coordinate within range."""

    def test_built_list(self):
        recs = json.loads((ROOT / "site" / "data" / "launches.json").read_text(encoding="utf-8"))["records"]
        events = {}
        for e in json.loads((ROOT / "site" / "data" / "history.json").read_text(encoding="utf-8"))["events"]:
            events.setdefault(e["id"], []).append(e)
        o = run(recs, events)
        g = o["geo"]
        self.assertEqual(sum(f["properties"]["feature"] == "launch" for f in g["features"]), len(recs))
        bad = [f["properties"].get("id") for f in g["features"] if f["geometry"] and not in_range(f["geometry"]["coordinates"])]
        self.assertEqual(bad, [])
        self.assertEqual(len(list(csv.reader(io.StringIO(o["csv"].lstrip("﻿"))))), len(recs) + 1)
        ET.fromstring(o["kml"].encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
