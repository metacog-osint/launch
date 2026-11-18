"""Joey0609/notams import (launch/joey.py) and its notices on the History tab's records (catalog.py). Offline.
The NOTAM texts below are synthetic, written in the shape of the source's rows."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from launch import catalog, joey  # noqa: E402
from test_catalog import NOW, SITES, chart_event, gcat_rec, nfc_launch, nn, ring  # noqa: E402

CN_SHORT = """A1001/25 NOTAMN
Q) ZLHW/QRDCA/IV/BO/W/000/999/4000N10000E020
A) ZLHW B) 2503011000 C) 2503011040
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N400000E1000000-N400000E1010000-N390000E1010000-N390000E1000000
BACK TO START.VERTICAL LIMITS:SFC-UNL.
F) SFC G) UNL

CREATED: 27 FEB 2025 03:08
SOURCE: ZBBBYNYX"""

CN_BACKUP_DAYS = """A1002/25 NOTAMN
Q) ZLHW/QRTCA/IV/BO/W/000/999/4000N10000E020
A) ZLHW B) 2503012312 C) 2503030834
D) 2312-2346 01, 0159-0233 0751-0834 03
E) A TEMPORARY RESTRICTED AREA ESTABLISHED BOUNDED BY:
N400000E1000000-N400000E1010000-N390000E1010000-N390000E1000000
BACK TO START.
F) GND G) UNL"""

SUMMER = """A1003/25 NOTAMN
Q) ZBPE/QRPCA/IV/BO/W/000/999/3950N11930E005
A) ZBPE B) 2506301600 C) 2508311559
E) A TEMPORARY PROHIBITED AREA ESTABLISHED BOUNDED BY:
N395600E1192100-N395600E1193300-N395100E1193900-N395100E1192100 BACK TO START.
F) GND G) UNL"""

GA_BAN = """A1004/25 NOTAMN
Q) ZGZU/QRTCA/IV/BO/W/000/999/2237N11358E108
A) ZGZU B) 2503010000 C) 2503010300
E) A TEMPORARY RESTRICTED AREA ESTABLISHED,THE AREA WITHIN A CIRCLE CENTERED AT N223637E1135758 WITH RADIUS OF
200KM. ALL GENERAL AVIATION FLIGHT ACTIVITIES ARE PROHIBITED WITHOUT PRIOR APPROVAL.
F) SFC G) UNL"""

LONG_LOW = """A1005/25 NOTAMN
Q) ZGZU/QRTCA/IV/NBO/W/000/187/2152N11314E025
A) ZGZU B) 2503010145 C) 2503050620
E) A TEMPORARY RESTRICTED AREA ESTABLISHED BOUNDED BY:
N220000E1130000-N220000E1131000-N213000E1131000-N213000E1130000 BACK TO START.
F) SFC G) 5700M AMSL"""

DOWNRANGE = """B2001/25 NOTAMN
Q) RPHI/QWMLW/IV/BO/W/000/999/1500N12500E050
A) RPHI B) 2503011010 C) 2503011100
E) SPECIAL OPS (AEROSPACE FLT ACT) WILL BE CONDUCTED BY CHINA. EST FALL AREA FOR UNBURNED DEBRIS WI:
150000N 1250000E - 150000N 1260000E - 140000N 1260000E - 140000N 1250000E - 150000N 1250000E.
F) SFC G) UNL"""

CANCEL = """A1006/25 NOTAMC A1001/25
Q) ZLHW/QRDCA/IV/BO/W/000/999/4000N10000E020
A) ZLHW B) 2503010900
E) REF A1001/25 CANCELLED."""


def month(*texts, codes=None, geometry=None):
    n = len(texts)
    return {"NUM": n, "CODE": codes or [t.split()[0] for t in texts], "TIME": [""] * n, "PLATID": [str(i) for i in range(n)],
            "RAWMESSAGE": list(texts), "ALTITUDE": ["0 ~ INF"] * n, "GEOMETRY": geometry or [""] * n,
            "CLASSIFY": {}, "classify": ["c1"] * n}


def kept(text):
    return joey.notice(joey.rows(month(text))[0])


class Filter(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(kept(CN_SHORT)["kept"], "cn-area")
        self.assertEqual(kept(CN_BACKUP_DAYS)["kept"], "cn-area")  # 34-minute periods over three days
        self.assertEqual(kept(DOWNRANGE)["kept"], "words")
        for t in (SUMMER, GA_BAN, LONG_LOW, CANCEL):
            self.assertIsNone(kept(t), t.split()[0])

    def test_fields_and_no_source_line(self):
        n = kept(CN_SHORT)
        self.assertEqual((n["number"], n["fir"], n["start"], n["end"], n["created"]),
                         ("A1001/25", "ZLHW", "2025-03-01T10:00:00Z", "2025-03-01T10:40:00Z", "2025-02-27T03:08:00Z"))
        self.assertEqual(n["ring_basis"], "text")
        self.assertEqual(len(n["rings"]), 1)
        self.assertNotIn("SOURCE", json.dumps(n))
        self.assertNotIn("ZBBBYNYX", json.dumps(n))
        d = kept(DOWNRANGE)
        self.assertEqual((d["issuing_state"], d["named_states"]), ("PH", ["CN"]))

    def test_geometry_fallback_and_parts(self):
        no_coords = DOWNRANGE.replace("150000N 1250000E - 150000N 1260000E - 140000N 1260000E - 140000N 1250000E - "
                                      "150000N 1250000E.", "SEE CHART.")
        r = joey.rows(month(no_coords, codes=["B2001/25_AREA1"],
                            geometry=["PATH|M=N150000E1250000|L=N150000E1260000|L=N140000E1260000|Z"]))[0]
        n = joey.notice(r)
        self.assertEqual((n["ring_basis"], n["part"]), ("geometry", "AREA1"))
        self.assertEqual(n["rings"][0][0], [125.0, 15.0])
        self.assertEqual(n["rings"][0][0], n["rings"][0][-1])
        c = joey.geometry_ring("CIRCLE|C=N223637E1135758|R=200KM")
        self.assertGreater(len(c), 30)

    def test_build_dedupes_by_number_and_firs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / joey.DB
            db.mkdir(parents=True)
            (db / "2025-02.json").write_text(json.dumps(month(CN_SHORT, SUMMER)), encoding="utf-8")
            (db / "2025-03.json").write_text(json.dumps(month(CN_SHORT, DOWNRANGE)), encoding="utf-8")
            (db / "active_notams.json").write_text("{}", encoding="utf-8")
            doc = joey.build(Path(tmp))
        self.assertEqual([n["id"] for n in doc["notices"]], ["joey:A1001-25-ZLHW", "joey:B2001-25-RPHI"])
        self.assertEqual((doc["counts"]["rows"], doc["counts"]["kept"], doc["counts"]["duplicates"]), (4, 2, 1))
        self.assertEqual(doc["commit"], joey.SHA)


def jn(nid, number, fir, start, end, rings, issuing="CN", named=(), locations=None):
    return {"id": nid, "number": number, "part": None, "type": "new", "fir": fir, "locations": locations or [fir],
            "q_code": "QRDCA", "start": start, "end": end, "schedule": None, "lower": "SFC", "upper": "UNL",
            "issuing_state": issuing, "named_states": list(named), "kept": "cn-area", "rings": rings,
            "ring_basis": "text", "created": None, "group": "c1", "text": "A TEMPORARY DANGER AREA"}


class OnRecords(unittest.TestCase):
    def build(self, events, launches, notices, nfc_launches=()):
        jd = {"source": "github.com/Joey0609/notams", "commit": "y" * 40, "licence": "MIT", "attribution": "Joey",
              "rule": "r", "notices": notices}
        nd = {"source": "github.com/mikezang/NotamForChina", "commit": "x" * 40, "licence": "Apache-2.0",
              "attribution": "NotamForChina", "launches": list(nfc_launches)} if nfc_launches else None
        ix = catalog.build_index({"events": events}, {"since": "2023-01-01", "sites": SITES, "launches": launches,
                                                       "closures": []}, [], [], NOW, nd, jd)
        return ix, {r["id"]: r for r in ix["records"]}

    def test_window_and_place(self):
        g = gcat_rec("2025-050", "2025-03-01T10:10:00Z", "Chang Zheng 7A", "Y", "WEN")
        g2 = gcat_rec("2025-051", "2025-03-01T10:20:00Z", "Falcon 9", "Z", "CC", country="US")
        near = jn("joey:1", "A1001/25", "ZJSA", "2025-03-01T10:00:00Z", "2025-03-01T10:40:00Z", [ring(112, 18)])
        down = jn("joey:2", "B2001/25", "RPHI", "2025-03-01T10:05:00Z", "2025-03-01T10:50:00Z", [ring(125, 15)],
                  issuing="PH", named=["CN"])
        late = jn("joey:3", "A1002/25", "ZJSA", "2025-03-01T06:00:00Z", "2025-03-01T08:00:00Z", [ring(112, 18)])
        far = jn("joey:4", "A1003/25", "ZJSA", "2025-03-01T10:00:00Z", "2025-03-01T10:40:00Z", [ring(-30, -60)])
        ix, r = self.build([], [g, g2], [near, down, late, far])
        rec = r["gcat:2025-050"]
        self.assertIn("joey", rec["sources"])
        self.assertEqual(sorted(n["id"] for n in rec["joey_notices"]), ["joey:1", "joey:2"])
        self.assertNotIn("joey_notices", r["gcat:2025-051"])  # CHINA named: not the US launch in the same window
        self.assertEqual(rec["joey_notices"][0]["join"]["by"], "window")
        self.assertIn("closure area", rec["path"]["basis"])  # Joey's areas feed the path estimate
        c = ix["counts"]["joey"]
        self.assertEqual((c["by_window"], c["unjoined"]), (2, 2))  # 8 h too early (tolerance 2 h); 5,000 NM out
        self.assertEqual(ix["joey"]["licence_file"], catalog.JOEY_LICENCE_FILE)

    def test_by_window_only_an_orbital_launch(self):
        # A missile test nearer the area, in the same window, takes nothing from the orbital launch.
        g = gcat_rec("2025-060", "2025-04-01T10:10:00Z", "Chang Zheng 7A", "Y", "WEN")
        m = dict(gcat_rec("2025-M60", "2025-04-01T10:15:00Z", "DF-31", "Test", "WEN"), kind="missile", category="Test")
        n = jn("joey:9", "A1009/25", "ZJSA", "2025-04-01T10:00:00Z", "2025-04-01T10:40:00Z", [ring(111, 19)])
        ix, r = self.build([], [m, g], [n])
        self.assertEqual([x["id"] for x in r["gcat:2025-060"].get("joey_notices") or []], ["joey:9"])
        self.assertNotIn("joey_notices", r["gcat:2025-M60"])

    def test_a_long_window_joins_only_one_launch(self):
        a = gcat_rec("2025-060", "2025-04-02T10:00:00Z", "Chang Zheng 7A", "Y", "WEN")
        b = gcat_rec("2025-061", "2025-04-09T10:00:00Z", "Chang Zheng 8", "Y", "WEN")
        long = jn("joey:5", "A2000/25", "ZJSA", "2025-04-01T00:00:00Z", "2025-04-20T00:00:00Z", [ring(112, 18)])
        ix, r = self.build([], [a, b], [long])
        self.assertEqual(ix["counts"]["joey"]["unjoined_why"], {"several launches in the window": 1})

    def test_charted_text_first_then_joey_then_nfc(self):
        pad = [110.95, 19.61]
        ev = chart_event("hist:t", "2025-03-01T10:00:00Z", "LM-7A", "Y", pad,
                         areas=[{"ring": ring(112, 18), "notam": "A0500/25", "centroid": [112.25, 17.75]}])
        ev["notams"] = [{"number": "A0500/25", "q": {"fir": "ZJSA"}, "locations": ["ZJSA"], "text": "x"}]
        g = gcat_rec("2025-050", "2025-03-01T10:00:00Z", "Chang Zheng 7A", "Y", "WEN")
        x = nfc_launch("nfc:6", "2025-03-01T10:00:00Z", "长征七号甲", "Wenchang",
                       [nn("ZJSA", "A0501/25", rg=ring(113.01, 17))], gcat="2025-050")
        # the charted NOTAM, out of every window: still joins, by its number and FIR
        charted = jn("joey:a", "A0500/25", "ZJSA", "2025-02-01T00:00:00Z", "2025-02-01T01:00:00Z", [ring(112.01, 18)])
        other_fir = jn("joey:b", "A0500/25", "ZGZU", "2025-02-01T00:00:00Z", "2025-02-01T01:00:00Z", [ring(116, 20)])
        nfc_too = jn("joey:c", "A0501/25", "ZJSA", "2025-02-01T00:00:00Z", "2025-02-01T01:00:00Z", [ring(113, 17)])
        ix, r = self.build([ev], [g], [charted, other_fir, nfc_too], [x])
        rec = r["gcat:2025-050"]  # the charted event's notices are on the launch it joined
        by = {n["id"]: n for n in rec["joey_notices"]}
        self.assertTrue(by["joey:a"]["chart"])
        self.assertNotIn("rings", by["joey:a"])  # the charted area is drawn; Joey's is the check
        self.assertNotIn("text", by["joey:a"])  # the charted copy carries the text
        self.assertLess(by["joey:a"]["gap_nm"], catalog.NFC_AGREE_NM)
        self.assertNotIn("joey:b", by)  # the same number in another FIR is another NOTAM
        self.assertTrue(by["joey:c"]["rings"])  # Joey's area is drawn ...
        n = next(n for n in rec["nfc_notices"] if n["number"] == "A0501/25")
        self.assertTrue(n["joey"])  # ... and NotamForChina's is the check under it
        self.assertNotIn("ring", n)
        self.assertLess(n["gap_nm"], catalog.NFC_AGREE_NM)
        c = ix["counts"]["joey"]
        self.assertEqual((c["by_notam_chart"], c["by_notam_nfc"], c["unjoined"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
