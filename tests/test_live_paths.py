"""The Live tab's estimated paths: which live closure areas a scheduled launch's path runs through
(catalog.live_paths) and site_src/livepaths.js, run in Node."""
import json
import pathlib
import shutil
import subprocess
import unittest

from launch import ascent, catalog, live

ROOT = pathlib.Path(__file__).resolve().parents[1]
LP = (ROOT / "site_src" / "livepaths.js").as_uri()
NODE = shutil.which("node")
VANDENBERG = [-120.611, 34.632]
NET = "2026-11-22T12:16:00Z"
WINDOW = {"start": "2026-11-22T12:00:00Z", "end": "2026-11-22T13:30:00Z"}


def area(pad, az, nm, key, windows=None, half=0.2):
    lon, lat = ascent.dest(pad, az, nm)
    ring = [[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half], [lon - half, lat + half],
            [lon - half, lat - half]]
    return {"key": key, "source": "cordon-navwarn", "ring": ring, "windows": [WINDOW] if windows is None else windows}


def rec(pad=VANDENBERG, az=155.4, **kw):
    return {"id": "ll2:x", "ll2": "x", "status": "upcoming", "time": NET, "net_precision": "Minute", "pad": list(pad),
            "site": "Vandenberg", "orbit": "LEO", "kind": "Orbital", "actor": "US",
            "path": {"kind": "estimated", "az": az, "nm": 1500, "basis": "the estimate before any live area"}, **kw}


def row(i, a, level="time", launch="x"):
    return {"launch": launch, "area": a["key"], "area_i": i, "area_source": a["source"], "level": level,
            "window": [WINDOW["start"], WINDOW["end"]]}


def roles(r):
    return {c["area"]: c["role"] for c in r["live"]["closures"]}


