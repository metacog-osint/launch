"""Offline tests for the public gate (launch/public.py): what of the source map may reach the published
history file. The map in these tests is made up; no real ship, position or note is in it.

The last class reads the committed history/history.json, the file that is published as data/history.json. It
fails if a site named YW-*, or a site note holding a speed, a heading or a coordinate, is in it.
Run: python -m unittest discover -s tests"""
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from launch import history, notam, patterns, public  # noqa: E402
from synthetic_terms import TERMS  # noqa: E402

SHIP_AT = [-150.5, -45.25]        # the made-up tracking ship
RESTRICTED_AT = [-140.0, -50.0]   # the made-up sea-launch position whose note names a restricted tool
KML = """<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>map</name>
<Folder><name>Launch Sites</name>
 <Placemark><name>LC-9A</name><description>TAIYUAN 3851N 11136E. FIRST SEEN 0846Z</description><Point><coordinates>111.6085,38.8491,0</coordinates></Point></Placemark>
 <Placemark><name>Dongfeng Landing Site</name><description>CAPSULE LANDINGS</description><Point><coordinates>100.07,41.6,0</coordinates></Point></Placemark>
 <Placemark><name>Kura Missile Test Range</name><Point><coordinates>162.5,57.3,0</coordinates></Point></Placemark>
 <Placemark><name>YW-99</name><description>14 NOV 0846Z HDG 090 12 KTS</description><Point><coordinates>-150.5,-45.25,0</coordinates></Point></Placemark>
 <Placemark><name>2 Feb 30_0202UTC_Testrocket-2_Payload</name><description>LAUNCH SHIP</description><Point><coordinates>-141.0,-50.5,0</coordinates></Point></Placemark>
 <Placemark><name>1 Jan 30_0101Z Testrocket-1</name><description>POSITION PER QQ
VIEW</description><Point><coordinates>-140.0,-50.0,0</coordinates></Point></Placemark>
 <Placemark><name>Bohu Laser Facility</name><Point><coordinates>86.6,41.9,0</coordinates></Point></Placemark>
 <Placemark><name>Brand New Marker</name><description>ADDED LATER</description><Point><coordinates>10,10,0</coordinates></Point></Placemark>
</Folder>
<Folder><name>2026 - Previous Chinese Launches</name>
 <Placemark><name>1 Jan 30_0101 UTC_Testrocket-1_Payload</name><LineString><coordinates>-140.0,-50.0,0 -139.0,-53.0,0</coordinates></LineString></Placemark>
 <Placemark><name>1 Jan 30_0101 UTC_Testrocket-1_Payload</name><description>ZQDETECT CONFIRMS LAUNCH DETECTED</description><Point><coordinates>-139.2,-52.0,0</coordinates></Point></Placemark>
 <Placemark><name>1 Jan 30_0101 UTC_Testrocket-1_Payload</name><Point><coordinates>-140.0001,-50.0001,0</coordinates></Point></Placemark>
 <Placemark><name>1 Jan 30_0101 UTC_Testrocket-1_Payload</name><Point><coordinates>-138.5,-52.5,0</coordinates></Point></Placemark>
 <Placemark><name>1 Jan 30_0101 UTC_Testrocket-1_Payload</name><description>A4754/26 NOTAMN&lt;br&gt;Q)NZZO/QRDCA/IV/BO/W/000/999/5300S13900W012&lt;br&gt;A)NZZO B)3001010050 C)3001010130&lt;br&gt;E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:&lt;br&gt;S530200W1390100-S530400W1391500-S534400W1391800-S534200W1390400&lt;br&gt;BACK TO START.&lt;br&gt;F)SFC G)UNL</description>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>-139.0166667,-53.0333333,0 -139.25,-53.0666667,0 -139.3,-53.7333333,0 -139.0666667,-53.7,0 -139.0166667,-53.0333333,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
 <Placemark><name>1 Jan 30_0101 UTC_Testrocket-1_Payload</name><description>A4754/26 NOTAMN&lt;br&gt;Q)NZZO/QRDCA/IV/BO/W/000/999/5300S13900W012&lt;br&gt;A)NZZO B)3001010050 C)3001010130&lt;br&gt;E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:&lt;br&gt;S530200W1390100-S530400W1391500-S534400W1391800-S534200W1390400&lt;br&gt;BACK TO START.&lt;br&gt;F)SFC G)UNL</description><Point><coordinates>-139.1,-53.4,0</coordinates></Point></Placemark>
 <Placemark><name>24 Sep 26_ 0846 UTC_LM-6A_ Yaogan-40 04A-C</name><description>ZQDETECT CONFIRMS LAUNCH DETECTED</description>
  <LineString><coordinates>111.6085,38.8491,0 112.16,35.88,0</coordinates></LineString></Placemark>
</Folder>
<Folder><name>Unknown NOTAMs</name>
 <Placemark><name>YW99</name><description>ON STATION</description><Point><coordinates>-151.0,-46.0,0</coordinates></Point></Placemark>
 <Placemark><name>Liao wang 9</name><description>ARRIVED</description><Point><coordinates>-152.0,-47.0,0</coordinates></Point></Placemark>
 <Placemark><name>Marker only</name><description>SEEN HERE</description><Point><coordinates>-153.0,-48.0,0</coordinates></Point></Placemark>
</Folder></Document></kml>"""
SHIPS_IN_EVENTS = [[-151.0, -46.0], [-152.0, -47.0]]
BARE_POINT = [-153.0, -48.0]
ALLOW = {"kinds": {"LC-9A": "launch pad", "Dongfeng Landing Site": "landing site", "Kura Missile Test Range": "drop zone"},
         "notes": {}, "held": {"Bohu Laser Facility": "a laser facility"}, "problems": []}


