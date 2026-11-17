"""Offline tests for the History tab's launch list (catalog.py, programs.py, gcat.py).
Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import catalog, gcat  # noqa: E402
from launch import programs as P  # noqa: E402

NOW = "2026-11-15T00:00:00Z"
SITES = {
    "WEN": {"name": "Wenchang", "gcat_name": "Wenchang", "lat": 19.6142, "lon": 110.9511, "country": "CN"},
    "VOST": {"name": "Vostochny", "gcat_name": "Vostochniy", "lat": 51.7, "lon": 128.0, "country": "RU"},
    "CC": {"name": "Cape Canaveral", "gcat_name": "Canaveral", "lat": 28.46, "lon": -80.54, "country": "US"},
    "KSC": {"name": "Kennedy (KSC)", "gcat_name": "Kennedy", "lat": 28.6083, "lon": -80.6041, "country": "US"},
    "VSFBS": {"name": "Vandenberg", "gcat_name": "Vandenberg", "lat": 34.63, "lon": -120.61, "country": "US"},
}


def gcat_rec(tag, time, vehicle, mission, site_code, category="Sat LEO O", inc=None, country="CN", names=None):
    s = SITES[site_code]
    return {"id": "gcat:" + tag, "source": "gcat", "tag": tag, "time": time, "date": time[:10], "vehicle_raw": vehicle,
            "flight": mission, "mission": mission, "agency": "X", "country": country, "outcome": "success",
            "kind": "orbital", "category": category, "site_code": site_code,
            "site": {"name": s["gcat_name"], "lat": s["lat"], "lon": s["lon"], "country": s["country"]},
            "pad_name": "", "payloads": {"count": 1, "names": names or [mission], "more": 0, "owners": [], "states": [],
                                         "op_orbits": []}, "inc": inc, "updated": "2026-11-01T00:00:00Z"}


def chart_event(eid, time, vehicle, payload, pad, paths=None, areas=None, actor="CN"):
    return {"id": eid, "layer": "Previous Chinese Launches", "kind": "launch", "actor": actor, "label": f"x_{vehicle}_{payload}",
            "extra": None, "cancelled": False, "vehicle": vehicle, "payload": payload, "time": time, "time_basis": "time",
            "pad": pad, "areas": areas or [], "paths": paths or [], "points": [], "notams": [], "texts": [], "links": [],
            "withheld_notes": 0}


class Names(unittest.TestCase):
    def test_vehicles(self):
        for raw, want in [("LM-7A", "LM-7A"), ("Chang Zheng 7A", "LM-7A"), ("Long March 7A", "LM-7A"),
                          ("Chang Zheng 2C/YZ-1S", "LM-2C"), ("LM-2F/G", "LM-2F"), ("Soyuz-2-1B", "Soyuz-2.1b"),
                          ("SOYUZ 2.1B W/FREGAT", "Soyuz-2.1b"), ("Soyuz 2.1b/Fregat-M", "Soyuz-2.1b"),
                          ("Gushenxing 1", "Ceres-1"), ("Shuang Quxian 1", "Hyperbola-1"), ("Yinli-1", "Gravity-1"),
                          ("Falcon 9 FT5", "Falcon 9"), ("???", P.NOT_KNOWN), ("", P.NOT_KNOWN),
                          ("LM-6A or 4B", "LM-6A or 4B")]:
            self.assertEqual(P.vehicle(raw), want, raw)

    def test_programmes(self):
        self.assertEqual(P.programmes("Yaogan-40 04A-C")[0], ["Yaogan"])
        self.assertEqual(P.programmes("Rassvet-3 G1")[1], "LEO broadband constellation")
        self.assertEqual(P.programmes("Tongxin Jishu Shiyan 24")[0], ["TJS"])  # not also Shiyan
        self.assertEqual(P.programmes("Xingwang Digui 27A-I")[0], ["Guowang (SatNet)"])
        self.assertEqual(P.programmes("Shenzhou-20 Return")[1], "Reentry / landing")
        self.assertEqual(P.programmes("Mystery payload"), ([], "Not classified"))
        self.assertIn("assessed", P.NOTES["Yaogan"])
        # Reviewed 15 Nov 2026
        for text, want in [("25 Sep 24_0044 UTC_ICBM", "Missile / suborbital test"),  # "_" splits words
                           ("WHG-03", "Communications"), ("Weixing Hulianwang Gaogui 01", "Communications"),
                           ("GMM KA", "Test flight"), ("Test?", "Test flight"), ("Tatara-1R", "Rideshare"),
                           ("Dragon C207.4", "Human spaceflight"), ("INSAT-2DS", "Weather"),
                           ("MACH-TB?", "Missile / suborbital test"), ("FOBS Test", "Missile / suborbital test"),
                           ("Multiple Payloads", "Rideshare")]:
            self.assertEqual(P.programmes(text)[1], want, text)
        self.assertEqual(P.programmes("Jielong-3 Multiple Payloads Tech Demo")[1], "Technology / experimental")

    def test_programmes_reviewed_16_nov(self):
        # The eight names left "Not classified" (GCAT's flight, mission and payload names, or the charted label)
        for texts, want in [(["Helusi 1", "Horus 1"], "Earth observation"),
                            (["Lingxi-03/Sixiang", "Sixiang", "Yinhe-8", "Kuangda Nanhu"], "Earth observation"),
                            (["Tianxing-1 02", "Chuangxin-15 02"], "Technology / experimental"),
                            (["EXSQ", "Enshi Xidou Shanquan"], "Earth observation"),
                            (["Enshi Xidu Shanquan"], "Earth observation"),
                            (["Cosmos Will See You Now", "Open Cosmos", "MR 1"], "LEO broadband constellation"),
                            (["ZK-14/15", "Jingan Mengxiang", "Muduo 1A", "Zhongke-1 15"], "Earth observation"),
                            (["25 Aug 26_0321 UTC_LM-6C_Jingan Mengxiang"], "Earth observation"),
                            (["Tanluzhe", "Tanluzhe A"], "Science / exploration"),
                            (["Pengcheng #1, Diting 01A-C, Chaozhisuan-1, Yunxiao Tanluzhe", "Pujiang-4"],
                             "Earth observation")]:
            self.assertEqual(P.programmes(*texts)[1], want, texts)
        # "Yaogan" is also the word for remote sensing: a customer's satellite is not the series
        for texts in [["Alsat-3A", "Aerjiliya Yaogan-3A"], ["PRSC-HS1", "Bajistan Yaogan 02"],
                      ["Aman Zhineng Yaogan-1"], ["Tianyi-51/52", "Caiyun SAR01", "Xinglianti Tianyuan YG01"]]:
            self.assertNotIn("Yaogan", P.programmes(*texts)[0], texts)
        for texts in [["Yaogan 39 05 zu 01 xing"], ["YG53/YG56"], ["9-20 Oct 26_1500-1459 UTC_LM-4B_Yaogan?"],
                      ["11 Jan 24_0352 UTC_Yaogan-40"], ["Shiyan-37 and Yaogan-38"], ["YG-40"]]:
            self.assertIn("Yaogan", P.programmes(*texts)[0], texts)
        # "Shiyan" is also the word for experimental: the series carries its number
        for text in ["Guanlan Shiyan Xing", "Dingzhihua Shiyan Zaihe", "Shutianyuxing-01 shiyan xing"]:
            self.assertNotIn("Shiyan", P.programmes(text)[0], text)
        for text in ["Shiyan 24C-01", "SY24A/B", "Shiyan-30 01 and 02", "Shi Yan 12"]:
            self.assertIn("Shiyan", P.programmes(text)[0], text)
        self.assertEqual(P.programmes("Chonfu Shiyong Shiyan HQ 4")[0], ["Reusable spacecraft (CSSHQ)"])

    def test_pla_owner(self):
        for owners in [["ZLZB"], ["ZZB/CAST"], ["ZLZB?"], ["CASC", "JHB"]]:
            self.assertEqual(P.programmes("Gao Fen 12-05", owners=owners),
                             (["Gaofen", P.PLA_OWNED], "Military / intelligence"), owners)
        for owners in [None, [], ["CAST"], ["CMSEO"], ["ZXW"], ["PLABS"]]:  # Planet's code starts with PLA
            self.assertEqual(P.programmes("Gao Fen 12-05", owners=owners), (["Gaofen"], "Earth observation"), owners)
        self.assertEqual(P.programmes("Shenzhou-20 Return", owners=["ZZB"])[1], "Reentry / landing")
        self.assertIn(P.PLA_OWNED, P.NOTES)

    def test_payload_unknown(self):
        for name in ["Unk Payload", "Unknown Payload DELAYED", "Payload Unk", "Payload", "UNK", "", None,
                     "2240-0320 ???", "Poss Zhuque-3 Unk Payload"]:
            self.assertTrue(P.payload_unknown(name), name)
        for name in ["Horus 1", "Test", "Funky-1"]:
            self.assertFalse(P.payload_unknown(name), name)
        self.assertEqual(P.MTYPES[-1], "Not classified")  # catalog.py reads the last as "not classified"

    def test_orbits(self):
        self.assertEqual(P.orbit_class("Sat SSO D"), "SSO / polar")
        self.assertEqual(P.orbit_class("Sat LSS O"), "Space station")
        self.assertEqual(P.orbit_class(None, "PO"), "SSO / polar")
        self.assertEqual(P.orbit_class("Test"), P.NOT_KNOWN)

    def test_gcat_dates_and_agency(self):
        self.assertEqual(gcat.vague_date("2026 Nov 12 0436:30")["time"], "2026-11-12T04:36:30Z")
        self.assertEqual(gcat.vague_date("2026 Nov  4?")["date"], "2026-11-04")
        self.assertTrue(gcat.vague_date("2026 Nov  4?")["uncertain"])
        self.assertEqual(gcat.agency_country("CALT/CASC", {"CALT": {"state": "CN"}}), "CN")
        self.assertEqual(gcat.agency_country("XX", {}), None)


class Azimuths(unittest.TestCase):
    def test_branches(self):
        az, direct = catalog.branches(45.92, 51.64)  # Baikonur to the ISS: about 63 or 117 degrees
        self.assertTrue(direct)
        self.assertAlmostEqual(az[0], 63.2, delta=0.6)
        self.assertAlmostEqual(az[1], 116.8, delta=0.6)
        self.assertEqual(catalog.branches(28.5, 10.0), ([90.0], False))  # below the latitude: due east
        polar = catalog.branches(34.6, 97.6)[0]  # retrograde: north-west or south-west
        self.assertTrue(any(180 < a < 200 for a in polar) and any(340 < a < 360 for a in polar))

    def test_choose(self):
        bands = [{"from": 140, "to": 145, "events": 6}]
        self.assertEqual(catalog.choose([40.0, 140.0], bands, None)[0], 140.0)
        az, why = catalog.choose([350.0, 190.0], [], "Vandenberg", polar=True)
        self.assertEqual(az, 190.0)
        self.assertIn("south-going", why)
        az, why = catalog.choose([40.0, 140.0], [], "Kourou")
        self.assertEqual(az, 40.0)
        self.assertIn("assumed", why)

    def test_infer_path_order(self):
        pad = [110.95, 19.61]
        drawn = catalog.infer_path(pad, "Wenchang", [], drawn=[[[110.95, 19.61], [118.0, 15.0]]])
        self.assertEqual(drawn["kind"], "drawn")
        area = catalog.infer_path(pad, "Wenchang", [], areas=[{"azimuth": 120.0, "downrange_nm": 400}, {"azimuth": 125.0, "downrange_nm": 900}], inc=50)
        self.assertEqual((area["az"], area["nm"]), (125.0, 1035))
        far = catalog.infer_path(pad, "Wenchang", [], areas=[{"azimuth": 120.0, "downrange_nm": 400},
                                                               {"azimuth": 290.0, "downrange_nm": 9500}])
        self.assertEqual(far["az"], 120.0)  # a splashdown half a world away sets no azimuth
        geo = catalog.infer_path(pad, "Wenchang", [], orbit="GTO / GEO")
        self.assertEqual(geo["az"], 90.0)
        self.assertIsNone(catalog.infer_path(pad, "Wenchang", [{"from": 100, "to": 105, "events": 2}]))  # too few to use
        self.assertIsNone(catalog.infer_path(None, None, [], inc=50))

    def test_cape_polar_corridor(self):
        # PACE (8 Feb 2024, GCAT inclination 98.07): offshore to the turn point, then the inclination's azimuth from
        # there, not 189 deg from the pad across the Florida peninsula.
        slc40 = [-80.5774, 28.5619]
        p = catalog.infer_path(slc40, "Cape Canaveral", [], inc=98.07)
        self.assertEqual(p["via"], [[-79.7, 26.3]])
        self.assertTrue(185 < p["az"] < 192)
        self.assertIn("dog-leg", p["basis"])
        self.assertIn("via", catalog.infer_path([-80.6041, 28.6082], "Kennedy (KSC)", [], inc=86.5))
        # North-going (a space station) and other sites keep a single great circle from the pad.
        self.assertNotIn("via", catalog.infer_path(slc40, "Cape Canaveral", [], inc=51.6))
        self.assertNotIn("via", catalog.infer_path([-120.61, 34.63], "Vandenberg", [], inc=97.6))
        # A measured bearing (a closure area) is never turned.
        area = catalog.infer_path(slc40, "Cape Canaveral", [], areas=[{"azimuth": 170.0, "downrange_nm": 300}], inc=98.07)
        self.assertNotIn("via", area)

    def test_paths_drawn_back_to_the_pad_are_turned_round(self):
        wen = [110.95, 19.61]
        sites = {"WEN": SITES["WEN"]}
        back = {"id": "x", "pad": [120.0, 10.0], "paths": [[[120.0, 10.0], [115.0, 15.0], wen]]}
        e = catalog.orient_paths(back, sites)
        self.assertEqual(e["pad"], wen)
        self.assertEqual(e["paths"][0][0], wen)
        self.assertEqual(back["paths"][0][0], [120.0, 10.0])  # the source event is not changed
        sea = {"id": "y", "pad": [125.0, 30.0], "paths": [[[125.0, 30.0], [130.0, 25.0]]]}  # starts at no site
        self.assertIs(catalog.orient_paths(sea, sites), sea)
        legs = {"id": "z", "pad": [125.0, 30.0], "paths": [[[125.0, 30.0], [130.0, 25.0]], [[120.0, 10.0], wen]]}
        self.assertEqual(catalog.orient_paths(legs, sites)["pad"], wen)  # the first line starting at a site
        later = {"id": "w", "pad": [125.0, 30.0], "paths": [[[125.0, 30.0], [130.0, 25.0]], [wen, [120.0, 10.0]]]}
        self.assertEqual(catalog.orient_paths(later, sites)["pad"], wen)  # a later leg drawn first

    def test_path_length_and_farthest_area(self):
        # The History tab's range filters: a charted path's length (legs summed) and the farthest area's distance.
        one_deg = catalog.path_length_nm([[0.0, 0.0], [1.0, 0.0]])
        self.assertEqual(one_deg, 60)  # one degree of the equator is about 60 NM
        self.assertEqual(catalog.path_length_nm([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]), 120)
        self.assertEqual(catalog.path_length_nm([[0.0, 0.0]]), 0)
        drawn = catalog.infer_path([0.0, 0.0], None, [], drawn=[[[0.0, 0.0], [1.0, 0.0]], [[0.0, 0.0], [3.0, 0.0], [4.0, 0.0]]])
        self.assertEqual(drawn["len_nm"], 240)  # the longest line, as for its azimuth
        areas = [{"azimuth": 120.0, "downrange_nm": 400.4}, {"azimuth": 290.0, "downrange_nm": 9500.6}, {"ring": []}]
        self.assertEqual(catalog.farthest_nm([0, 0], areas), 9501)  # every area counts here, a splashdown too
        self.assertIsNone(catalog.farthest_nm(None, areas))
        self.assertIsNone(catalog.farthest_nm([0, 0], [{"ring": []}]))


class Ledger(unittest.TestCase):
    def test_merge_keeps_fields_and_unions(self):
        old = {"launches": [dict(gcat_rec("2026-001", "2026-01-01T00:00:00Z", "Chang Zheng 7A", "A", "WEN", inc=19.5), updated="2026-01-02T00:00:00Z")]}
        new = {"launches": [dict(gcat_rec("2026-001", "2026-01-01T00:00:00Z", "Chang Zheng 7A", "A", "WEN"), outcome="failure",
                                 updated="2026-01-03T00:00:00Z"),
                            gcat_rec("2026-002", "2026-01-05T00:00:00Z", "Falcon 9", "B", "CC", country="US")]}
        m = catalog.merge(old, None, new)
        self.assertEqual(len(m["launches"]), 2)
        a = m["launches"][0]
        self.assertEqual(a["outcome"], "failure")  # the newer reading wins
        self.assertEqual(a["inc"], 19.5)  # and a field it lacks is kept

    def test_flown_and_closures(self):
        up = [{"id": "u1", "net": "2026-11-14T01:00:00Z", "status": "Success", "name": "x", "lat": 51.88, "lon": 128.33},
              {"id": "u2", "net": "2026-11-20T01:00:00Z", "status": "Go", "name": "y", "lat": 51.88, "lon": 128.33}]
        f = catalog.flown_from_ll2(up, NOW)
        self.assertEqual([x["id"] for x in f], ["ll2:u1"])
        self.assertTrue(f[0]["provisional"])
        cl = catalog.closures_from_matches(
            [{"launch": "u2", "area": "A1", "level": "time and place", "area_source": "faa-tfr", "window": ["a", "b"]},
             {"launch": "u2", "area": "A2", "level": "time"}],
            [{"key": "A1", "ring": [[0, 0], [1, 0], [1, 1], [0, 0]]}, {"key": "A2", "ring": [[0, 0], [1, 0], [1, 1], [0, 0]]}], NOW)
        self.assertEqual([c["area"] for c in cl], ["A1"])  # time-only coincidences are not kept


class Index(unittest.TestCase):
    def build(self, events, launches, upcoming=(), corridors=()):
        return catalog.build_index({"events": events}, {"since": "2023-01-01", "sites": SITES, "launches": launches, "closures": []},
                                   list(upcoming), list(corridors), NOW)

    def test_chart_joins_gcat_and_placemarks_fold(self):
        pad = [110.95, 19.61]
        ev1 = chart_event("hist:a", "2026-05-26T16:16:00Z", "LM-7A", "TJS-24", pad, paths=[[pad, [120.0, 15.0]]])
        ev2 = chart_event("hist:b", "2026-05-26T16:16:00Z", "LM-7A", "TJS-24 nav warning", None)
        g = gcat_rec("2026-116", "2026-05-26T16:16:30Z", "Chang Zheng 7A", "TJS-24", "WEN", category="Sat GTO O", inc=0.04)
        g2 = gcat_rec("2026-117", "2026-06-01T00:00:00Z", "Chang Zheng 5", "Other", "WEN")
        ix = self.build([ev1, ev2], [g, g2])
        recs = {r["id"]: r for r in ix["records"]}
        self.assertEqual(set(recs), {"hist:a", "gcat:2026-117"})  # one record for the launch, one GCAT-only
        r = recs["hist:a"]
        self.assertEqual(r["chart"], ["hist:a", "hist:b"])
        self.assertEqual((r["gcat"], r["vehicle"], r["site"], r["orbit"]), ("2026-116", "LM-7A", "Wenchang", "GTO / GEO"))
        self.assertEqual(r["time"], "2026-05-26T16:16:30Z")  # GCAT's launch time
        self.assertEqual(r["path"]["kind"], "drawn")
        self.assertEqual(r["programmes"], ["TJS"])

    def test_second_pass_needs_vehicle_and_place(self):
        pad = [110.95, 19.61]
        ev = chart_event("hist:c", "2026-03-01T10:00:00Z", "LM-7A", "Unknown", pad)  # the map's time is a day early
        g = gcat_rec("2026-050", "2026-03-02T09:00:00Z", "Chang Zheng 7A", "Something", "WEN")
        r = [x for x in self.build([ev], [g])["records"] if x["id"] == "hist:c"][0]
        self.assertEqual(r["join"]["pass"], 2)
        self.assertEqual(r["chart_time"], "2026-03-01T10:00:00Z")
        other = gcat_rec("2026-051", "2026-03-02T09:00:00Z", "Chang Zheng 5", "Something", "WEN")
        r = [x for x in self.build([ev], [other])["records"] if x["id"] == "hist:c"][0]
        self.assertNotIn("gcat", r)  # a different vehicle a day later is not the same launch

    def test_same_country_far_away_needs_a_vehicle_that_does_not_differ(self):
        # An ICBM charted 1,393 NM from Wenchang joined a Wenchang launch 71 minutes away (25 Sep 2024) by country alone.
        far = [100.3, 40.96]
        g = gcat_rec("2026-060", "2026-04-01T10:00:00Z", "Chang Zheng 7A", "Something", "WEN")
        for veh, joined in (("ICBM", False), ("LM-7A", True), ("Unknown Rocket and Unknown Payload", True)):
            ev = chart_event("hist:f", "2026-04-01T11:00:00Z", veh, "X", far)
            r = [x for x in self.build([ev], [g])["records"] if x["id"] == "hist:f"][0]
            self.assertEqual("gcat" in r, joined, veh)
        self.assertFalse(catalog._other_vehicle("Pegasus", "Pegasus XL"))
        self.assertTrue(catalog._other_vehicle("ICBM", "Lijian-1"))

    def test_upcoming_and_borrowed_inclination(self):
        g = gcat_rec("2026-200", "2026-10-01T00:00:00Z", "Falcon 9", "Starlink Group 11-1", "VSFBS", inc=53.0, country="US")
        up = {"id": "u9", "name": "Falcon 9 | Starlink Group 11-9", "net": "2026-11-20T00:00:00Z", "status": "Go",
              "vehicle": "Falcon 9 Block 5", "mission": "Starlink Group 11-9", "orbit": "LEO", "provider_countries": ["US"],
              "location": "Vandenberg SFB, CA, USA", "lat": 34.632, "lon": -120.611}
        ix = self.build([], [g], [up])
        r = [x for x in ix["records"] if x["id"] == "ll2:u9"][0]
        self.assertEqual((r["status"], r["site"], r["mtype"]), ("upcoming", "Vandenberg", "LEO broadband constellation"))
        self.assertIn("last Starlink launch from Vandenberg", r["path"]["basis"])
        self.assertGreater(r["path"]["az"], 90)  # Vandenberg launches go south
        self.assertLess(r["path"]["az"], 270)

    def test_site_named_by_launch_library_wins(self):
        # SLC-41 is closer to GCAT's coarse Kennedy point than to its Canaveral point; the place name decides.
        self.assertEqual(catalog.nearest_site(28.583, -80.583, SITES, place="Cape Canaveral SFS, FL, USA"), "Cape Canaveral")
        self.assertEqual(catalog.nearest_site(28.583, -80.583, SITES), "Kennedy (KSC)")



def ring(lon, lat, d=0.5):
    return [[lon, lat], [lon + d, lat], [lon + d, lat - d], [lon, lat - d], [lon, lat]]


def nfc_launch(nid, time, vehicle_zh, site, notices, gcat=None):
    return {"id": nid, "vehicle": None, "vehicle_zh": vehicle_zh, "site": site, "site_zh": None, "time": time,
            "date": time[:10] if time else None, "notices": notices, "paths": [], "from": ["map"], "gcat": gcat}


def nn(fir, number=None, start=None, end=None, rg=None, label=None):
    return {"fir": fir, "number": number, "label": label, "start": start, "end": end, "ring": rg}


class NotamForChina(unittest.TestCase):
    def build(self, events, launches, launches_nfc):
        doc = {"source": "github.com/mikezang/NotamForChina", "commit": "x" * 40, "licence": "Apache-2.0",
               "attribution": "NotamForChina by mikezang", "launches": launches_nfc}
        return catalog.build_index({"events": events}, {"since": "2023-01-01", "sites": SITES, "launches": launches,
                                                         "closures": []}, [], [], NOW, doc)

    def recs(self, ix):
        return {r["id"]: r for r in ix["records"]}

    def test_notices_join_by_tag_and_areas_are_drawn(self):
        g = gcat_rec("2024-100", "2024-06-01T10:00:00Z", "Chang Zheng 7A", "X", "WEN")
        x = nfc_launch("nfc:1", "2024-06-01T10:00:00Z", "长征七号甲", "Wenchang",
                       [nn("ZJSA", "A1000/24", rg=ring(112, 18)), nn("ZJSA", "A1000/24", "2024-06-01T09:50:00Z", "2024-06-01T10:40:00Z")],
                       gcat="2024-100")
        ix = self.build([], [g], [x])
        r = self.recs(ix)["gcat:2024-100"]
        self.assertEqual(r["sources"], ["gcat", "nfc"])
        self.assertEqual(len(r["nfc_notices"]), 1)  # one notice: the sheet's window folded into the charted area
        self.assertEqual(r["nfc_notices"][0]["start"], "2024-06-01T09:50:00Z")
        self.assertIn("closure area", r["path"]["basis"])  # the charted area sets the azimuth
        self.assertEqual(ix["nfc"]["licence"], "Apache-2.0")
        self.assertEqual(ix["nfc"]["licence_file"], catalog.NFC_LICENCE_FILE)

    def test_a_tag_to_another_vehicle_is_refused(self):
        g = gcat_rec("2024-101", "2024-06-01T10:00:00Z", "Lijian-1", "X", "WEN")
        x = nfc_launch("nfc:2", "2024-06-01T10:05:00Z", "快舟一号甲", "Wenchang", [nn("ZJSA", "A1001/24")], gcat="2024-101")
        r = self.recs(self.build([], [g], [x]))
        self.assertNotIn("nfc", r["gcat:2024-101"])
        self.assertEqual(r["nfc:2"]["status"], "notice")  # GCAT covers 2024 and lists no such launch
        self.assertTrue(r["nfc:2"]["nfc_unmatched"])

    def test_untagged_joins_by_vehicle_and_time_else_stands_alone(self):
        g = gcat_rec("2023-145", "2023-09-17T04:13:00Z", "Chang Zheng 2D", "X", "WEN")
        x = nfc_launch("nfc:3", "2023-09-17T04:13:00Z", "长征二号丁", "Jiuquan", [nn("ZLHW", rg=ring(100, 40))])
        old = nfc_launch("nfc:4", "2019-01-01T00:00:00Z", "长征二号F", "Wenchang", [nn("ZJSA", rg=ring(112, 18))])
        undated = nfc_launch("nfc:5", None, None, None, [nn("ZBPE", rg=ring(110, 40))])
        ix = self.build([], [g], [x, old, undated])
        r = self.recs(ix)
        self.assertEqual(r["gcat:2023-145"]["nfc_join"], {"by": "vehicle", "hours": 0.0})  # the folder named another site
        self.assertEqual((r["nfc:4"]["status"], r["nfc:4"]["vehicle"], r["nfc:4"]["site"], r["nfc:4"]["sources"]),
                         ("launched", "LM-2F", "Wenchang", ["nfc"]))  # before GCAT's list here: NotamForChina's word
        self.assertNotIn("nfc:5", r)
        self.assertEqual(ix["counts"]["nfc"]["undated"], 1)

    def test_one_notice_with_toms_text_and_nfc_ring_as_a_check(self):
        pad = [110.95, 19.61]
        ev = chart_event("hist:t", "2025-03-01T10:00:00Z", "LM-7A", "Y", pad,
                       areas=[{"ring": ring(112, 18), "notam": "A0500/25", "centroid": [112.25, 17.75]}])
        ev["notams"] = [{"number": "A0500/25", "q": {"fir": "ZJSA"}, "locations": ["ZJSA"], "text": "x", "start": None, "end": None}]
        g = gcat_rec("2025-050", "2025-03-01T10:00:00Z", "Chang Zheng 7A", "Y", "WEN")
        x = nfc_launch("nfc:6", "2025-03-01T10:00:00Z", "长征七号甲", "Wenchang",
                       [nn("ZJSA", "A0500/25", rg=ring(112.01, 18)), nn("ZGZU", "A0500/25", rg=ring(116, 20)),
                        nn("ZJSA", "A0501/25", rg=ring(113, 17))], gcat="2025-050")
        r = self.recs(self.build([ev], [g], [x]))["hist:t"]
        by = {(n["number"], n["fir"]): n for n in r["nfc_notices"]}
        self.assertTrue(by[("A0500/25", "ZJSA")]["chart"])
        self.assertNotIn("ring", by[("A0500/25", "ZJSA")])  # the charted area is drawn; NotamForChina's is the check
        self.assertLess(by[("A0500/25", "ZJSA")]["gap_nm"], catalog.NFC_AGREE_NM)
        self.assertNotIn("chart", by[("A0501/25", "ZJSA")])
        # the same number in another FIR is another NOTAM
        self.assertEqual(len(r["nfc_notices"]), 3)
        self.assertNotIn("chart", by[("A0500/25", "ZGZU")])

    def test_a_shared_notam_joins_toms_misdated_event(self):
        ev = chart_event("hist:y", "2025-03-12T22:33:00Z", "LM-2D", "Z", [100.3, 40.96])  # the map's name is a year out
        ev["notams"] = [{"number": "A0600/26", "q": {"fir": "ZLHW"}, "locations": ["ZLHW"], "text": "x"}]
        g = gcat_rec("2026-048", "2026-03-12T22:33:00Z", "Chang Zheng 2D", "Z", "WEN")
        x = nfc_launch("nfc:7", "2026-03-12T22:33:00Z", "长征二号丁", "Wenchang", [nn("ZLHW", "A0600/26")], gcat="2026-048")
        ix = self.build([ev], [g], [x])
        r = self.recs(ix)
        self.assertNotIn("gcat:2026-048", r)
        self.assertEqual((r["hist:y"]["gcat"], r["hist:y"]["join"]["pass"]), ("2026-048", 3))
        self.assertEqual(r["hist:y"]["chart_time"], "2025-03-12T22:33:00Z")

    def test_fold_windows_only_when_one_to_one(self):
        rows = [nn("ZHWH/ZPKM", rg=ring(1, 1)), nn("ZHWH", start="2023-01-01T00:00:00Z", end="2023-01-01T01:00:00Z"),
                nn("ZPKM", start="2023-01-01T00:10:00Z", end="2023-01-01T01:10:00Z"), nn("ZLHW", rg=ring(2, 2)),
                nn("ZLHW", rg=ring(3, 3)), nn("ZLHW", start="2023-01-01T00:00:00Z", end="2023-01-01T00:30:00Z")]
        out = catalog.fold_windows(rows)
        self.assertEqual(len(out), 4)  # ZHWH and ZPKM fold into the area spanning both; ZLHW has two areas: stays
        self.assertEqual((out[0]["start"], out[0]["end"]), ("2023-01-01T00:00:00Z", "2023-01-01T01:10:00Z"))

    def test_vehicle_keys(self):
        self.assertTrue(catalog.same_vehicle("LM-11S", "LM-11"))
        self.assertTrue(catalog.same_vehicle("Zhuque-2E", "Zhuque-2"))
        self.assertFalse(catalog.same_vehicle("LM-2", "LM-2C"))
        self.assertIsNone(catalog.same_vehicle(P.NOT_KNOWN, "LM-2C"))


class AreaBearings(unittest.TestCase):
    def test_bearings_come_from_the_records_pad(self):
        # The import's bearing (from a line start inside the area) is stale once the pad is moved to the site.
        area = {"centroid": [107.7417, 37.9917], "azimuth": 74.3, "downrange_nm": 10.7}
        a = catalog._bear([111.585, 38.8587], [area])[0]
        self.assertAlmostEqual(a["azimuth"], 255.5, delta=0.5)
        self.assertAlmostEqual(a["downrange_nm"], 190, delta=2)
        self.assertEqual(catalog.farthest_nm([111.585, 38.8587], [a]), round(a["downrange_nm"]))
        self.assertEqual(catalog._bear([111.585, 38.8587], [{"ring": []}]), [{"ring": []}])  # no centroid: as it was


class DrawnHeading(unittest.TestCase):
    def test_heading_is_the_first_legs_not_the_bearing_to_the_end(self):
        line31 = [[-97.16, 26.0], [-83.0, 24.32], [50.66, -27.19], [113.82, -16.05]]  # Starbase, east, to off Australia
        p = catalog.infer_path(line31[0], None, [], drawn=[line31])
        self.assertAlmostEqual(p["az"], 94.4, delta=0.5)  # the bearing to the end would read 282.8
        wiggle = [[0.0, 0.0], [0.1, 0.0], [0.0, 5.0]]  # a 6 NM first leg east, then north
        self.assertAlmostEqual(catalog.initial_heading(wiggle), 0.0, delta=0.5)
        glonass = [[40.6, 62.9], [164.1, -61.2], [-131.2, -61.0]]  # Plesetsk over the pole: every point past a quarter
        self.assertAlmostEqual(catalog.infer_path(glonass[0], None, [], drawn=[glonass])["az"], 111.9, delta=0.5)
        dogleg = [[121.2, 36.6], [121.6, 35.6], [123.2, 20.8], [111.2, -18.6]]  # Haiyang: SSE, then south-west
        az = catalog.infer_path(dogleg[0], None, [], drawn=[dogleg])["az"]
        self.assertAlmostEqual(az, catalog.history.bearing(36.6, 121.2, -18.6, 111.2), delta=0.1)  # downrange, not the first leg
        self.assertAlmostEqual(catalog.initial_heading([[0.0, 0.0], [0.5, 0.0]]), 90.0, delta=0.5)  # short line: its end
        baikonur = [63.56, 46.0]
        outline = [[80.0, 50.5], [89.4, 51.5], [80.0, 50.5]]  # a drop zone drawn as a line, away from the pad
        az = catalog.infer_path(baikonur, None, [], drawn=[outline])["az"]
        self.assertAlmostEqual(az, catalog.history.bearing(46.0, 63.56, 51.5, 89.4), delta=0.1)  # pad to its far end


class PadAtNoSite(unittest.TestCase):
    """A charted path drawn from a point downrange (Starship Flight 6, 19 Nov 2024: 219 NM out in the Gulf) left the
    charted event unjoined and the launch listed twice."""

    def build(self, events, launches):
        return catalog.build_index({"events": events}, {"since": "2023-01-01", "sites": SITES, "launches": launches,
                                                         "closures": []}, [], [], NOW)

    def test_joins_by_time_and_vehicle_and_takes_gcats_pad(self):
        sea = [-116.2, 33.5]  # about 230 NM from Vandenberg, at no launch site
        ev = chart_event("hist:s", "2026-04-01T10:00:00Z", "Falcon 9", "Starlink 9-9", sea,
                         paths=[[sea, [-115.0, 33.0]]], actor=None)
        g = gcat_rec("2026-070", "2026-04-01T10:05:00Z", "Falcon 9", "Starlink 9-9", "VSFBS", country="US")
        recs = {r["id"]: r for r in self.build([ev], [g])["records"]}
        self.assertEqual(set(recs), {"hist:s"})  # one record, not two
        r = recs["hist:s"]
        self.assertEqual((r["gcat"], r["site"], r["join"]["pass"]), ("2026-070", "Vandenberg", 1))
        self.assertEqual(r["pad"], [SITES["VSFBS"]["lon"], SITES["VSFBS"]["lat"]])
        self.assertEqual(r["chart_pad"], sea)
        self.assertEqual(r["path"]["kind"], "drawn")  # the charted line is still drawn as charted
        op = chart_event("hist:v", "2026-04-01T10:00:00Z", "SpaceX", "Starlink 9-9", sea, actor=None)
        r = [x for x in self.build([op], [g])["records"] if x["id"] == "hist:v"][0]
        self.assertEqual((r["gcat"], r["vehicle"]), ("2026-070", "Falcon 9"))  # joined by programme; GCAT names the vehicle

    def test_needs_the_same_vehicle_and_a_pad_at_no_site(self):
        sea = [-116.2, 33.5]
        g = gcat_rec("2026-071", "2026-04-01T10:05:00Z", "Falcon 9", "Starlink 9-9", "VSFBS", country="US")
        other = chart_event("hist:t", "2026-04-01T10:00:00Z", "Minotaur IV", "NROL-1", sea, actor=None)
        r = [x for x in self.build([other], [g])["records"] if x["id"] == "hist:t"][0]
        self.assertNotIn("gcat", r)  # another vehicle at the same time is another launch
        self.assertNotIn("chart_pad", r)
        cape = chart_event("hist:u", "2026-04-01T10:00:00Z", "Falcon 9", "Starlink 9-9", [-80.54, 28.46], actor=None)
        r = [x for x in self.build([cape], [g])["records"] if x["id"] == "hist:u"][0]
        self.assertNotIn("gcat", r)  # a pad at a known site is measured from: the Cape is not Vandenberg


class Suborbital(unittest.TestCase):
    """GCAT's suborbital launches and missile firings (LaunchCode S, Y, A, M, L): kinds, orbit, paths and joins."""

    def sub_rec(self, tag, time, kind, site_code, category="Test", vehicle="Black Brant IX", country="US"):
        return dict(gcat_rec(tag, time, vehicle, tag, site_code, category=category, country=country, names=[]),
                    kind=kind, apogee_km=300.0)

    def build(self, events, launches):
        return catalog.build_index({"events": events}, {"since": "2023-01-01", "sites": SITES, "launches": launches,
                                                         "closures": []}, [], [], NOW)

    def test_kinds_and_mission_types(self):
        self.assertEqual(P.launch_kind("orbital"), P.ORBITAL)
        self.assertEqual(P.launch_kind("near-orbital"), P.ORBITAL)
        self.assertEqual(P.launch_kind("suborbital", "Auroral"), P.SUBORBITAL)
        self.assertEqual(P.launch_kind("crewed suborbital", "Tourist Flight"), P.CREWED_SUB)
        self.assertEqual(P.launch_kind("missile", "Weapon"), P.COMBAT_LAUNCH)
        self.assertEqual(P.launch_kind("missile", "Interceptor Weapon"), P.COMBAT_LAUNCH)
        self.assertEqual(P.launch_kind("missile", "Interceptor"), P.MISSILE)
        self.assertEqual(P.launch_kind("lofted missile", "Sat LEO S"), P.LOFTED)
        self.assertEqual(P.kind_mtype(P.COMBAT_LAUNCH, P.TEST), P.COMBAT)
        self.assertEqual(P.kind_mtype(P.SUBORBITAL, "Not classified", "Auroral"), P.SCI)
        self.assertEqual(P.kind_mtype(P.SUBORBITAL, "Not classified", "Hypersonic"), P.TECH)
        self.assertEqual(P.kind_mtype(P.SUBORBITAL, P.MSL, "Hypersonic"), P.MSL)  # a programme's type stays
        self.assertEqual(P.MTYPES[-1], "Not classified")
        self.assertEqual(P.NO_PAYLOAD, "Payload not known")
        self.assertEqual(set(P.KIND_NOTES), set(P.KINDS))

    def test_backfill_reads_every_kind(self):
        sites = {"WI": {"name": "Wallops I", "full_name": "Wallops Flight Facility", "lat": 37.8, "lon": -75.5, "country": "US"},
                 "SUNAN": {"name": "Sunan", "full_name": "Sunan Airport", "lat": 39.3, "lon": 125.7, "country": "KP"}}
        row = lambda tag, code, site, cat="Test", apo="129", inc="-": {
            "Launch_Tag": tag, "Launch_Date": "2025 Feb  4 1600:07", "LaunchCode": code, "LV_Type": "X", "Variant": "-",
            "Flight": "-", "Mission": "-", "Agency": "NASA", "Category": cat, "Launch_Site": site, "Launch_Pad": "-",
            "Apogee": apo, "Range": "1000", "Inc": inc}
        rows = [row("2025-S01", "SS", "WI"), row("2025-U01", "LS", "SUNAN?", "Sat LEO S", "6000", "40"),
                row("2025-M01", "MS", "SUNAN", "Weapon"), row("2025-001", "OS", "WI", "Sat LEO O", "-", "51.6"),
                row("2025-X01", "XS", "WI"), row("2025-Z01", "ZZ", "WI")]
        out = {r["tag"]: r for r in catalog.from_gcat_tables(rows, [], sites, {}, NOW)}
        self.assertEqual(set(out), {"2025-S01", "2025-U01", "2025-M01", "2025-001"})
        self.assertEqual(out["2025-S01"]["kind"], "suborbital")
        self.assertEqual(out["2025-S01"]["apogee_km"], 129.0)
        u = out["2025-U01"]
        self.assertEqual((u["kind"], u["site_code"], u["inc"], u.get("site_uncertain")), ("lofted missile", "SUNAN", None, True))
        self.assertEqual(u["site"]["name"], "Sunan")
        self.assertEqual(out["2025-001"]["inc"], 51.6)
        self.assertNotIn("apogee_km", out["2025-001"])

    def test_record_kind_orbit_and_no_borrowed_path(self):
        # An orbital launch from the same site would lend its inclination to an orbital launch; not to a sounding rocket.
        orb = gcat_rec("2026-010", "2026-01-01T00:00:00Z", "Falcon 9", "Starlink Group 1-1", "VSFBS", inc=53.0, country="US")
        s = self.sub_rec("2026-S01", "2026-02-01T00:00:00Z", "suborbital", "VSFBS", category="Auroral")
        m = self.sub_rec("2026-M01", "2026-02-02T00:00:00Z", "missile", "VSFBS", category="Weapon", vehicle="Minuteman 3")
        recs = {r["id"]: r for r in self.build([], [orb, s, m])["records"]}
        r = recs["gcat:2026-S01"]
        self.assertEqual((r["kind"], r["orbit"], r["mtype"], r["apogee_km"]), (P.SUBORBITAL, "Suborbital", P.SCI, 300.0))
        self.assertNotIn("path", r)
        self.assertEqual((recs["gcat:2026-M01"]["kind"], recs["gcat:2026-M01"]["mtype"]), (P.COMBAT_LAUNCH, P.COMBAT))
        self.assertEqual(recs["gcat:2026-010"]["kind"], P.ORBITAL)

    def test_suborbital_path_to_its_farthest_area(self):
        pad = [-120.61, 34.63]
        area = {"ring": [[-110, 20], [-109, 20], [-109, 21], [-110, 20]], "centroid": [-109.5, 20.5]}
        ev = chart_event("hist:m", "2026-03-01T10:00:00Z", "Minuteman", "GT 250", pad, areas=[area], actor="US")
        g = self.sub_rec("2026-M02", "2026-03-01T10:05:00Z", "missile", "VSFBS", vehicle="Minuteman 3")
        r = [x for x in self.build([ev], [g])["records"] if x["id"] == "hist:m"][0]
        self.assertEqual((r["gcat"], r["kind"]), ("2026-M02", P.MISSILE))
        self.assertEqual(r["path"]["kind"], "estimated")
        self.assertIn("suborbital", r["path"]["basis"])
        self.assertLess(r["path"]["nm"], 1100)  # drawn to the area (about 1,040 NM), not past it

    def test_joins_combat_never_suborbital_by_place_only(self):
        far_pad = [110.95, 19.61]  # Wenchang; the GCAT launches below are at Vandenberg
        ev = chart_event("hist:x", "2026-04-01T10:00:00Z", "Unknown", "Unknown", far_pad, actor="US")
        test = self.sub_rec("2026-M03", "2026-04-01T10:30:00Z", "missile", "VSFBS")
        r = [x for x in self.build([ev], [test])["records"] if x["id"] == "hist:x"][0]
        self.assertNotIn("gcat", r)  # same country, but 6,000 NM apart: a missile needs to be near in place
        near = chart_event("hist:y", "2026-04-01T10:00:00Z", "Unknown", "Unknown", [-120.6, 34.6], actor="US")
        combat = self.sub_rec("2026-M04", "2026-04-01T10:30:00Z", "missile", "VSFBS", category="Weapon")
        r = [x for x in self.build([near], [combat])["records"] if x["id"] == "hist:y"][0]
        self.assertNotIn("gcat", r)  # a missile fired in combat joins no charted event
        self.assertEqual(r["kind"], P.NOT_KNOWN)

    def test_counts_and_kinds_in_the_index(self):
        ix = self.build([], [self.sub_rec("2026-S05", "2026-02-01T00:00:00Z", "crewed suborbital", "VSFBS")])
        self.assertEqual(ix["kinds"], P.KINDS)
        self.assertEqual(ix["counts"]["gcat_kinds"][P.CREWED_SUB], 1)
        self.assertEqual(ix["records"][0]["mtype"], P.CREW)

    def test_merge_keeps_the_baselines_sites(self):
        base = {"sites": {"WI": {"name": "Wallops", "lat": 1, "lon": 2, "region": True}}}
        old = {"sites": {"WI": {"name": "Wallops I", "lat": 1, "lon": 2, "country": "US"}, "X": {"name": "X"}}}
        m = catalog.merge(base, old)
        self.assertEqual(m["sites"]["WI"], {"name": "Wallops", "lat": 1, "lon": 2, "region": True, "country": "US"})
        self.assertIn("X", m["sites"])


if __name__ == "__main__":
    unittest.main()
