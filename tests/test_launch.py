"""Offline tests for Launch. Fixtures: real NOTAMs reposted on the NASASpaceflight forum (Oct-Nov 2026) and a small
KML in the shape of the source map. Run: python -m unittest discover -s tests"""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from launch import feed, history, live, notam, patterns  # noqa: E402
from synthetic_terms import TERMS  # noqa: E402
from tic_doctrine import contract, registers  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def notams():
    return {n["number"]: n for n in (notam.parse(p) for p in notam.split_many((FIX / "notams.txt").read_text(encoding="utf-8")))}


class Parser(unittest.TestCase):
    def setUp(self):
        self.n = notams()

    def test_all_fixtures_read(self):
        self.assertEqual(sorted(self.n), sorted(["B5731/26", "A5561/26", "E3971/26", "A0580/26", "A5673/26", "A1393/26",
                                                 "B9257/25", "B6436/25"]))

    def test_qline_and_times(self):
        n = self.n["B5731/26"]
        self.assertEqual(n["q"]["fir"], "RPHI")
        self.assertEqual(n["q"]["code"], "QWMLW")
        self.assertEqual(n["q"]["subject_text"], "missile, gun or rocket firing")
        self.assertEqual(n["q"]["radius_nm"], 23)
        self.assertEqual(n["start"], "2026-11-05T20:00:00Z")
        self.assertEqual(n["end"], "2026-11-09T23:00:00Z")
        self.assertEqual(n["schedule"], "2000-2300")

    def test_every_coordinate_form(self):
        forms = {k: n["shapes"][0].get("forms") for k, n in self.n.items()}
        self.assertEqual(forms["A5561/26"], ["prefix"])        # N330400E0984900
        self.assertEqual(forms["B5731/26"], ["suffix"])        # 091600N 1185700E
        self.assertEqual(forms["A1393/26"], ["suffix"])        # 2438S 15700W (DDMM)
        self.assertEqual(forms["B9257/25"], ["spaced"])        # 36 31 00 S 131 00 00 W
        self.assertEqual(forms["B6436/25"], ["suffix"])        # decimal seconds
        ring = self.n["A5561/26"]["shapes"][0]["ring"]
        self.assertAlmostEqual(ring[0][1], 33 + 4 / 60, places=5)
        self.assertAlmostEqual(ring[0][0], 98 + 49 / 60, places=5)
        self.assertEqual(ring[0], ring[-1])
        self.assertAlmostEqual(self.n["B6436/25"]["shapes"][0]["ring"][2][1], 7 + 21 / 60 + 21.62 / 3600, places=5)

    def test_dash_form(self):
        pts, _ = notam.coords("A. 59-42.60S 165-49.20E B. 58-39.87S 161-41.05W")
        self.assertEqual([p["form"] for p in pts], ["dash", "dash"])
        self.assertAlmostEqual(pts[0]["lat"], -(59 + 42.6 / 60), places=5)
        self.assertAlmostEqual(pts[1]["lon"], -(161 + 41.05 / 60), places=5)

    def test_malformed_token_rejected_not_guessed(self):
        n = self.n["A0580/26"]
        self.assertEqual([r["token"] for r in n["rejected"]], ["0055535N"])
        self.assertEqual(n["shapes"][0]["vertices"], 4)
        self.assertTrue(any("0055535N" in c for c in n["checks"]))

    def test_relayed(self):
        self.assertTrue(self.n["E3971/26"]["relayed"])   # Australia's FIR, for China
        self.assertEqual(self.n["E3971/26"]["issuing_state"], "AU")
        self.assertTrue(self.n["A1393/26"]["relayed"])   # Tahiti (CAAC spacecraft)
        self.assertFalse(self.n["A5561/26"]["relayed"])  # China's own FIR

    def test_two_locations(self):
        self.assertEqual(self.n["A5673/26"]["locations"], ["ZLHW", "ZPKM"])

    def test_qline_circle_only_without_text_shape(self):
        n = notam.parse("A0001/26 NOTAMN Q)ZBPE/QRDCA/IV/BO/W/000/999/3553N11209E012 A)ZBPE B)2609240838 "
                        "C)2609240904 E) DANGER AREA ACTIVATED. F)SFC G)UNL")
        self.assertEqual(len(n["shapes"]), 1)
        self.assertTrue(n["shapes"][0]["derived"].startswith("Q-line circle"))

    def test_text_circle(self):
        n = notam.parse("A0002/26 NOTAMN Q)KZMA/QRTCA/IV/BO/W/000/999/2830N08036W010 A)KZMA B)2611140000 "
                        "C)2611140100 E) AIRSPACE WI A RADIUS OF 10NM CENTRED ON 283000N0803600W. F)SFC G)UNL")
        self.assertEqual(n["shapes"][0]["kind"], "circle")
        self.assertEqual(n["shapes"][0]["radius_nm"], 10)

    def test_2400_end_of_day(self):
        self.assertEqual(notam.stamp("2611302400")[0], "2026-12-01T00:00:00Z")