def public_doc(allow=ALLOW):
    """The fixture map as tools/launch.py history writes it."""
    history.use_terms(TERMS)
    doc = history.load(KML)
    sites, gate = public.sites(doc["sites"], allow)
    hist = {"source": "x.kml", "sites_rule": public.RULE, "sites": sites, "events": doc["events"]}
    return doc, hist, patterns.build(doc["events"], sites), gate


def positions(hist):
    """Every point position in a history file: sites, event pads, path vertices and points."""
    out = [[s["lon"], s["lat"]] for s in hist["sites"]]
    for e in hist["events"]:
        out += ([e["pad"]] if e.get("pad") else []) + [v for ln in e["paths"] for v in ln] + list(e["points"])
    return out


def near(pts, where, nm=1.0):
    return [p for p in pts if notam.haversine_nm(p[1], p[0], where[1], where[0]) <= nm]


class Screens(unittest.TestCase):
    def test_speed_heading_coordinate_and_time_are_seen(self):
        for label, samples in {
            "a speed": ["12 kts", "making 14.5 knots", "SOG 9", "8kn", "speed unknown"],
            "a heading": ["hdg 090", "heading north", "course 270", "COG 135", "090T", "270 true", "97 deg", "southbound"],
            "a coordinate": ["3553N 11209E", "N360200E1120100", "360200N1120100E", "59-42.60S 165-49.20E",
                             "36 31 00 S 131 00 00 W", "38.8491, 111.6085", "38.85N 111.61E", "38N 111E", "40.96° N",
                             "51RUQ1234567890", "lat 38.8", "coords below"],
            "a time of day": ["0846Z", "1132 UTC", "19:24", "at 0300 local", "9 pm"],
        }.items():
            for text in samples:
                self.assertIn(label, public.note_problems(text), text)

    def test_plain_notes_pass(self):
        for text in ["Taiyuan", "Crew capsule landings since 2021", "Pad for the Long March 7 and 8",
                     "China's 2026 plans name this pad", "100 m from the old tower", "Built 2014 to 2016",
                     "SLC-4E's neighbour", "Soyuz-2.1b pad", "Used by LM-2C, LM-2D and LM-4C", "3 km from the coast"]:
            self.assertEqual(public.note_problems(text), [], text)

    def test_ship_and_dated_names_are_seen(self):
        for name in ["YW-99", "YW5", "yw 3", "Yuan Wang 5", "Yuanwang-7", "Liao wang 9", "Liaowang-9", "Tracking ship",
                     "USNS Example"]:
            self.assertIn("reads as a ship", public.name_problems(name), name)
        for name in ["2 Feb 30_0202UTC_Testrocket-2_Payload", "13 Jan 30_0300_Testrocket-3_10x Payload",
                     "22 March 2030_1549Z_Testrocket-3", "5 Dec 30_19:24UTC_Testrocket-3"]:
            self.assertTrue(public.name_problems(name), name)

    def test_pad_names_pass(self):
        for name in ["LC-9A", "SLC-4E", "4W / LZ-4", "576E", "1S (Soyuz)", "LC 31/6", "LC-16-01", "MARS Pad 0A",
                     "5/X or 2.2 (Start-1M)", "SLS-1 (Pad 921), LC-91", "KSC Launch Complex 39A", "Starbase"]:
            self.assertEqual(public.name_problems(name), [], name)


