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

    def test_notam_year_corrects_a_mistyped_chart_year(self):
        nm = history.parse_name("29 Dec 26_~0613 UTC_Jielong-3_PRCS-EO?")
        kept = [{"start": "2025-12-29T06:07:00Z", "end": "2025-12-29T07:08:00Z"}]
        self.assertEqual(history._when(nm, kept), ("2025-12-29T06:13:00Z", "time"))
        self.assertEqual(history._when(nm, []), ("2026-12-29T06:13:00Z", "time"))  # no NOTAM: the name stands
        other_day = [{"start": "2025-12-20T06:07:00Z", "end": "2025-12-20T07:08:00Z"}]
        self.assertEqual(history._when(nm, other_day)[0], "2026-12-29T06:13:00Z")  # not the same day: the name stands

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

    def test_six_hour_windows(self):
        """Ariane 6 VA271's own areas ran 4.9 to 5.7 hours (22 Nov 2026) and matched nothing at four."""
        up = [{"id": "u1", "name": "Ariane 64 | Amazon Leo (LE-04)", "net": "2026-11-23T11:09:00Z", "lat": 5.24, "lon": -52.77}]
        ring = [[-47.2, 14.0], [-45.6, 12.9], [-48.0, 10.0], [-47.2, 14.0]]
        five7 = {"key": "A1864/26", "ring": ring, "windows": [{"start": "2026-11-23T06:27:00Z", "end": "2026-11-23T12:08:00Z"}]}
        self.assertEqual(len(live.match(up, [five7], [], [])), 1)
        seven = {**five7, "windows": [{"start": "2026-11-23T05:00:00Z", "end": "2026-11-23T12:08:00Z"}]}
        self.assertEqual(live.match(up, [seven], [], []), [])

    def test_named(self):
        """A mission designator in the text names the launch (hyphens ignored) and lets a longer window match; the
        vehicle's name counts only where the place fits too."""
        self.assertEqual(live.mission_words({"name": "Falcon 9 Block 5 | NROL-136", "mission": "NROL-136"}), ["NROL136"])
        self.assertEqual(live.mission_words({"name": "Starship | Starlink Group 31-2 (Starship Flight 15)"}), [])
        self.assertEqual(live.vehicle_pattern("Ariane 64 Block 2").pattern, r"\bARIANE[\s-]*6")
        self.assertEqual(live.vehicle_pattern("Soyuz 2.1b/Fregat-M").pattern, r"\bSOYUZ[\s-]*2")
        self.assertIsNone(live.vehicle_pattern("H3-22S"))
        up = [{"id": "u1", "name": "Falcon 9 Block 5 | NROL-136", "mission": "NROL-136", "vehicle": "Falcon 9 Block 5",
               "net": "2026-11-22T16:00:00Z", "lat": 34.63, "lon": -120.61}]
        tahiti = {"key": "A1508/26", "ring": [[-121.9, -30.0], [-122.7, -28.0], [-120.7, -27.2], [-121.9, -30.0]],
                  "windows": [{"start": "2026-11-22T14:00:00Z", "end": "2026-11-27T14:08:00Z"}],
                  "text": "TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN OF SPACEX\nNROL-136 IN TAHITI FIR"}
        m = live.match(up, [tahiti], [], [])
        self.assertEqual((m[0]["named"], m[0]["named_by"], m[0]["level"]), ("NROL-136", "mission", "time"))
        self.assertEqual(live.match(up, [{**tahiti, "text": "SPACE DEBRIS"}], [], []), [])   # 5 days, unnamed
        near = {"key": "x", "ring": [[-121.0, 34.0], [-120.8, 34.0], [-120.8, 33.8], [-121.0, 34.0]],
                "windows": [{"start": "2026-11-22T15:00:00Z", "end": "2026-11-22T17:00:00Z"}], "text": "FALCON 9 LAUNCH"}
        self.assertEqual(live.match(up, [near], [], [])[0]["named_by"], "vehicle")
        far = {**near, "ring": [[150, -40], [151, -40], [151, -41], [150, -40]]}
        self.assertIsNone(live.match(up, [far], [], [])[0]["named"])

    def test_cordon_launch_warnings(self):
        """NGA warnings come from Cordon's feed (decided 17 Nov 2026): launch hazards kept, missile firings left out,
        Orbit's keys and NGA's numbers kept, letters from the text when areas have no windows of their own."""
        win = [{"start": "2026-11-20T10:00:00Z", "end": "2026-11-20T13:00:00Z"}]
        sq = [[120.0, 10.0], [120.5, 10.0], [120.5, 10.5], [120.0, 10.0]]
        doc = {"generated_at": "2026-11-17T18:15:56Z", "health": {"nga-navwarnings": {"state": "fresh"}}, "features": [
            {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[sq], [[[c[0] + 2, c[1]] for c in sq]]]},
             "properties": {"id": "cordon:navwarn:P-3352-2026", "data_as_of": "2026-11-15T12:00:00Z",
                            "valid_until": "2026-11-20T17:00:00Z",
                            "measures": {"category": "launch", "sea": "South China Sea", "place": "Philippines",
                                         "hazard": "space debris", "windows": win, "window_mode": "single",
                                         "cancels": [], "text": "1. HAZARDOUS OPERATIONS, SPACE DEBRIS\n"
                                         "   201000Z TO 201600Z NOV IN AREAS BOUND BY\n   A. 10-00N 120-00E.\n"
                                         "   B. 10-00N 122-00E.",
                                         "rebroadcasts": [{"id": "cordon:navwarn:12-800-2026", "number": "NAVAREA XII 800/2026",
                                                           "issued": "2026-11-15T13:00:00Z"}]}}},
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [sq]},
             "properties": {"id": "cordon:navwarn:A-237-2026", "measures": {"category": "launch", "hazard": None}}},
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [sq]},
             "properties": {"id": "cordon:navwarn:4-5-2026", "measures": {"category": "military"}}}]}
        got = live.cordon_read(json.dumps(doc).encode())
        self.assertEqual((got["nga_state"], got["missile_firings_left_out"]), ("fresh", 1))
        self.assertEqual([(a["key"], a["label"]) for a in got["areas"]],
                         [("hydropac-3352-26", "A"), ("hydropac-3352-26", "B")])
        a = got["areas"][0]
        self.assertEqual((a["source"], a["hazard"], a["windows"], a["regions"], a["expires"]),
                         ("cordon-navwarn", "space debris", win, ["SOUTH CHINA SEA", "PHILIPPINES"], "2026-11-20T17:00:00Z"))
        self.assertEqual([b["id"] for b in a["broadcasts"]], ["HYDROPAC 3352/26", "NAVAREA XII 800/26"])
        self.assertEqual(a["ring"][0], a["ring"][-1])
        up = [{"id": "u1", "name": "LM-2C", "net": "2026-11-20T10:30:00Z", "lat": 19.6, "lon": 110.95}]
        m = live.match(up, got["areas"], [], [])
        self.assertEqual({r["area"] for r in m}, {"hydropac-3352-26"})

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

    # FDC 6/8694 as the FAA's XML gave it on 20 Nov 2026 (cut down, telephone numbers removed).
    XNOTAM_8694 = b"""<XNOTAM-Update><Group><Add><Not>
      <dateIssued>2026-11-18T15:00:00</dateIssued><dateEffective>2026-11-21T17:00:00</dateEffective>
      <dateExpire>2026-11-21T21:00:00</dateExpire><codeTimeZone>MST</codeTimeZone>
      <txtDescrTraditional>!FDC 6/8694 ZLC ID..AIRSPACE 94 ZLC AIRSPACE BOISE, ID..TEMPORARY FLIGHT RESTRICTION.
      PURSUANT TO 14 CFR SECTION 91.143, SPACE OPS AREA, ACFT OPS ARE PROHIBITED WI AN AREA DEFINED AS 2NM RADIUS OF
      431415N1161927W (BOI180020.0) SFC-FL440 EFFECTIVE 2611211700 UTC UNTIL 2611212100 UTC. TO PROVIDE A SAFE
      ENVIRONMENT FOR ROCKET LAUNCH ACTIVITY TRIPOLI IDAHO ROCKETRY IS THE POINT OF CONTACT. 2611211700-2611212100
      </txtDescrTraditional>
    </Not></Add></Group></XNOTAM-Update>"""

    def test_amateur_rocketry_tfr_is_labelled_and_kept(self):
        d = live.tfr_detail(self.XNOTAM_8694)
        self.assertEqual(d["activity"], live.AMATEUR_LABEL)
        self.assertEqual(d["windows"], [{"start": "2026-11-21T17:00:00Z", "end": "2026-11-21T21:00:00Z"}])
        self.assertNotIn("TRIPOLI", json.dumps(d))  # the label only; the notice's text and contacts are not kept
        self.assertIsNone(live.tfr_detail(self.XNOTAM_7113)["activity"])  # a Cape launch TFR carries no label
        sq = [[-116.4, 43.2], [-116.3, 43.2], [-116.3, 43.3], [-116.4, 43.2]]
        item = feed._tfr_item({"id": "6/8694", "facility": "ZLC", "state": "ID", "description": "Boise, ID",
                               "created": "11/18/2026", "rings": [sq], "detail": d},
                              "2026-11-20T00:00:00Z", "2026-11-20T00:00:00Z")["properties"]
        self.assertIn(live.AMATEUR_LABEL, item["title"])
        self.assertIn("not an orbital launch closure", item["summary"])
        self.assertEqual(item["measures"]["activity"], live.AMATEUR_LABEL)

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

    def test_feed_folds_a_notices_lettered_areas(self):
        """24 Nov 2026: NAVAREA XII 836/26's parts A, B, C each matched USSF-380 and gave three items with one id."""
        sq = [[-121.0, 33.0], [-120.9, 33.0], [-120.9, 33.1], [-121.0, 33.0]]
        areas = [{"key": "navarea-xii-836-26", "label": x, "source": "cordon-navwarn",
                  "ring": [[c[0], c[1] - i] for c in sq]} for i, x in enumerate("ABC")]
        m = {"launch": "u1", "launch_name": "Falcon 9 | USSF-380", "net": "2026-11-29T04:39:00Z", "area": "navarea-xii-836-26",
             "window": ["2026-11-29T04:39:00Z", "2026-11-29T09:22:00Z"], "azimuth": 154.0, "place_basis": "b",
             "inclination_est": 70.0, "grouped_with": None}
        snap = {"generated_at": "2026-11-25T00:00:00Z", "lanes": {}, "areas": areas,
                "matches": [{**m, "area_i": 0, "level": "time and place", "distance_nm": 287},
                            {**m, "area_i": 1, "level": "time and place", "distance_nm": 65},
                            {**m, "area_i": 2, "level": "time", "distance_nm": 360}]}
        fs = feed.build_feed(snap)["features"]
        self.assertEqual(len(fs), 1)
        p = fs[0]["properties"]
        self.assertEqual((fs[0]["geometry"]["type"], len(fs[0]["geometry"]["coordinates"])), ("MultiPolygon", 2))
        self.assertEqual(p["measures"]["parts"], ["A", "B"])   # the two that fit in time and place
        self.assertIn("(areas A, B)", p["title"])
        self.assertIn("NOTAM Management Service", feed.build_feed(snap)["attribution"])

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



