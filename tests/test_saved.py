"""site_src/saved.js (notices saved on the Paste tab and their join on the History tab), run in Node. Skipped where
Node is not installed. Made-up notices only."""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAVED = (ROOT / "site_src" / "saved.js").as_uri()
NODE = shutil.which("node")

SCRIPT = """
import * as S from %s;
const mem = {}; const st = { getItem: (k) => mem[k] ?? null, setItem: (k, v) => { mem[k] = v; } };
const bad = { getItem: () => { throw new Error("off"); }, setItem: () => { throw new Error("off"); } };
const txt = (num, b, c, q) => `${num} NOTAMN\\nQ) ZZZZ/QRDCA/IV/BO/W/000/999/${q || "3000N12300E050"}\\nA) ZZZZ B) ${b} C) ${c}\\nE) MADE-UP DANGER AREA FOR A TEST.\\nF) SFC G) UNL`;
const out = {};
out.same = S.idOf(txt("A0001/26", "2601010000", "2601010200")) === S.idOf("  " + txt("A0001/26", "2601010000", "2601010200").replace(/\\n/g, "\\n\\n"));
const e1 = S.entry(txt("A0001/26", "2601010000", "2601010200"), "2026-01-01T00:00:00Z");
let list = S.add([], [e1, e1]);
out.dedupe = list.length;
out.stored = S.store(list, st); out.loaded = S.load(st).length; out.badLoad = S.load(bad).length; out.badStore = S.store(list, bad);
out.roundtrip = S.fromFile(S.toFile(list)).map((x) => x.id === e1.id);
const n1 = S.read(e1);
out.read = { number: n1.number, fir: n1.fir, start: n1.start, end: n1.end, rings: n1.rings.length };
const rec = (id, t, pad, kind, extra) => ({ id, status: "launched", time: t, pad, kind: kind || "Orbital", sources: ["gcat"], ...(extra || {}) });
const recs = [
  rec("near", "2026-01-01T01:00:00Z", [123.5, 30.5]),
  rec("far", "2026-01-01T01:00:00Z", [-80.6, 28.5]),
  rec("combat", "2026-01-01T01:10:00Z", [123.4, 30.4], "Combat launch"),
  rec("bynum", "2025-06-01T00:00:00Z", [0, 0], "Orbital", { joey_notices: [{ number: "B0002/26", fir: "ZZZZ" }] }),
];
const nums = (r) => (r.joey_notices || []).map((n) => ({ number: n.number, firs: [n.fir] }));
const xs = [
  n1,                                                                              // window and place: near
  S.read(S.entry(txt("B0002/26", "2601050000", "2601050100"))),                    // by number
  S.read(S.entry(txt("C0003/26", "2603010000", "2603010100"))),                    // nothing in its window
  S.read(S.entry(txt("D0004/26", "2601010000", "2601200000"))),                    // 19 days: only near qualifies
  S.read(S.entry(txt("E0005/26", "2601010300", "2601010400"))),                    // launch 2 h before the window: within tolerance
];
const j = S.join(xs, recs, nums);
out.join = Object.fromEntries([...j.byRecord].map(([k, v]) => [k, v.map((x) => [x.number, x.join.by])]));
out.own = j.own.map((r) => [r.id === xs[2].id, r.status, r.sources, r.time, !!r.pad]);
out.nm = j.byRecord.get("near")[0].join.nm;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node is not installed")
class SavedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT % json.dumps(SAVED)],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        if r.returncode:
            raise AssertionError(r.stderr)
        cls.out = json.loads(r.stdout)

    def test_storage(self):
        o = self.out
        self.assertTrue(o["same"])                       # whitespace does not change a notice's id
        self.assertEqual(o["dedupe"], 1)
        self.assertEqual((o["stored"], o["loaded"]), (True, 1))
        self.assertEqual((o["badLoad"], o["badStore"]), (0, False))  # storage off: empty, and saving says so
        self.assertEqual(o["roundtrip"], [True])

    def test_read(self):
        self.assertEqual(self.out["read"], {"number": "A0001/26", "fir": "ZZZZ", "start": "2026-01-01T00:00:00Z",
                                            "end": "2026-01-01T02:00:00Z", "rings": 1})

    def test_join(self):
        o = self.out
        self.assertEqual(o["join"], {"near": [["A0001/26", "window"], ["D0004/26", "window"], ["E0005/26", "window"]],
                                     "bynum": [["B0002/26", "notam"]]})
        self.assertEqual(o["own"], [[True, "notice", ["saved"], "2026-03-01T00:00:00Z", True]])
        self.assertEqual(o["nm"], 0)                     # the pad lies inside the 50 NM area


if __name__ == "__main__":
    unittest.main()