class Gate(unittest.TestCase):
    def setUp(self):
        self.doc, self.hist, self.pat, self.gate = public_doc()

    def test_only_listed_sites_are_published_with_their_kind(self):
        self.assertEqual([(s["name"], s["kind"]) for s in self.hist["sites"]],
                         [("LC-9A", "launch pad"), ("Dongfeng Landing Site", "landing site"),
                          ("Kura Missile Test Range", "drop zone")])
        self.assertEqual(self.gate["withheld"], {"the name reads as a ship": 1, "the name carries a date": 1,
                                                 "held on the allow-list": 1, "not on the allow-list": 1})
        self.assertEqual(self.gate["not_listed"], ["Brand New Marker"])
        self.assertEqual(public.problems(self.hist, self.pat, ALLOW), [])

    def test_no_ship_position_anywhere(self):
        self.assertEqual(near(positions(self.hist), SHIP_AT), [])
        self.assertNotIn("YW", json.dumps(self.hist) + json.dumps(self.pat))

    def test_a_ship_or_a_dated_name_is_never_published_even_if_listed(self):
        allow = {**ALLOW, "kinds": {**ALLOW["kinds"], "YW-99": "launch pad",
                                    "2 Feb 30_0202UTC_Testrocket-2_Payload": "launch pad"}}
        sites, _ = public.sites(self.doc["sites"], allow)
        self.assertEqual([s["name"] for s in sites], ["LC-9A", "Dongfeng Landing Site", "Kura Missile Test Range"])

    def test_the_maps_own_notes_are_never_published(self):
        self.assertTrue(all(set(s) == {"name", "lon", "lat"} for s in self.doc["sites"]))  # not even read out
        self.assertTrue(all(s["note"] is None for s in self.hist["sites"]))
        blob = json.dumps(self.hist)
        for word in ("TAIYUAN", "0846Z", "KTS", "HDG", "CAPSULE", "LAUNCH SHIP", "ADDED LATER", "QQ", "ZQDETECT"):
            self.assertNotIn(word, blob)

    def test_a_note_comes_from_the_allow_list_only(self):
        allow = {**ALLOW, "notes": {"LC-9A": "Solid and liquid pads at Taiyuan"}}
        _, hist, pat, gate = public_doc(allow)
        self.assertEqual(hist["sites"][0]["note"], "Solid and liquid pads at Taiyuan")
        self.assertEqual(gate["notes"], 1)
        self.assertEqual(public.problems(hist, pat, allow), [])

    def test_a_position_whose_note_names_a_restricted_source_is_withheld_wherever_it_is_drawn(self):
        self.assertEqual(near(positions(self.hist), RESTRICTED_AT), [])     # not a site, pad, path vertex or point
        e = next(x for x in self.hist["events"] if "Testrocket-1" in x["label"])
        self.assertEqual((e["paths"], e["pad"]), ([], None))                 # the path drawn from it went with it
        self.assertEqual(e["points"], [[-139.1, -53.4]])                       # only the point that carries the notice
        self.assertEqual(len(e["areas"]), 1)                                 # the notice's area stays
        self.assertEqual(self.doc["withheld"]["sites"], 1)
        self.assertEqual(self.doc["withheld"]["shapes"]["2026 - Previous Chinese Launches"], {
            "flight paths drawn at a withheld position": 1, "points whose own note names a restricted source": 1,
            "points at a withheld position": 1, "points with no notice behind them": 1})

    def test_a_ship_in_the_event_layers_is_not_imported(self):
        self.assertEqual(self.doc["withheld"]["ships"], {"Unknown NOTAMs": 2})
        for where in SHIPS_IN_EVENTS:
            self.assertEqual(near(positions(self.hist), where), [])
        blob = json.dumps(self.hist)
        for word in ("YW99", "Liao", "ON STATION", "ARRIVED"):
            self.assertNotIn(word, blob)
        self.assertFalse(any(public.ship_named(e) for e in self.hist["events"]))

    def test_a_point_with_no_notice_behind_it_is_not_imported_and_an_empty_event_goes_with_it(self):
        self.assertEqual(near(positions(self.hist), BARE_POINT), [])
        self.assertEqual(self.doc["withheld"]["empty_events"], {"Unknown NOTAMs": 1})
        self.assertEqual(self.doc["withheld"]["shapes"]["Unknown NOTAMs"], {"points with no notice behind them": 1})
        self.assertEqual(sorted(e["label"][:14] for e in self.hist["events"]), ["1 Jan 30_0101 ", "24 Sep 26_ 084"])

    def test_a_flight_path_with_a_detection_note_keeps_its_line(self):
        e = next(x for x in self.hist["events"] if "LM-6A" in x["label"])
        self.assertEqual((e["pad"], e["withheld_notes"]), ([111.6085, 38.8491], 1))


