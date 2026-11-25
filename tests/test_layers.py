"""The Live tab's layers and filters (site_src/layers.js) and its upcoming-launch board (site_src/board.js), run
in Node (25 Nov 2026)."""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LY = (ROOT / "site_src" / "layers.js").as_uri()
BD = (ROOT / "site_src" / "board.js").as_uri()
NODE = shutil.which("node")

SCRIPT = r"""
const L = await import(%s), B = await import(%s);
const now = "2026-11-25T12:00:00Z";
const D = L.parse("");
const s = (o) => ({ ...L.parse(""), ...o });
const area = (o) => ({ source: "faa-nms", windows: [{ start: "2026-11-25T00:00:00Z", end: "2026-11-25T18:00:00Z" }], ...o });
const later = area({ windows: [{ start: "2026-11-30T00:00:00Z", end: "2026-11-30T02:00:00Z" }] });
const out = {
  dflt: D, dq: L.query(D),
  parsed: L.parse("show=recent,paths,bogus&src=tfr&cc=cn,ru&within=3"),
  q: L.query(L.parse("show=recent,paths,bogus&src=tfr&cc=cn,ru&within=3")),
  none: L.parse("show=none"), noneQ: L.query(s({ show: [] })), junk: L.parse("show=x&cc=&within=5"), w14: L.parse("within=14").within, w0q: L.query(s({ within: 14 })),
  kinds: [{ source: "faa-tfr" }, { source: "faa-nms" }, { source: "cordon-navwarn" }, {}].map(L.srcKind),
  groups: [L.areaGroup({ state: "CN" }, [{ actor: "US" }]), L.areaGroup({ source: "faa-tfr" }, []), L.areaGroup({ state: "RU" }, []), L.areaGroup({ state: "JP" }), L.areaGroup({})],
  shown: [
    L.areaShown(area({}), [], D, now),
    L.areaShown(area({ off_live: "airdrop" }), [], D, now),
    L.areaShown(area({ off_live: "airdrop" }), [], s({ show: ["areas", "off"] }), now),
    L.areaShown(area({}), [], s({ show: ["paths"] }), now),
    L.areaShown(area({}), [], s({ src: ["tfr", "nga"] }), now),
    L.areaShown(area({ state: "CN" }), [], s({ cc: ["us"] }), now),
    L.areaShown(area({ state: "CN" }), [{ actor: "US" }], s({ cc: ["us"] }), now),
    L.areaShown(later, [], D, now),
    L.areaShown(later, [], s({ within: 3 }), now),
    L.areaShown(area({ windows: [{ start: "2026-11-20T00:00:00Z", end: "2026-11-21T00:00:00Z" }] }), [], D, now),
    L.areaShown(area({ windows: [] }), [], s({ within: 1 }), now),
    L.areaShown(area({ windows: [{ start: "2027-01-10T00:00:00Z", end: "2027-01-11T00:00:00Z" }] }), [], D, now),   // any time
    L.areaShown(later, [], s({ within: 14 }), now),
  ],
  launches: [
    L.launchShown("US", "2026-11-26T00:00:00Z", s({ within: 1 }), now),
    L.launchShown("US", "2026-11-27T00:00:00Z", s({ within: 1 }), now),
    L.launchShown("US", "2026-11-24T00:00:00Z", s({ within: 1 }), now),
    L.launchShown("JP", "2026-11-26T00:00:00Z", s({ cc: ["us", "cn", "ru"] }), now),
    L.launchShown(null, null, D, now),
    L.launchShown("US", "2026-12-30T00:00:00Z", D, now),
  ],
  recent: [L.recentShown({ actor: "CN" }, D), L.recentShown({ actor: "CN" }, s({ show: ["recent"] })), L.recentShown({ actor: "CN" }, s({ show: ["recent"], cc: ["us"] }))],
  sum: [L.summary(1, 1, 1, 1), L.summary(12, 65, 4, 10)],
};
const recs = [
  { id: "ll2:b", ll2: "b", status: "upcoming", time: "2026-11-27T00:00:00Z", actor: "US", site: "Vandenberg", ll2_status: "Go",
    live: { closures: [{ role: "path" }, { role: "path" }, { role: "pad" }, { role: "none", why: "x" }] } },
  { id: "ll2:a", ll2: "a", status: "upcoming", time: "2026-11-26T00:00:00Z", actor: "CN", pad_name: "LC-3", ll2_status: "TBC" },
  { id: "ll2:c", ll2: "c", status: "upcoming", time: null, actor: "RU" },
  { id: "ll2:old", ll2: "old", status: "launched", time: "2026-11-20T00:00:00Z" },
];
const sched = [
  { refs: { ll2: "b" }, net_changes: 4, net_moves: [{ at: "2026-11-24T00:00:00Z", from: "2026-11-26T00:00:00Z", to: "2026-11-27T02:00:00Z" }] },
  { refs: { ll2: "a" }, net_changes: 0, net_moves: [] },
];
const rows = B.boardRows(recs, sched);
out.board = rows.map((r) => [r.id, r.site, r.status, r.moves, r.path, r.pad, r.other, B.moveText(r), B.closureText(r)]);
out.bare = B.boardRows(recs, null).map((r) => [r.id, r.moves, B.moveText(r)]);
out.moves = [
  { moves: 1, lastMove: { from: "2026-11-26T00:00:00Z", to: "2026-11-26T00:40:00Z" } },
  { moves: 2, lastMove: { from: "2026-11-26T05:00:00Z", to: "2026-11-26T02:00:00Z" } },
  { moves: 3, lastMove: { from: "2026-11-26T00:00:00Z", to: "2026-11-28T00:00:00Z" } },
  { moves: 2, lastMove: { from: "bad", to: "2026-11-28T00:00:00Z" } },
].map(B.moveText);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node is not installed")
class LayersJsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % (json.dumps(LY), json.dumps(BD))],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise AssertionError(r.stderr)
        cls.o = json.loads(r.stdout)

    def test_the_default_is_areas_paths_and_pads_everywhere_for_14_days(self):
        self.assertEqual(self.o["dflt"], {"show": ["areas", "paths", "pads"], "src": ["notam", "nga", "tfr"],
                                          "cc": ["us", "cn", "ru", "other"], "within": 0})
        self.assertEqual(self.o["dq"], "")

    def test_the_address_round_trips_and_drops_unknown_names(self):
        self.assertEqual(self.o["parsed"], {"show": ["recent", "paths"], "src": ["tfr"], "cc": ["cn", "ru"], "within": 3})
        self.assertEqual(self.o["q"], "show=paths,recent&src=tfr&cc=cn,ru&within=3")   # canonical order
        self.assertEqual(self.o["none"]["show"], [])
        self.assertEqual(self.o["noneQ"], "show=none")
        self.assertEqual(self.o["junk"], self.o["dflt"])   # a mistyped address never hides everything
        self.assertEqual((self.o["w14"], self.o["w0q"]), (14, "within=14"))

    def test_source_and_country_of_an_area(self):
        self.assertEqual(self.o["kinds"], ["tfr", "notam", "nga", "nga"])
        self.assertEqual(self.o["groups"], ["us", "us", "ru", "other", "other"])   # a tied launch's country first

    def test_which_areas_show(self):
        self.assertEqual(self.o["shown"], [True, False, True, False, False, False, True, True, False, False, True, True, True])

    def test_which_launches_show(self):
        self.assertEqual(self.o["launches"], [True, False, True, False, True, True])
        self.assertEqual(self.o["recent"], [False, True, False])

    def test_summary_line(self):
        self.assertEqual(self.o["sum"], ["Showing 1 of 1 area and 1 of 1 scheduled launch on the map.",
                                         "Showing 12 of 65 areas and 4 of 10 scheduled launches on the map."])

    def test_board_rows_soonest_first_with_moves_and_closures(self):
        self.assertEqual(self.o["board"], [
            ["ll2:a", "LC-3", "TBC", 0, 0, 0, 0, "Not moved", "None"],
            ["ll2:b", "Vandenberg", "Go", 4, 2, 1, 1, "4 times; last 1 day 2 h later", "2 on the path, 1 at the pad, 1 elsewhere"],
            ["ll2:c", "", "", 0, 0, 0, 0, "Not moved", "None"],    # no NET: last
        ])
        self.assertEqual(self.o["bare"], [["ll2:a", 0, "Not moved"], ["ll2:b", 0, "Not moved"], ["ll2:c", 0, "Not moved"]])

    def test_move_text(self):
        self.assertEqual(self.o["moves"], ["Once; last 40 min later", "2 times; last 3 h earlier", "3 times; last 2 days later", "2 times"])


if __name__ == "__main__":
    unittest.main()
