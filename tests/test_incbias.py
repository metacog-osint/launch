"""Offline tests for the implied-inclination calibration (launch/incbias.py) and its use in live matching.
Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import ascent, history, incbias, live  # noqa: E402

XICHANG = (28.2, 102.0)   # lat, lon
# Past 35-degree launches from a Xichang-like pad whose farthest areas lay about 104.5 deg from the pad (south of
# the plain 35-degree heading: the bearing reads about 31.4).
PAST_35 = [[102.0, 28.2, az, 35.0] for az in (104.3, 104.5, 104.5, 104.6, 104.8)]
NET = "2026-11-30T08:00:00Z"
WIN = [{"start": "2026-11-30T07:50:00Z", "end": "2026-11-30T08:40:00Z"}]


def box(lat, lon, key, w=0.3, windows=WIN):
    return {"key": key, "ring": [[lon - w, lat - w], [lon + w, lat - w], [lon + w, lat + w], [lon - w, lat + w],
                                 [lon - w, lat - w]], "windows": windows}


def along(az, nm, key):
    lon, lat = ascent.dest([XICHANG[1], XICHANG[0]], az, nm)
    return box(lat, lon, key)


class Implied(unittest.TestCase):
    def test_plain_bearing_reads_low_for_a_xichang_35_degree_launch(self):
        self.assertAlmostEqual(history.inclination(28.2, 104.5), 31.4, delta=0.3)

    def test_calibrated_reading_gives_35(self):
        inc, n = incbias.implied(28.2, 102.0, 104.6, PAST_35)
        self.assertEqual(n, 5)
        self.assertAlmostEqual(inc, 35.0, delta=0.3)

    def test_too_few_past_launches_leave_the_reading(self):
        inc, n = incbias.implied(28.2, 102.0, 104.6, PAST_35[:2])
        self.assertEqual((inc, n), (history.inclination(28.2, 104.6), 0))
        self.assertIn("too few", incbias.basis(0))
        self.assertIn("5 past launches", incbias.basis(5))

    def test_other_bearings_and_other_sites_do_not_count(self):
        self.assertEqual(incbias.implied(28.2, 102.0, 115.0, PAST_35)[1], 0)    # over AZ_WIN off
        moved = [[s[0] + 2, s[1], s[2], s[3]] for s in PAST_35]                  # ~105 NM away
        self.assertEqual(incbias.implied(28.2, 102.0, 104.6, moved)[1], 0)
        self.assertEqual(incbias.implied(28.2, 102.0, 104.6, None)[1], 0)

    def test_nearest_bearings_set_the_correction(self):
        # Five launches on 104.5 that read 3.6 low, four on 108-109 that read about 2 low: the nearest five rule.
        other = [[102.0, 28.2, az, 35.0] for az in (108.0, 108.5, 108.8, 109.0)]
        inc, n = incbias.implied(28.2, 102.0, 104.5, PAST_35 + other)
        self.assertEqual(n, incbias.K)
        self.assertAlmostEqual(inc, 35.0, delta=0.3)

    def test_retrograde_sso_reading_comes_down(self):
        # A Taiyuan-like pad whose sun-synchronous launches' areas lie 193.5 deg out, reading about 3 high.
        past = [[111.6, 38.85, az, 97.5] for az in (193.2, 193.4, 193.5, 193.6, 193.8)]
        raw = history.inclination(38.85, 193.6)
        self.assertGreater(raw, 100)
        inc, n = incbias.implied(38.85, 111.6, 193.6, past)
        self.assertEqual(n, 5)
        self.assertAlmostEqual(inc, 97.5, delta=0.3)


class Samples(unittest.TestCase):
    BASE = {"kind": "Orbital", "orbit": "LEO", "pad": [102.0, 28.2], "inc": 35.0}

    def test_farthest_area_bearing_is_a_sample(self):
        r = {**self.BASE, "path": {"az": 104.5, "basis": "bearing from the pad to its farthest closure area"}}
        self.assertEqual(incbias.sample(r), [102.0, 28.2, 104.5, 35.0])

    def test_dog_leg_takes_its_last_area_point(self):
        lon, lat = ascent.dest([102.0, 28.2], 106.0, 600)
        r = {**self.BASE, "path": {"az": 70.0, "via": [[lon, lat]],
                                   "basis": "through its closure areas in order of distance (2 areas, ...)"}}
        self.assertAlmostEqual(incbias.sample(r)[2], 106.0, delta=0.2)

    def test_paths_not_from_areas_and_high_orbits_are_not_samples(self):
        by_inc = {**self.BASE, "path": {"az": 68.0, "basis": "payload inclination 35 (GCAT) from the pad's latitude"}}
        turned = {**self.BASE, "path": {"az": 68.0, "basis": "bearing from the pad to its farthest closure area, "
                                                             "then on the heading of its orbit there"}}
        gto = {**self.BASE, "orbit": "GTO / GEO",
               "path": {"az": 100.0, "basis": "bearing from the pad to its farthest closure area"}}
        failed = {**self.BASE, "inc": 0.0, "path": {"az": 100.0, "basis": "bearing from the pad to its farthest closure area"}}
        self.assertEqual(incbias.samples([by_inc, turned, gto, failed]), [])


class LiveUse(unittest.TestCase):
    UP = [{"id": "u1", "name": "Long March 2D | Unknown Payload", "net": NET, "lat": XICHANG[0], "lon": XICHANG[1]}]

    def test_match_carries_the_corrected_estimate(self):
        areas = [along(104.5, 315, "near")]
        plain = live.match(self.UP, areas, [], [])[0]
        fixed = live.match(self.UP, areas, [], [], None, PAST_35)[0]
        self.assertEqual(plain["level"], "time and place")
        self.assertAlmostEqual(plain["inclination_est"], 31.4, delta=0.4)
        self.assertAlmostEqual(fixed["inclination_est"], 35.0, delta=0.4)
        self.assertIn("corrected", fixed["inclination_basis"])
        self.assertIn("too few", plain["inclination_basis"])

    def test_track_orbits_fall_back_on_the_given_estimate(self):
        self.assertEqual([i for i, _ in live.track_orbits(28.2, 104.5, [], 35.0)], [32.0, 33.5, 35.0, 36.5, 38.0])
        self.assertEqual(live.track_orbits(28.2, 104.5, [])[2][0], history.inclination(28.2, 104.5))

    def test_on_track_follows_the_corrected_orbit(self):
        t = live.ground_track(XICHANG[0], XICHANG[1], 35.0, False, 30, 30)
        far = box(t[0][1], t[0][2], "far",
                  windows=[{"start": "2026-11-30T08:10:00Z", "end": "2026-11-30T08:45:00Z"}])
        rows = {r["area"]: r for r in live.match(self.UP, [along(104.5, 315, "near"), far], [], [], None, PAST_35)}
        self.assertEqual(rows["far"]["level"], "time and place")
        self.assertEqual(rows["far"]["track"]["inc"], 35.0)
        plain = {r["area"]: r for r in live.match(self.UP, [along(104.5, 315, "near"), far], [], [])}
        self.assertNotEqual((plain["far"]["track"] or {}).get("inc"), 35.0)


if __name__ == "__main__":
    unittest.main()