class EventRules(unittest.TestCase):
    """Two rules added on 15 Nov 2026, tested on single events."""
    NAME = "3 Mar 30_0303 UTC_Testrocket-3_Payload"

    def event(self, *placemarks):
        return history._event({"layer": "2026 - Previous Chinese Launches", "name": self.NAME,
                               "placemarks": [{"desc": d, "geoms": g} for d, g in placemarks]})

    def test_a_shape_whose_note_names_a_position_tool_is_not_imported(self):
        line = ("line", [[-120.0, -40.0], [-119.0, -42.0]])
        area = ("polygon", [[-119.0, -42.0], [-118.0, -42.0], [-118.0, -43.0], [-119.0, -42.0]])
        e, held = self.event(("TRACK FROM QQ VIEW", [line]), ("QQVIEW BOX", [area]),
                             ("ZQDETECT CONFIRMS LAUNCH DETECTED", [("line", [[-100.0, -30.0], [-99.0, -31.0]])]))
        self.assertEqual((e["areas"], e["pad"]), ([], [-100.0, -30.0]))   # the detection-note line keeps its shape
        self.assertEqual(e["paths"], [[[-100.0, -30.0], [-99.0, -31.0]]])
        self.assertEqual(held, {"shapes whose own note names a position tool": 2})
        self.assertEqual(e["withheld_notes"], 3)
        self.assertNotIn("QQ", json.dumps(e).upper())

    def test_a_warning_text_with_no_coordinate_is_withheld_and_its_point_with_it(self):
        e, held = self.event(("NAV WARNING: KEEP AN EYE ON THIS ONE", [("point", [-110.0, -35.0])]),
                             ("NAVAREA XI 1234/30. ROCKET LAUNCHING. 30-00N 120-00E 30-00N 121-00E",
                              [("point", [120.5, 30.0])]))
        self.assertEqual(len(e["texts"]), 1)
        self.assertIn("NAVAREA XI 1234/30", e["texts"][0])
        self.assertEqual(e["points"], [[120.5, 30.0]])
        self.assertEqual((held, e["withheld_notes"]), ({"points with no notice behind them": 1}, 1))

    def test_a_source_line_is_never_published(self):
        notice = ("A4754/26 NOTAMN<br>Q)NZZO/QRDCA/IV/BO/W/000/999/5300S13900W012<br>A)NZZO B)3001010050 C)3001010130"
                  "<br>E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:<br>S530200W1390100-S530400W1391500-"
                  "S534400W1391800-S534200W1390400<br>BACK TO START.<br>F)SFC G)UNL<br>SOURCE: CHAT WITH A. PERSON"
                  "<br>Source - https://example.org/x")
        warning = "NAVAREA XI 1234/30. ROCKET LAUNCHING. 30-00N 120-00E 30-00N 121-00E\nSOURCE: A FRIEND"
        e, _ = self.event((notice, []), (warning, [("point", [120.5, 30.0])]))
        self.assertEqual(len(e["notams"]), 1)
        self.assertEqual(len(e["texts"]), 1)
        blob = json.dumps(e).upper()
        for word in ("SOURCE", "CHAT WITH", "PERSON", "FRIEND"):
            self.assertNotIn(word, blob)
        self.assertIn("BACK TO START", e["notams"][0]["text"])
        hist = {"source": "x", "sites_rule": public.RULE, "sites": [], "events": [
            {**e, "texts": ["NAVAREA XI 1/30. 30-00N 120-00E\nSOURCE: X"]}]}
        self.assertTrue(any("SOURCE line" in p for p in public.problems(hist, None, ALLOW)))