class PlaceOnThinPads(unittest.TestCase):
    """Most pads have few charted events (24 Nov 2026: 69 of 77 under 10), so their bands alone missed NG-25's
    and USSF-380's own areas. Below MIN_BAND_EVENTS an area on a flown orbit's azimuth fits too."""
    CAPE = {"lat": 28.562, "lon": -80.577}
    WIN = [{"start": "2026-11-29T15:40:00Z", "end": "2026-11-29T16:43:00Z"}]

    def area(self, az, nm):
        import math
        lat1, lon1, d = math.radians(self.CAPE["lat"]), math.radians(self.CAPE["lon"]), nm / 3440.065
        b = math.radians(az)
        lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b))
        lon2 = lon1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2))
        x, y = math.degrees(lon2), math.degrees(lat2)
        return {"key": f"a{az}-{nm}", "ring": [[x - .05, y - .05], [x + .05, y - .05], [x + .05, y + .05], [x - .05, y + .05],
                                              [x - .05, y - .05]], "windows": self.WIN}

    def corr(self, events):
        return [{"pad": [-80.604, 28.608], "events": events, "bands": [{"from": 110, "to": 115, "downrange_nm": [12, 12]}]}]

    def run_it(self, areas, events=2, flown=None):
        up = [{"id": "u1", "name": "Falcon 9 | NG-25", "net": "2026-11-29T15:47:00Z", **self.CAPE}]
        return live.match(up, areas, self.corr(events), [], flown)

    ISS = [{"lat": 28.56, "lon": -80.58, "inc": 51.64}] * 5

    def test_launch_azimuths(self):
        a = live.launch_azimuths(28.5, 51.6)
        self.assertAlmostEqual(a[0], 45.0, delta=0.5)
        self.assertAlmostEqual(a[1], 135.0, delta=0.5)
        self.assertEqual(live.launch_azimuths(28.5, 20.0), [90.0])
        self.assertEqual(live.launch_azimuths(34.6, 160.0), [270.0])

    def test_thin_pad_area_on_a_flown_azimuth_fits(self):
        m = self.run_it([self.area(46, 251)], flown=self.ISS)
        self.assertEqual(m[0]["level"], "time and place")
        self.assertIn("51.5-degree orbit flown from this site", m[0]["place_basis"])
        self.assertEqual(self.run_it([self.area(46, 251)])[0]["level"], "time")        # no GCAT launches read
        self.assertEqual(self.run_it([self.area(80, 251)], flown=self.ISS)[0]["level"], "time")   # off the azimuth

    def test_rich_pad_bands_still_rule(self):
        self.assertEqual(self.run_it([self.area(46, 251)], events=20, flown=self.ISS)[0]["level"], "time")

    def test_one_off_inclination_does_not_count(self):
        self.assertEqual(self.run_it([self.area(46, 251)], flown=self.ISS[:4])[0]["level"], "time")

    def test_area_near_the_pad_fits_whatever_the_bands(self):
        m = self.run_it([self.area(58, 11)], events=20)
        self.assertEqual((m[0]["level"], m[0]["place_basis"]), ("time and place", "within 30 NM of the pad"))

    def test_far_area_stays_time(self):
        self.assertEqual(self.run_it([self.area(233, 5900)], flown=self.ISS)[0]["level"], "time")