KML = """<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>map</name>
<Folder><name>Launch Sites</name>
 <Placemark><name>LC-9A</name><description>TAIYUAN</description><Point><coordinates>111.6085,38.8491,0</coordinates></Point></Placemark>
 <Placemark><name>Zhuque 2E ZQDETECT Centroid 9 Jun 26</name><description>ZQDETECT HAVE SHARED</description><Point><coordinates>100.2,40.9,0</coordinates></Point></Placemark>
</Folder>
<Folder><name>2026 - Previous Chinese Launches</name>
 <Placemark><name>24 Sep 26_ 0846 UTC_LM-6A_ Yaogan-40 04A-C</name><description>A4754/26 NOTAMN&lt;br&gt;Q)ZBPE/QRDCA/IV/BO/W/000/999/3553N11209E012&lt;br&gt;A)ZBPE B)2609240838 C)2609240904&lt;br&gt;E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:&lt;br&gt;N360200E1120100-N360400E1121500-N354400E1121800-N354200E1120400&lt;br&gt;BACK TO START.&lt;br&gt;F)SFC G)UNL&lt;br&gt;https://forum.nasaspaceflight.com/index.php?topic=57867.msg1</description>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>112.0166667,36.0333333,0 112.25,36.0666667,0 112.3,35.7333333,0 112.0666667,35.7,0 112.0166667,36.0333333,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
 <Placemark><name>24 Sep 26_ 0846 UTC_LM-6A_ Yaogan-40 04A-C</name><description>ZQDETECT CONFIRMS LAUNCH DETECTED</description>
  <LineString><coordinates>111.6085,38.8491,0 112.16,35.88,0</coordinates></LineString></Placemark>
 <Placemark><name>Dec 25_2326 UTC_LM-8A_Xingwang</name><description>B6436/25 NOTAMN&lt;br&gt;Q) RPHI/QWMLW/IV/BO /W /000/999/0738N12039E045&lt;br&gt;A) RPHI B) 2512252319 C) 2512252354&lt;br&gt;E) EST FALL AREA WI: 075500N 1195800E - 082100N 1203200E - 072121N 1211923E - 075500N 1195800E&lt;br&gt;F) SFC G) UNL</description>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>119.9667,7.9167,0 120.5333,8.35,0 121.3233,7.3559,0 119.9667,7.9167,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Folder>
<Folder><name>Previous Exercise NOTAMs</name>
 <Placemark><name>DRILLX Astral Guardian</name><description>DRILLX scenario text</description><Point><coordinates>40,62,0</coordinates></Point></Placemark>
</Folder></Document></kml>"""