class AllowList(unittest.TestCase):
    def read(self, doc):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "public_sites.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            return public.allowlist(p)

    def test_a_bad_entry_is_refused_and_reported(self):
        a = self.read({"publish": {"launch pad": ["LC-9A", "LC-9A", "YW-99", "Bohu Laser Facility",
                                                  "2 Feb 30_0202UTC_Testrocket-2"],
                                   "tracking ship": ["Somewhere"]},
                       "held": {"Bohu Laser Facility": "a laser facility"},
                       "notes": {"LC-9A": "hdg 090 at 12 kts", "Nowhere": "x"}})
        self.assertEqual(a["kinds"], {"LC-9A": "launch pad"})
        self.assertEqual(a["notes"], {})
        self.assertEqual(len(a["problems"]), 7)

    def test_names_match_whatever_the_spacing(self):
        a = self.read({"publish": {"launch pad": ["LC-2  (West Pad)"]}, "notes": {"LC-2 (West Pad)": " West  pad "}})
        sites, _ = public.sites([{"name": " LC-2 (West Pad) ", "lon": 1.0, "lat": 2.0}], a)
        self.assertEqual(sites, [{"name": "LC-2 (West Pad)", "lon": 1.0, "lat": 2.0, "kind": "launch pad",
                                  "note": "West pad"}])