class LivePathsTest(unittest.TestCase):
    def run_one(self, r, areas, levels=None):
        ms = [row(i, a, (levels or {}).get(a["key"], "time")) for i, a in enumerate(areas)]
        return catalog.live_paths([r], ms, areas, {})

    def test_time_only_areas_on_the_expected_bearing_set_the_path(self):
        areas = [area(VANDENBERG, 156, 104, "a"), area(VANDENBERG, 154, 271, "b"), area(VANDENBERG, 156, 332, "c")]
        r = rec()
        self.assertEqual(self.run_one(r, areas), 1)
        self.assertEqual(set(roles(r).values()), {"path"})
        self.assertAlmostEqual(r["path"]["az"], 156, delta=1)
        self.assertGreater(r["path"]["nm"], 332)
        self.assertIn("closure area", r["path"]["basis"])
        self.assertFalse([k for k in r["path"] if k.startswith("_")])

    def test_a_far_coincidence_draws_nothing_and_keeps_the_estimate(self):
        kourou = [-52.77, 5.24]   # the window holds an Ariane too, 4,000 NM from the area
        areas = [area(kourou, 303, 4077, "far")]
        r = rec(pad=kourou, az=38.3)
        before = dict(r["path"])
        self.assertEqual(self.run_one(r, areas), 0)
        self.assertEqual(r["path"], before)
        self.assertEqual(roles(r), {"far": "coincidence"})
        self.assertIn("NM from the pad", r["live"]["closures"][0]["why"])

    def test_a_time_only_area_off_the_expected_bearing_is_not_on_the_path(self):
        r = rec()
        self.assertEqual(self.run_one(r, [area(VANDENBERG, 250, 400, "off")]), 0)
        self.assertEqual(roles(r), {"off": "coincidence"})
        self.assertIn("off the launch's expected bearing", r["live"]["closures"][0]["why"])

    def test_a_time_only_area_with_no_expected_bearing_is_not_used(self):
        r = rec()
        r.pop("path")
        self.assertEqual(self.run_one(r, [area(VANDENBERG, 155, 400, "a")]), 0)
        self.assertNotIn("path", r)
        self.assertIn("no expected bearing", r["live"]["closures"][0]["why"])

    def test_time_and_place_sets_the_path_off_the_site_estimate(self):
        # Taiyuan's 255-degree drop zone (the Yaogan-50 launches) against a corridor estimate of 172.5
        taiyuan = [111.608, 38.849]
        a = area(taiyuan, 255, 188, "A6107/26 ZLHW")
        r = rec(pad=taiyuan, az=172.5, orbit="Not known")
        self.assertEqual(self.run_one(r, [a], {"A6107/26 ZLHW": "time and place"}), 1)
        self.assertAlmostEqual(r["path"]["az"], 255, delta=1)

    def test_areas_that_bend_give_a_path_through_them(self):
        jiuquan = [100.29, 40.96]
        areas = [area(jiuquan, 112, 506, "a"), area(jiuquan, 102, 1109, "b")]
        r = rec(pad=jiuquan, az=102.7)
        self.run_one(r, areas, {"a": "time and place", "b": "time and place"})
        self.assertEqual(len(r["path"]["via"]), 2)

    def test_an_area_at_the_pad_is_marked_and_sets_no_path(self):
        r = rec()
        before = dict(r["path"])
        self.assertEqual(self.run_one(r, [area(VANDENBERG, 0, 5, "pad", half=0.05)], {"pad": "time and place"}), 0)
        self.assertEqual(roles(r), {"pad": "pad"})
        self.assertEqual(r["path"], before)

    def test_a_net_known_only_to_the_day_ties_nothing(self):
        r = rec(net_precision="Day")
        self.assertEqual(self.run_one(r, [area(VANDENBERG, 155, 300, "a")], {"a": "time and place"}), 0)
        self.assertEqual(roles(r), {"a": "coincidence"})
        self.assertIn("known only to the day", r["live"]["closures"][0]["why"])

    def test_an_area_off_the_line_of_the_others_stays_a_coincidence(self):
        areas = [area(VANDENBERG, 155, 300, "a"), area(VANDENBERG, 156, 600, "b"), area(VANDENBERG, 215, 500, "side")]
        r = rec()
        self.run_one(r, areas, {k: "time and place" for k in ("a", "b", "side")})
        self.assertEqual(roles(r), {"a": "path", "b": "path", "side": "coincidence"})
        self.assertIn("off the line", next(c for c in r["live"]["closures"] if c["area"] == "side")["why"])

    def test_only_upcoming_records_change(self):
        r = rec(status="launched")
        self.assertEqual(self.run_one(r, [area(VANDENBERG, 155, 300, "a")]), 0)
        self.assertNotIn("live", r)

    def test_match_names_the_area_by_its_place_in_the_list(self):
        up = [{"id": "x", "name": "F9", "net": NET, "lat": VANDENBERG[1], "lon": VANDENBERG[0]}]
        late = {"start": "2026-11-23T12:00:00Z", "end": "2026-11-23T13:00:00Z"}
        areas = [area(VANDENBERG, 155, 100, "same", [late]), area(VANDENBERG, 155, 200, "same"),
                 area(VANDENBERG, 155, 300, "same")]
        self.assertEqual([m["area_i"] for m in live.match(up, areas, [], [])], [1, 2])

    def test_build_index_gives_history_and_live_the_same_path(self):
        up = {"id": "x", "name": "Falcon 9 | NROL", "net": NET, "net_precision": "Minute", "status": "Go",
              "provider_countries": ["US"], "vehicle": "Falcon 9", "mission": "NROL", "orbit": "SSO", "pad": "SLC-4E",
              "location": "Vandenberg SFB, CA, USA", "lat": VANDENBERG[1], "lon": VANDENBERG[0]}
        a = area(VANDENBERG, 190, 400, "a")
        ix = catalog.build_index({"events": []}, {"since": "2023-01-01", "sites": {}, "launches": [], "closures": []},
                                 [up], [], "2026-11-21T00:00:00Z",
                                 live={"matches": [row(0, a, "time and place")], "areas": [a]})
        r = next(x for x in ix["records"] if x["status"] == "upcoming")
        self.assertEqual(roles(r), {"a": "path"})
        self.assertAlmostEqual(r["path"]["az"], 190, delta=1)
        self.assertEqual(ix["counts"]["paths"]["live"], 1)