class History(unittest.TestCase):
    def setUp(self):
        history.use_terms(TERMS)
        self.doc = history.load(KML)
        self.ev = {e["label"]: e for e in self.doc["events"]}

    def test_names(self):
        n = history.parse_name("Canceled - 22 Apr 25_~1547 UTC_LM-8 Y5_Qianfan Jigui 04A-R")
        self.assertEqual((n["day"], n["month"], n["year"], n["hhmm"], n["vehicle"]), (22, 4, 2025, "1547", "LM-8 Y5"))
        self.assertTrue(n["cancelled"])
        n = history.parse_name("NAVWARN 19-30 Aug 26_1800-2100 UTC_Angara-1.2_Payload Unk")
        self.assertEqual((n["day"], n["day_end"], n["hhmm_end"], n["vehicle"]), (19, 30, "2100", "Angara-1.2"))

    def test_event_grouped_with_path_and_check(self):
        e = self.ev["24 Sep 26_ 0846 UTC_LM-6A_ Yaogan-40 04A-C"]
        self.assertEqual(e["time"], "2026-09-24T08:46:00Z")
        self.assertEqual(e["actor"], "CN")
        self.assertEqual(len(e["areas"]), 1)
        self.assertEqual(e["pad"], [111.6085, 38.8491])
        self.assertTrue(e["areas"][0]["text_check"]["agrees"])
        self.assertAlmostEqual(e["areas"][0]["inclination_est"], 82, delta=3)

    def test_links_lose_session_parameters(self):
        s = history.strip_session
        self.assertEqual(s("https://forum.example/index.php?PHPSESSID=ab12&topic=5.msg1"), "https://forum.example/index.php?topic=5.msg1")
        self.assertEqual(s("https://x.example/a?topic=1&utm_source=y#m5"), "https://x.example/a?topic=1#m5")
        self.assertEqual(s("https://x.example/a;jsessionid=Q?x=1"), "https://x.example/a?x=1")
        self.assertEqual(s("https://x.example/news/a-b;"), "https://x.example/news/a-b;")  # nothing to strip: unchanged

    def test_day_from_notam_window(self):
        e = self.ev["Dec 25_2326 UTC_LM-8A_Xingwang"]
        self.assertEqual((e["time"], e["time_basis"]), ("2025-12-25T23:26:00Z", "from notam"))

    def test_non_public_notes_withheld(self):
        blob = json.dumps(self.doc)
        for word in ("ZQDETECT", "QQVIEW", "DRILLX"):
            self.assertNotIn(word, blob)
        self.assertEqual(self.ev["24 Sep 26_ 0846 UTC_LM-6A_ Yaogan-40 04A-C"]["withheld_notes"], 1)
        self.assertEqual([s["name"] for s in self.doc["sites"]], ["LC-9A"])