class Check(unittest.TestCase):
    """problems() is what stops a deploy, so it is shown to fail on each thing the rule forbids."""
    GOOD = {"name": "LC-9A", "lon": 111.6085, "lat": 38.8491, "kind": "launch pad", "note": None}

    def errs(self, *sites, allow=ALLOW, pat=None):
        return public.problems({"sites": list(sites)}, pat, allow)

    def test_passes_a_clean_file(self):
        self.assertEqual(self.errs(self.GOOD), [])

    def test_fails_on_a_ship(self):
        errs = self.errs(self.GOOD, {"name": "YW-99", "lon": -150.5, "lat": -45.25, "kind": "launch pad", "note": None})
        self.assertEqual(len(errs), 1)
        self.assertNotIn("150.5", errs[0])

    def test_fails_on_a_note_with_a_speed_a_heading_or_a_coordinate(self):
        for note in ("14 Nov, making 12 kts", "hdg 090", "3851N 11136E", "seen 0846Z"):
            allow = {**ALLOW, "notes": {"LC-9A": note}}   # even if someone wrote it into the allow-list by hand
            errs = self.errs({**self.GOOD, "note": note}, allow=allow)
            self.assertTrue(errs, note)
            self.assertFalse(any(note in e for e in errs))   # the note's text is not repeated in a log

    def test_fails_on_a_note_that_is_not_on_the_allow_list(self):
        self.assertEqual(len(self.errs({**self.GOOD, "note": "Taiyuan"})), 1)

    def test_fails_on_an_unlisted_site_a_dated_name_a_wrong_kind_and_an_extra_field(self):
        self.assertTrue(self.errs({**self.GOOD, "name": "Brand New Marker"}))
        self.assertTrue(self.errs({**self.GOOD, "name": "2 Feb 30_0202UTC_Testrocket-2_Payload"}))
        self.assertTrue(self.errs({**self.GOOD, "kind": "drop zone"}))
        self.assertTrue(self.errs({k: v for k, v in self.GOOD.items() if k != "kind"}))
        self.assertTrue(self.errs({**self.GOOD, "heading": 90}))

    def test_fails_on_an_event_named_as_a_ship(self):
        for label in ("YW99", "Liao wang 9"):
            errs = public.problems({"sites": [self.GOOD], "events": [{"label": label, "points": [[-151.0, -46.0]]}]}, None, ALLOW)
            self.assertEqual(errs, ["1 event(s) named as a ship are in the file"])

    def test_fails_on_a_corridor_named_after_an_unpublished_site(self):
        self.assertTrue(self.errs(self.GOOD, pat={"corridors": [{"site": "YW-99"}]}))
        self.assertEqual(self.errs(self.GOOD, pat={"corridors": [{"site": "LC-9A"}, {"site": None}]}), [])


OLD = {"source": "x.kml", "imported_from": "the source map", "excluded_layers": [], "sites": [
    {"name": "LC-9A", "lon": 111.6085, "lat": 38.8491, "note": "TAIYUAN 3851N 11136E"},
    {"name": "YW-99", "lon": -150.5, "lat": -45.25, "note": "14 NOV 0846Z HDG 090 12 KTS"},
    {"name": "2 Feb 30_0202UTC_Testrocket-2_Payload", "lon": -141.0, "lat": -50.5, "note": None},
    {"name": "Brand New Marker", "lon": 10.0, "lat": 10.0, "note": "ADDED LATER"}],
    "events": [{"id": "hist:unknown-notams-liao-wang-9", "label": "Liao wang 9", "extra": None, "points": [[-152.0, -47.0]]}]}
OLD_PAT = {"corridors": [{"pad": [111.6085, 38.8491], "site": "LC-9A", "events": 3, "bands": []},
                         {"pad": [-150.5, -45.3], "site": "YW-99", "events": 3, "bands": []}],
           "recurring": [], "windows": {}, "firs": [], "hours": {}, "rules": {}}