SCRIPT = """
import * as L from %s;
const closure = (i, role) => ({ i, role, area: "A" + i });
const path = { az: 155, nm: 400, basis: "b" };
const on = { id: "ll2:b", status: "upcoming", time: "2026-11-24T00:00:00Z", pad: [0, 0], path, live: { closures: [closure(1, "path"), closure(2, "pad"), closure(3, "coincidence")] } };
const soon = { id: "ll2:a", status: "upcoming", time: "2026-11-23T00:00:00Z", pad: [0, 0], path, live: { closures: [closure(1, "path")] } };
const none = { id: "ll2:c", status: "upcoming", time: "2026-11-22T00:00:00Z", pad: [0, 0], path, live: { closures: [closure(4, "coincidence")] } };
const bare = { id: "ll2:d", status: "upcoming", time: "2026-11-22T00:00:00Z", pad: [0, 0], path };
const flown = { ...on, id: "gcat:z", status: "launched" };
const tied = L.tiedAreas([on, soon, none, bare, flown]);
const week = (time, id, status = "launched") => ({ id, status, time });
const now = "2026-11-21T12:00:00Z";
const out = {
  has: [on, soon, none, bare, flown, null].map(L.hasLivePath),
  records: L.livePathRecords([on, none, soon]).map((r) => r.id),
  tied: [...tied.keys()].sort(),
  first: tied.get(1).map((r) => r.id),
  pad: tied.get(2).map((r) => r.id),
  past: L.pastWeek([week("2026-11-14T12:00:00Z", "edge"), week("2026-11-14T11:59:59Z", "old"), week("2026-11-21T04:20:00Z", "new"),
    week("2026-11-18T22:51:00Z", "mid"), week("2026-11-21T12:00:01Z", "later"), week("2026-11-20T00:00:00Z", "up", "upcoming"), { id: "no-time", status: "launched" }], now).map((r) => r.id),
  bad: L.pastWeek([week("2026-11-20T00:00:00Z", "x")], "not a date"),
  href: L.historyHref({ id: "ll2:7b d" }),
  grouped: L.groupMatches([
    { launch: "u", launch_name: "U", net: "2026-11-29T04:39:00Z", area: "nav", area_i: 0, level: "time and place", distance_nm: 287, azimuth: 154.3 },
    { launch: "u", launch_name: "U", net: "2026-11-29T04:39:00Z", area: "nav", area_i: 1, level: "time and place", distance_nm: 65, azimuth: 152.5 },
    { launch: "u", launch_name: "U", net: "2026-11-29T04:39:00Z", area: "nav", area_i: 2, level: "time", distance_nm: 360, azimuth: 155.1 },
    { launch: "c", launch_name: "C", net: "2026-11-29T03:50:00Z", area: "nav", area_i: 0, level: "time", distance_nm: 5592, azimuth: 40.8 },
    { launch: "c", launch_name: "C", net: "2026-11-29T03:50:00Z", area: "far", area_i: 3, level: "time", distance_nm: 8000, azimuth: 320, named: null, track: null },
    { launch: "c", launch_name: "C", net: "2026-11-29T03:50:00Z", area: "named", area_i: 4, level: "time", distance_nm: 8000, azimuth: 320, named: "C-1", named_by: "mission" },
    { launch: "c", launch_name: "C", net: "2026-11-29T03:50:00Z", area: "near", area_i: 5, level: "time", distance_nm: 900, azimuth: 120 },
  ], [{ label: "A" }, { label: "B" }, { label: "C" }, {}, {}, {}]).map((r) => [r.launch, r.area, r.level, r.parts.join(""), r.nm.join("-"), r.az.join("-"), r.area_is.join(","), r.also.join(","), r.far]),
};
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node is not installed")
class LivePathsJsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % json.dumps(LP)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise AssertionError(r.stderr)
        cls.o = json.loads(r.stdout)

    def test_a_path_needs_a_closure_on_it(self):
        self.assertEqual(self.o["has"], [True, True, False, False, False, False])
        self.assertEqual(self.o["records"], ["ll2:b", "ll2:a"])

    def test_tied_areas_are_those_on_a_path_or_at_its_pad(self):
        self.assertEqual(self.o["tied"], [1, 2])
        self.assertEqual(self.o["first"], ["ll2:a", "ll2:b"])   # soonest first: it sets the area's colour
        self.assertEqual(self.o["pad"], ["ll2:b"])

    def test_past_week_is_newest_first_and_bounded(self):
        self.assertEqual(self.o["past"], ["new", "mid", "edge"])
        self.assertEqual(self.o["bad"], [])

    def test_history_link_is_encoded(self):
        self.assertEqual(self.o["href"], "#history?sel=ll2%3A7b%20d")

    def test_matches_fold_by_notice_and_far_time_only_is_marked(self):
        """24 Nov 2026: NAVAREA XII 836/26's three parts were three rows (and three feed items sharing one id)."""
        g = {(r[0], r[1]): r for r in self.o["grouped"]}
        self.assertEqual(len(self.o["grouped"]), 5)
        self.assertEqual(g[("u", "nav")][2:], ["time and place", "ABC", "65-360", "152.5-155.1", "1,0,2", "", False])
        self.assertEqual(g[("c", "nav")][7:], ["U", True])     # time only, far, and the notice fits U in place
        self.assertTrue(g[("c", "far")][8])
        self.assertFalse(g[("c", "named")][8])                # a notice that names the launch never folds away
        self.assertFalse(g[("c", "near")][8])
        self.assertEqual([r[0] for r in self.o["grouped"]], ["c", "c", "c", "c", "u"])   # by NET


if __name__ == "__main__":
    unittest.main()