class Matching(unittest.TestCase):
    def test_levels(self):
        pad = {"lat": 38.8491, "lon": 111.6085}
        area = {"key": "x", "ring": [[112.0, 36.0], [112.3, 36.0], [112.3, 35.7], [112.0, 35.7], [112.0, 36.0]],
                "windows": [{"start": "2026-11-20T08:30:00Z", "end": "2026-11-20T09:10:00Z"}]}
        corr = [{"pad": [111.6085, 38.8491], "bands": [{"from": 170, "to": 175, "downrange_nm": [150, 200]}]}]
        up = [{"id": "u1", "name": "LM-6A", "net": "2026-11-20T08:46:00Z", **pad}]
        m = live.match(up, [area], corr, [])
        self.assertEqual(m[0]["level"], "time and place")
        far = {**area, "ring": [[-150, -40], [-149, -40], [-149, -41], [-150, -40]]}
        self.assertEqual(live.match(up, [far], corr, [])[0]["level"], "time")
        long_window = {**area, "windows": [{"start": "2026-11-20T00:00:00Z", "end": "2026-11-20T12:00:00Z"}]}
        self.assertEqual(live.match(up, [long_window], corr, []), [])
        gcat = [{"launch_tag": "2026-260", "time": "2026-11-20T08:47:00Z", "vehicle": "CZ-6A",
                 "site": {"lat": 38.85, "lon": 111.61}}]
        self.assertEqual(live.match(up, [area], corr, gcat)[0]["level"], "grouped")

    def test_tfr_space_ops_only_and_stale_shapes_dropped(self):
        lst = json.dumps([{"notam_id": "6/7131", "type": "SPACE OPERATIONS", "facility": "ZHU", "state": "TX",
                           "description": "STARBASE", "creation_date": "11/12/2026"},
                          {"notam_id": "6/7529", "type": "SECURITY"}]).encode()
        sq = [[-97.2, 26.0], [-97.1, 26.0], [-97.1, 26.1], [-97.2, 26.0]]
        shp = json.dumps({"features": [
            {"properties": {"NOTAM_KEY": "6/7131-1-FDC-F"}, "geometry": {"type": "Polygon", "coordinates": [sq]}},
            {"properties": {"NOTAM_KEY": "5/6914-1-FDC-F"}, "geometry": {"type": "Polygon", "coordinates": [sq]}},
            {"properties": {"NOTAM_KEY": "6/7529-1-FDC-F"}, "geometry": {"type": "Polygon", "coordinates": [sq]}}]}).encode()
        t = live.tfr_space_ops(lst, shp)
        self.assertEqual([x["id"] for x in t], ["6/7131"])

    # FDC 6/7113 as the FAA's XML gave it on 15 Nov 2026 (cut down): times in UTC although codeTimeZone says EST.
    XNOTAM_7113 = b"""<XNOTAM-Update><Group><Add><Not>
      <dateIssued>2026-11-11T14:02:00</dateIssued><dateEffective>2026-11-15T17:01:00</dateEffective>
      <dateExpire>2026-11-15T18:50:00</dateExpire><codeTimeZone>EST</codeTimeZone>
      <txtLocalName>261115 ULA Vulcan KV-01 (A1174)</txtLocalName>
      <txtDescrTraditional>!FDC 6/7113 ZJX FL..AIRSPACE CAPE CANAVERAL, FL..TEMPORARY FLIGHT RESTRICTIONS. ...
      EFFECTIVE 2611151701 UTC (1201 LOCAL 11/15/26) UNTIL 2611151850 UTC (1350 LOCAL 11/15/26). ...
      2611151701-2611151850</txtDescrTraditional>
    </Not></Add></Group></XNOTAM-Update>"""

    def test_tfr_windows_are_utc_and_match_the_launch(self):
        d = live.tfr_detail(self.XNOTAM_7113)
        self.assertEqual(d["windows"], [{"start": "2026-11-15T17:01:00Z", "end": "2026-11-15T18:50:00Z"}])
        self.assertEqual(d["window_basis"], "notam-text")
        self.assertEqual(d["time_zone"], "EST")  # kept as written
        sq = [[-80.4, 28.9], [-80.2, 28.9], [-80.2, 29.1], [-80.4, 28.9]]
        areas = live.tfr_areas([{"id": "6/7113", "description": "Cape Canaveral", "rings": [sq], "detail": d}], {})
        self.assertEqual(areas[0]["windows"], d["windows"])
        up = [{"id": "u1", "name": "Vulcan VC6L | Amazon Leo (LV-01)", "net": "2026-11-15T17:11:30Z",
               "lat": 28.583, "lon": -80.583}]
        m = live.match(up, areas, [], [])
        self.assertEqual([(x["area"], x["window"]) for x in m],
                         [("FDC 6/7113", ["2026-11-15T17:01:00Z", "2026-11-15T18:50:00Z"])])
        # read as EST (five hours later) the launch would have fallen outside the window
        self.assertEqual(live.match([{**up[0], "net": "2026-11-15T12:11:30Z"}], areas, [], []), [])

    def test_tfr_windows_fall_back_to_xml_dates_read_as_utc(self):
        w, basis = live.tfr_windows("NO TIMES IN THIS TEXT.", [("2026-11-16T15:00:00", "2026-11-16T16:30:00"),
                                                                ("2026-11-16T15:00:00", "2026-11-16T16:30:00")])
        self.assertEqual((w, basis), ([{"start": "2026-11-16T15:00:00Z", "end": "2026-11-16T16:30:00Z"}], "xml-dates"))
        self.assertEqual(live.tfr_windows(None, []), ([], None))
        self.assertEqual(live.tfr_windows("", [("bad", "2026-11-16T16:30:00")]), ([], None))
        # two periods in one text, each kept
        w, _ = live.tfr_windows("EFFECTIVE 2611161500 UTC UNTIL 2611161700 UTC AND 2611171500 UTC UNTIL "
                                "2611171700 UTC.", [])
        self.assertEqual([x["start"] for x in w], ["2026-11-16T15:00:00Z", "2026-11-17T15:00:00Z"])

    def test_tfr_summary_gives_utc_window_not_the_xml_zone(self):
        sq = [[-80.4, 28.9], [-80.2, 28.9], [-80.2, 29.1], [-80.4, 28.9]]
        snap = {"generated_at": "2026-11-15T06:00:00Z", "lanes": {"tfr": {"fetched_at": "2026-11-15T06:00:00Z"},
                                                                   "orbit": {"fetched_at": "2026-11-15T06:00:00Z"}},
                "tfr": [{"id": "6/7113", "facility": "ZJX", "state": "FL", "description": "Cape Canaveral",
                         "created": "11/11/2026", "rings": [sq], "detail": live.tfr_detail(self.XNOTAM_7113)}],
                "areas": [], "matches": []}
        s = feed.build_feed(snap)["features"][0]["properties"]["summary"]
        self.assertIn("In force 2026-11-15T17:01:00Z to 2026-11-15T18:50:00Z (UTC).", s)
        self.assertNotIn("time zone", s)