class BuildGate(unittest.TestCase):
    """A history file written by older code is put through the gate again when the site is built."""

    def test_an_old_file_is_cut_down_to_the_rule(self):
        hist = public.history(OLD, ALLOW)
        self.assertEqual(hist["sites"], [{"name": "LC-9A", "lon": 111.6085, "lat": 38.8491, "kind": "launch pad",
                                          "note": None}])
        self.assertEqual(list(hist), ["source", "imported_from", "excluded_layers", "sites_rule", "sites", "events"])
        self.assertEqual(hist["events"], [])                                 # the ship in the events went too
        pat = public.patterns(OLD_PAT, hist)
        self.assertEqual([c["site"] for c in pat["corridors"]], ["LC-9A", None])
        self.assertTrue(public.problems(OLD, OLD_PAT, ALLOW))
        self.assertEqual(public.problems(hist, pat, ALLOW), [])

    def test_the_built_site_and_its_check(self):
        spec = importlib.util.spec_from_file_location("launch_cli", ROOT / "tools" / "launch.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = {
                "data/snapshot.json": {"generated_at": "2026-11-15T00:00:00Z", "lanes": {}, "tfr": [], "areas": [],
                                       "matches": [], "orbit": {"upcoming": []}},
                "history/history.json": OLD, "history/patterns.json": OLD_PAT,
                "history/ledger.json": {"launches": [], "closures": [], "sites": {}},
                "history/public_sites.json": {"publish": {"launch pad": ["LC-9A"]}, "notes": {}, "held": {}},
                "doctrine/sources.json": {"sources": []},
                "doctrine/kit/vocab/grading.json": {"admiralty": {"basis": "", "reliability": {}, "credibility": {}}},
                "doctrine/kit/geo/countries.json": {"source": "x", "countries": []},
                "site_src/index.html": "<!doctype html>",
            }
            for rel, body in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
            cli.build_site(root)
            built = (root / "site" / "data" / "history.json").read_text(encoding="utf-8")
            for word in ("YW", "KTS", "HDG", "TAIYUAN", "0846Z", "150.5", "Testrocket", "Brand New", "Liao", "152.0"):
                self.assertNotIn(word, built)
            self.assertEqual([s["name"] for s in json.loads(built)["sites"]], ["LC-9A"])
            self.assertNotIn("YW", (root / "site" / "data" / "patterns.json").read_text(encoding="utf-8"))
            with mock.patch.object(cli.registers, "check", return_value=[]), \
                    mock.patch.object(cli.registers, "ids", return_value={}):
                self.assertEqual(cli.check_all(root), [])
                # the same check refuses a built file that still holds a ship
                (root / "site" / "data" / "history.json").write_text(json.dumps(OLD), encoding="utf-8")
                errs = cli.check_all(root)
                self.assertTrue(errs and all(e.startswith("data/history.json: ") for e in errs))


class CommittedFiles(unittest.TestCase):
    """The committed history file is the published one (tools/launch.py build_site), so it is checked as it stands."""

    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "history" / "history.json").read_text(encoding="utf-8")
        cls.hist = json.loads(cls.text)
        cls.pat_text = (ROOT / "history" / "patterns.json").read_text(encoding="utf-8")
        cls.pat = json.loads(cls.pat_text)

    def test_the_allow_list_file_is_clean(self):
        allow = public.allowlist()
        self.assertEqual(allow["problems"], [])
        self.assertTrue(allow["kinds"])
        self.assertTrue(set(allow["kinds"].values()) <= set(public.KINDS))

    def test_no_site_is_named_as_a_ship(self):
        ships = [s for s in self.hist["sites"] if re.match(r"\s*YW", s["name"], re.I) or public.SHIP.search(s["name"])]
        self.assertEqual(len(ships), 0, f"{len(ships)} site(s) named as ships (YW-*) are in history/history.json")

    def test_no_event_is_named_as_a_ship(self):
        ships = sum(1 for e in self.hist["events"] if public.ship_named(e))
        self.assertEqual(ships, 0, f"{ships} event(s) named as ships are in history/history.json")

    def test_no_site_note_holds_a_speed_a_heading_or_a_coordinate(self):
        bad = [s["name"] for s in self.hist["sites"] if public.note_problems(s.get("note"))]
        self.assertEqual(bad, [], "site notes holding a speed, heading, coordinate or time of day")

    def test_the_file_passes_the_public_check(self):
        self.assertEqual(public.problems(self.hist, self.pat), [])

    def test_the_site_build_publishes_it_unchanged(self):
        def dump(obj):
            return json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        hist = public.history(self.hist)
        # compared as true or false, so a failure never prints a piece of the file
        self.assertTrue(dump(hist) == self.text, "the gate would change history/history.json: rebuild it with "
                                                 "`python tools/launch.py history`")
        self.assertTrue(dump(public.patterns(self.pat, hist)) == self.pat_text,
                        "the gate would change history/patterns.json: rebuild it with `python tools/launch.py history`")


if __name__ == "__main__":
    unittest.main()