class GroundTrack(unittest.TestCase):
    """A far area under the launch's own ground track, at the time the track passes, is time and place (NG-25's
    South Pacific disposal areas, 24 Nov 2026, about 68 min after NET)."""
    CAPE = {"lat": 28.562, "lon": -80.577}
    NET = "2026-11-29T15:47:00Z"
    ISS = [{"lat": 28.56, "lon": -80.58, "inc": 51.64}] * 5
    CORR = [{"pad": [-80.604, 28.608], "events": 2, "bands": [{"from": 110, "to": 115, "downrange_nm": [12, 12]}]}]

    @staticmethod
    def box(lat, lon, w, start, end, key):
        return {"key": key, "ring": [[lon - .3, lat - .3], [lon + .3, lat - .3], [lon + .3, lat + .3], [lon - .3, lat + .3],
                                     [lon - .3, lat - .3]], "windows": [{"start": start, "end": end}]}

    def near(self):   # 251 NM out on the ISS azimuth: a place match that sets the orbit
        return self.box(31.5, -77.0, .3, "2026-11-29T15:40:00Z", "2026-11-29T16:43:00Z", "near")

    def point_at(self, minutes):
        t = live.ground_track(self.CAPE["lat"], self.CAPE["lon"], 51.5, True, minutes, minutes)
        return t[0][1], t[0][2]

    def run_it(self, areas, flown=ISS):
        up = [{"id": "u1", "name": "Falcon 9 | NG-25", "net": self.NET, **self.CAPE}]
        return {r["area"]: r for r in live.match(up, areas, self.CORR, [], flown)}

    def test_track_starts_at_the_pad_and_reaches_its_inclination(self):
        t = live.ground_track(28.5, -80.6, 51.6, True, 0, 30, step_s=60)
        self.assertAlmostEqual(t[0][1], 28.5, places=3)
        self.assertAlmostEqual(t[0][2], -80.6, places=3)
        self.assertAlmostEqual(max(x[1] for x in t), 51.6, delta=0.5)

    def test_track_orbits_take_a_flown_inclination_on_the_bearing(self):
        self.assertEqual(live.track_orbits(28.56, 46.0, [51.5, 28.5]), [(51.5, True)])
        guess = live.track_orbits(28.56, 46.0, [])
        self.assertEqual(len(guess), 5)
        self.assertTrue(all(north for _, north in guess))

    def test_far_area_under_the_track_in_its_window(self):
        la, lo = self.point_at(68)
        rows = self.run_it([self.near(), self.box(la, lo, .3, "2026-11-29T16:46:00Z", "2026-11-29T17:37:00Z", "far")])
        self.assertEqual(rows["near"]["level"], "time and place")
        self.assertEqual(rows["far"]["level"], "time and place")
        self.assertEqual(rows["far"]["track"]["inc"], 51.5)
        self.assertIn("ground track", rows["far"]["place_basis"])

    def test_far_area_off_the_track_or_out_of_time_stays_time(self):
        la, lo = self.point_at(68)
        off = self.box(la + 10, lo, .3, "2026-11-29T16:46:00Z", "2026-11-29T17:37:00Z", "off")
        late = self.box(la, lo, .3, "2026-11-29T19:00:00Z", "2026-11-29T20:30:00Z", "late")
        rows = self.run_it([self.near(), off])
        self.assertEqual(rows["off"]["level"], "time")
        self.assertIsNone(rows["off"]["track"])
        up = [{"id": "u1", "name": "Falcon 9 | NG-25", "net": "2026-11-29T18:30:00Z", **self.CAPE}]
        self.assertEqual(live.match(up, [late], self.CORR, [], self.ISS)[0]["level"], "time")   # no near area: no orbit

    def test_without_a_place_match_there_is_no_direction(self):
        la, lo = self.point_at(68)
        rows = self.run_it([self.box(la, lo, .3, "2026-11-29T16:46:00Z", "2026-11-29T17:37:00Z", "far")])
        self.assertEqual(rows["far"]["level"], "time")


if __name__ == "__main__":
    unittest.main()