class FeedAndRegisters(unittest.TestCase):
    def test_registers(self):
        self.assertEqual(registers.check(ROOT / "doctrine"), [])

    def test_feed_items_pass_contract(self):
        sq = [[-97.2, 26.0], [-97.1, 26.0], [-97.1, 26.1], [-97.2, 26.0]]
        snap = {"generated_at": "2026-11-14T02:00:00Z", "lanes": {"tfr": {"fetched_at": "2026-11-14T02:00:00Z"},
                                                                   "orbit": {"fetched_at": "2026-11-14T02:00:00Z"}},
                "tfr": [{"id": "6/7131", "facility": "ZHU", "state": "TX", "description": "STARBASE", "created": "11/12/2026",
                         "rings": [sq]}],
                "areas": [{"key": "hydropac-1-26", "ring": sq}],
                "matches": [{"launch": "u1", "launch_name": "Starship", "net": "2026-11-14T12:00:00Z", "area": "hydropac-1-26",
                             "window": ["2026-11-14T11:30:00Z", "2026-11-14T13:00:00Z"], "level": "time and place",
                             "azimuth": 95.0, "distance_nm": 300, "place_basis": "azimuth band", "inclination_est": 26.0,
                             "grouped_with": None}]}
        doc = feed.build_feed(snap)
        self.assertEqual(len(doc["features"]), 2)
        self.assertEqual(doc["features"][0]["properties"]["tier"], "routine")  # no detail read: issue time unknown
        snap["tfr"] += [{"id": "6/7549", "facility": "ZJX", "state": "FL", "description": "Cape Canaveral",
                         "created": "11/14/2026", "rings": [sq], "detail": {"issued_utc": "2026-11-14T00:00:00Z"}},
                        {"id": "6/7113", "facility": "ZJX", "state": "FL", "description": "Cape Canaveral",
                         "created": "11/10/2026", "rings": [sq], "detail": {"issued_utc": "2026-11-10T00:00:00Z"}}]
        doc = feed.build_feed(snap)
        tiers = {f["properties"]["id"]: f["properties"]["tier"] for f in doc["features"]}
        self.assertEqual(tiers["launch:tfr:6/7549"], "anomaly")  # issued 2 h before the run
        self.assertEqual(tiers["launch:tfr:6/7113"], "routine")  # issued 98 h before
        regs = registers.ids(ROOT / "doctrine")
        for f in doc["features"]:
            errs = [m for s, sev, m in contract.check(f, regs) if sev == "error"]
            self.assertEqual(errs, [], f["properties"]["id"])


class Patterns(unittest.TestCase):
    def test_recurring_zone(self):
        ring = [[100, 40], [100.1, 40], [100.1, 40.1], [100, 40]]
        evs = [{"id": f"e{i}", "label": f"e{i}", "time": f"2026-0{i + 1}-01T00:00:00Z", "actor": "CN", "kind": "launch",
                "layer": "x", "time_basis": "time", "pad": None, "notams": [],
                "areas": [{"ring": ring, "centroid": [100.05, 40.03]}]} for i in range(3)]
        z = patterns.recurring(evs)
        self.assertEqual(len(z), 1)
        self.assertEqual(z[0]["first"]["event"], "e0")


if __name__ == "__main__":
    unittest.main()
