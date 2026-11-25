"""Offline tests for launch/ascent.py and the paths catalog.py builds from it: which closure areas are a launch's
ascent, the path through them (dog-legs), and paths borrowed from a sibling launch."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launch import ascent as A  # noqa: E402
from launch import catalog, history, notam  # noqa: E402
from tests.test_catalog import NOW, SITES, first_leg, gcat_rec  # noqa: E402


def area(pad, az, nm, **kw):
    """An area `nm` from the pad on bearing `az`, as catalog._bear() gives it."""
    return {"azimuth": az, "downrange_nm": nm, "centroid": A.dest(pad, az, nm), **kw}


def ring_area(pad, ring, **kw):
    la, lo = notam.centroid(ring)
    return {"ring": ring, "centroid": [lo, la], "azimuth": history.bearing(pad[1], pad[0], la, lo),
            "downrange_nm": notam.haversine_nm(pad[1], pad[0], la, lo), **kw}


class Timing(unittest.TestCase):
    def test_a_daily_schedule_that_skips_the_launch_sets_its_area_aside(self):
        # LM-2D of 12 Dec 2024, 07:17 UTC: A4241/24 runs 0541-0705 and 0856-1020 daily.
        a = {"windows": [["2024-12-12T05:41:00Z", "2024-12-12T10:20:00Z"]], "schedule": "0541-0705,0856-1020"}
        self.assertFalse(A.time_holds(a, A._dt("2024-12-12T07:17:00Z")))
        self.assertTrue(A.time_holds(dict(a, schedule="0541-0730"), A._dt("2024-12-12T07:17:00Z")))
        self.assertTrue(A.time_holds(dict(a, schedule="0541-0710"), A._dt("2024-12-12T07:17:00Z")))  # SCHED_TOL_MIN
        night = {"windows": [["2024-12-11T23:30:00Z", "2024-12-12T01:30:00Z"]], "schedule": "2330-0130"}
        self.assertTrue(A.time_holds(night, A._dt("2024-12-12T00:10:00Z")))  # past midnight

    def test_a_window_that_ends_before_the_launch(self):
        a = {"windows": [["2026-03-01T00:00:00Z", "2026-03-01T02:00:00Z"]]}
        self.assertFalse(A.time_holds(a, A._dt("2026-03-05T00:00:00Z")))
        self.assertTrue(A.time_holds(a, A._dt("2026-03-01T03:30:00Z")))  # TIME_TOL_H either side
        self.assertTrue(A.time_holds(a, None))  # a launch known only to the day tests nothing


class LaterPass(unittest.TestCase):
    def test_swot_upper_stage_area_is_a_later_pass(self):
        # SWOT, 16 Dec 2022 11:46:47 UTC from Vandenberg, 77.6 deg: HYDROPAC 3529/22, 13:34-13:56 UTC.
        pad = [-120.611, 34.632]
        ring = [[-144.7333, 10.2667], [-146.8167, 9.95], [-145.2667, -0.4167], [-143.2167, -0.1167], [-144.7333, 10.2667]]
        a = ring_area(pad, ring, windows=[["2022-12-16T13:34:00Z", "2022-12-16T13:56:00Z"]], tie=A.TIE_WINDOW)
        kept, aside = A.select(pad, [a], [], time="2022-12-16T11:46:47Z", inc=77.6, own=True)
        self.assertEqual((kept, aside), ([], {"later": 1}))

    def test_a_dog_leg_area_near_the_pad_is_never_a_later_pass(self):
        jiuquan = [100.29, 40.96]
        kept, aside = A.select(jiuquan, [area(jiuquan, 140.0, 900)], [], inc=41.47, own=True)
        self.assertEqual((len(kept), aside), (1, {}))

    def test_beyond_the_ascent_only_a_tied_area_on_the_first_pass_stands(self):
        # LM-2D of 12 Dec 2024 (59.91 deg) from Jiuquan: N5532/24 in the Brisbane FIR, 3,484 NM out on its track.
        jq = [100.2908, 40.9581]
        on = area(jq, 143.3, 3484, tie=A.TIE_NOTAM)
        self.assertEqual(len(A.select(jq, [], [on], inc=59.91, own=True)[0]), 1)
        self.assertEqual(A.select(jq, [], [dict(on, tie=A.TIE_WINDOW)], inc=59.91, own=True)[1], {"far": 1})
        self.assertEqual(A.select(jq, [], [dict(on, azimuth=60.0, centroid=A.dest(jq, 60.0, 3484))], inc=59.91,
                                  own=True)[0], [])  # off its track: set aside


class Selection(unittest.TestCase):
    def test_tied_areas_outweigh_window_joined_ones_off_their_bearing(self):
        jq = [100.29, 40.96]
        near = [area(jq, 187.2, 504, tie=A.TIE_NOTAM, notice="a"), area(jq, 186.5, 640, tie=A.TIE_NOTAM, notice="b"),
                area(jq, 134.4, 1356, notice="c"), area(jq, 136.2, 1357, notice="d"), area(jq, 185.0, 900, notice="e")]
        kept, aside = A.select(jq, near, [], inc=89.0, own=True)
        self.assertEqual(sorted(a["notice"] for a in kept), ["a", "b", "e"])
        self.assertEqual(aside, {"bearing": 2})

    def test_with_no_tied_area_the_group_nearer_the_inclination_wins_a_tie(self):
        # Lijian-2 of 3 Nov 2026 (89 deg from Jiuquan): two areas at 187, two of another event at 135 farther out.
        jq = [100.29, 40.96]
        near = [area(jq, 187.2, 504), area(jq, 186.5, 640), area(jq, 134.4, 1356), area(jq, 136.2, 1357)]
        opts, _ = catalog.branches(jq[1], 89.0)
        kept, _ = A.select(jq, near, [], inc=89.0, own=True, branch_az=opts)
        self.assertTrue(len(kept) == 2 and all(185 < a["azimuth"] < 188 for a in kept))
        p = catalog.infer_path(jq, "Jiuquan", [], areas=near, inc=89.0)
        self.assertAlmostEqual(first_leg(jq, p), 186.5, delta=1)

    def test_a_notices_areas_stand_together(self):
        # HYDROPAC 2699/23 (Chollima-1, 23 Aug 2023): two Yellow Sea areas at 191 deg and one east of Luzon at 170.
        sohae = [124.705, 39.66]
        near = [area(sohae, 191.9, 241, notice="H"), area(sohae, 191.4, 365, notice="H"), area(sohae, 170.1, 1609, notice="H")]
        kept, aside = A.select(sohae, near, [], inc=97.0, own=True, branch_az=catalog.branches(sohae[1], 97.0)[0])
        self.assertEqual((len(kept), aside), (3, {}))
        p = catalog.infer_path(sohae, "Sohae", [], areas=near, inc=97.0)
        self.assertEqual(len(p["via"]), 3)
        self.assertIn("from 191.9° to 170.1°", p["basis"])


class Paths(unittest.TestCase):
    def test_qianfan_lm6a_bends_through_its_areas(self):
        taiyuan = [111.608, 38.849]
        near = [area(taiyuan, 171.4, 180), area(taiyuan, 174.9, 600), area(taiyuan, 178.4, 1236)]
        p = catalog.infer_path(taiyuan, "Taiyuan", [], areas=near, inc=89.0)
        self.assertEqual(len(p["via"]), 3)
        self.assertIn("dog-leg", p["basis"])
        line = catalog.infer_path(taiyuan, "Taiyuan", [], areas=[area(taiyuan, 178.4, x) for x in (180, 600, 1236)], inc=89.0)
        self.assertNotIn("via", line)

    def test_a_kink_is_left_out_not_drawn(self):
        pad = [100.29, 40.96]
        pts = [A.dest(pad, 106, 300), A.dest(pad, 140, 420), A.dest(pad, 110, 900)]  # the middle point lies off the line
        kept, out = A.route(pad, pts)
        self.assertEqual((len(kept), out), (2, 1))
        sohae = [124.705, 39.66]
        dogleg = [A.dest(sohae, 191.9, 241), A.dest(sohae, 191.4, 365), A.dest(sohae, 170.1, 1609)]
        self.assertEqual(A.route(sohae, dogleg)[1], 0)  # a 26 deg turn is a dog-leg

    def test_areas_both_sides_of_the_line_are_one_line(self):
        baikonur = [63.305, 45.965]
        zz = [area(baikonur, 61.0, 300), area(baikonur, 56.5, 600), area(baikonur, 63.0, 900), area(baikonur, 60.0, 1200)]
        self.assertTrue(A.zigzag(baikonur, A.points(baikonur, zz)))
        p = catalog.infer_path(baikonur, "Baikonur", [], areas=zz, inc=51.6)
        self.assertEqual(len(p.get("via") or []), 1 if "via" in p else 0)
        self.assertIn("drop zones side by side", p["basis"])
        sohae = [124.705, 39.66]
        dogleg = [A.dest(sohae, 191.9, 241), A.dest(sohae, 191.4, 365), A.dest(sohae, 170.1, 1609)]
        self.assertFalse(A.zigzag(sohae, dogleg))  # one side only: a dog-leg

    def test_deep_space_from_vandenberg_goes_south(self):
        p = catalog.infer_path([-120.611, 34.632], "Vandenberg", [], orbit="Deep space / lunar")
        self.assertEqual(p["az"], 157.5)
        self.assertIn("DART", p["basis"])

    def test_areas_at_one_distance_are_one_point(self):
        pad = [111.608, 38.849]
        pts = A.points(pad, [area(pad, 170.0, 600), area(pad, 172.0, 620), area(pad, 178.0, 1200)])
        self.assertEqual(len(pts), 2)

    def test_an_override_is_drawn_the_default_length(self):
        jiuquan = [100.29, 40.96]  # Shenzhou: 162 deg to an area, the station's 41.5 deg allows ~83 or ~97
        p = catalog.infer_path(jiuquan, "Jiuquan", [], areas=[area(jiuquan, 162.0, 900)], orbit_code="LSS")
        self.assertEqual(p["nm"], catalog.DEFAULT_PATH_NM)
        self.assertIn("off the ascent track", p["basis"])


class Borrowed(unittest.TestCase):
    def test_a_path_from_the_inclination_takes_a_sibling_launch_path(self):
        pad = [110.9511, 19.6142]
        donor = {"id": "gcat:a", "status": "launched", "site": "Wenchang", "pad": pad, "time": "2026-01-01T00:00:00Z",
                 "vehicle": "LM-8", "path": {"kind": "estimated", "az": 190.0, "nm": 1240, "basis": "x", "_by": "areas",
                                             "_inc": 89.0, "_n": 3}}
        thin = dict(donor, id="gcat:t", path=dict(donor["path"], _n=1))
        r = {"id": "gcat:b", "status": "launched", "site": "Wenchang", "pad": pad, "time": "2026-03-01T00:00:00Z",
             "path": {"kind": "estimated", "az": 178.9, "nm": 1500, "_by": "inc", "_inc": 88.99,
                      "basis": "payload inclination 88.99° (GCAT) from the pad's latitude; south-going"}}
        self.assertEqual(catalog.borrow_paths([donor, thin, r]), 1)
        self.assertEqual((r["path"]["az"], r["path"]["nm"], r["path"]["borrowed"]), (190.0, 1500, "gcat:a"))
        self.assertIn("no closure areas of its own", r["path"]["basis"])
        self.assertNotIn("_by", donor["path"])
        far = dict(r, id="gcat:c", path=dict(r["path"], _inc=97.5, _by="inc"))
        self.assertEqual(catalog.borrow_paths([dict(donor, path=dict(donor["path"], _by="areas")), far]), 0)


class Published(unittest.TestCase):
    def test_a_published_notice_gives_its_launch_areas(self):
        sites = dict(SITES, SOH={"name": "Sohae", "gcat_name": "Sohae", "lat": 39.66, "lon": 124.705, "country": "KP"})
        g = dict(gcat_rec("2023-F06", "2023-05-30T21:27:00Z", "Chollima-1", "Malligyong-1", "WEN", inc=97.0,
                          country="KP"), site_code="SOH", site={"name": "Sohae", "lat": 39.66, "lon": 124.705, "country": "KP"})
        ring = [[128.6677, 14.9017], [129.1806, 11.3217], [129.9013, 11.447], [129.4005, 15.0237], [128.6677, 14.9017]]
        pub = [{"tag": "2023-F06", "kind": "NGA navigational warning", "issuer": "NGA", "number": "HYDROPAC 1779/23",
                "stage": "area C", "windows": [["2023-05-30T15:00:00Z", "2023-06-10T15:00:00Z"]], "ring": ring,
                "source": {"publisher": "P", "title": "T", "url": "https://example.org/x", "date": "2023-05-31"},
                "reviewed": "2026-11-18"}]
        ledger = {"since": "2023-01-01", "sites": sites, "launches": [g], "closures": []}
        r = catalog.build_index({"events": []}, ledger, [], [], NOW, published=pub)["records"][0]
        self.assertEqual((r["published_notices"][0]["number"], "published" in r["sources"]), ("HYDROPAC 1779/23", True))
        self.assertIn("closure area", r["path"]["basis"])
        self.assertTrue(160 < first_leg(r["pad"], r["path"]) < 180)


if __name__ == "__main__":
    unittest.main()
