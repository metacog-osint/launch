"""NotamForChina import (launch/nfc.py): names, maps, the sheet, the merge and the join to GCAT. Offline."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import nfc  # noqa: E402

MAP = """<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>ZJSA/A0535/24</name><Polygon><outerBoundaryIs><LinearRing><coordinates>110,19,0 111,19,0 111,18,0 110,19,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>ZGZU/ZSHA</name><Polygon><outerBoundaryIs><LinearRing><coordinates>112,20,0 113,20,0 113,19,0 112,20,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>1st Stage</name><Polygon><outerBoundaryIs><LinearRing><coordinates>114,21,0 115,21,0 115,20,0 114,21,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>文昌12.1°轨道</name><LineString><coordinates>110.95,19.61,0 125,5,0</coordinates></LineString></Placemark>
</Document></kml>"""
MAP_PATH = "notams/maps/04.文昌/05.长征八号/2024年03月20日08时31分文昌长征八号.kml"


def workbook(rows: list[list[str]]) -> bytes:
    """A minimal .xlsx holding nfc.SHEET; every cell an inline number or a shared string."""
    shared, xml_rows = [], []
    for i, row in enumerate(rows, 1):
        cells = []
        for j, v in enumerate(row):
            if v == "":
                continue
            ref = f"{'ABCDEFGHIJKLM'[j]}{i}"
            try:
                float(v)
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            except ValueError:
                shared.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
        xml_rows.append(f'<row r="{i}">{"".join(cells)}</row>')
    m = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {m} {r}><sheets><sheet name="{nfc.SHEET}" sheetId="1" r:id="rId1"/>'
                                      f'</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {m}>' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {m}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


# 2024-03-20 00:31 UTC is serial 45371.021527...; 08:31 Beijing time on the same day is 45371.354861...
SHEET_ROWS = [["火箭年間统计", "发射地", "FIR"], ["", "", "Location", "Number", "Start", "End"],
              ["长征八号", "文昌", "ZJSA", "A0535/24", "45371.0125", "45371.0333", "", "", "", "", "", "", "45371.354861111"],
              ["", "", "RPHI/KZAK", "B0926/24", "45371.0131", "45371.0402"],
              [],
              ["快舟一号甲", "酒泉", "ZLHW", "", "45000.1", "45000.12", "", "", "", "", "", "", "45000.43"]]


class Names(unittest.TestCase):
    def test_vehicles(self):
        for zh, en in [("长征二号丙", "LM-2C"), ("长征八号甲", "LM-8A"), ("长征十二号", "LM-12"), ("快舟十一号", "KZ-11"),
                       ("谷神星一号海", "Ceres-1S"), ("长征二号丙 / 远征一号商", "LM-2C"), ("未知", None),
                       ("长征二号己", "LM-2F"), ("长征二号F", "LM-2F"), ("朱雀二号Ｅ", "ZQ-2E")]:
            self.assertEqual(nfc.vehicle(zh), en, zh)

    def test_sites(self):
        self.assertEqual([nfc.site(s) for s in ("01.酒泉", "文昌", "黄海", "?")], ["Jiuquan", "Wenchang", "sea", None])


class Map(unittest.TestCase):
    def test_one_launch_per_file_in_utc(self):
        m = nfc.parse_map(MAP_PATH, MAP.encode("utf-8"))
        self.assertEqual((m["time"], m["site"], m["vehicle"]), ("2024-03-20T00:31:00Z", "Wenchang", "LM-8"))
        self.assertEqual([(a["fir"], a["number"], a["label"]) for a in m["areas"]],
                         [("ZJSA", "A0535/24", None), ("ZGZU/ZSHA", None, None), (None, None, "1st Stage")])
        self.assertEqual(len(m["paths"]), 1)

    def test_an_unknown_time_keeps_the_date_only(self):
        m = nfc.parse_map(MAP_PATH.replace("08时31分", "??时??分"), MAP.encode("utf-8"))
        self.assertEqual((m["time"], m["date"]), (None, "2024-03-20"))

    def test_a_kmz_is_read(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("doc.kml", MAP)
        self.assertEqual(len(nfc.parse_map(MAP_PATH[:-1] + "z", buf.getvalue())["areas"]), 3)


class Sheet(unittest.TestCase):
    def test_blocks_firs_and_windows(self):
        s = nfc.parse_sheet(workbook(SHEET_ROWS))
        self.assertEqual(len(s), 2)
        self.assertEqual((s[0]["vehicle"], s[0]["site"], s[0]["time"]), ("LM-8", "Wenchang", "2024-03-20T00:31:00Z"))
        self.assertEqual([(n["fir"], n["number"]) for n in s[0]["notices"]],
                         [("ZJSA", "A0535/24"), ("RPHI", "B0926/24"), ("KZAK", "B0926/24")])
        self.assertEqual(s[0]["notices"][0]["start"], "2024-03-20T00:18:00Z")
        self.assertIsNone(s[1]["notices"][0]["number"])


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        src = Path(self.tmp.name)
        (src / MAP_PATH).parent.mkdir(parents=True)
        (src / MAP_PATH).write_text(MAP, encoding="utf-8")
        (src / nfc.WORKBOOK).parent.mkdir(parents=True)
        (src / nfc.WORKBOOK).write_bytes(workbook(SHEET_ROWS))
        self.doc = nfc.build(src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_map_and_sheet_merge_even_at_the_same_minute(self):
        # the map and the sheet give the same minute: a zero-hour difference is a match (it once read as false)
        L = self.doc["launches"]
        self.assertEqual(len(L), 2)
        lm8 = next(x for x in L if x["vehicle"] == "LM-8")
        self.assertEqual(lm8["from"], ["map", "sheet"])
        zjsa = next(n for n in lm8["notices"] if n["number"] == "A0535/24")
        self.assertTrue(zjsa["ring"] and zjsa["start"])  # the charted area gains the sheet's window
        self.assertEqual(self.doc["licence"], "Apache-2.0")
        self.assertIn("mikezang", self.doc["attribution"])

    def test_join_to_gcat_by_site_and_time(self):
        led = [{"tag": "2024-060", "time": "2024-03-20T00:31:30Z", "country": "CN", "site_code": "WEN"},
               {"tag": "2024-061", "time": "2024-03-20T00:40:00Z", "country": "CN", "site_code": "JQ"},
               {"tag": "2024-062", "time": "2024-03-20T00:31:00Z", "country": "US", "site_code": "CC"}]
        self.assertEqual(nfc.join(self.doc, led)["joined_to_gcat"], 1)
        self.assertEqual(next(x for x in self.doc["launches"] if x["vehicle"] == "LM-8")["gcat"], "2024-060")


class CommittedFile(unittest.TestCase):
    def test_it_carries_its_licence_and_only_names_numbers_times_and_shapes(self):
        p = ROOT / "history" / "nfc.json"
        if not p.exists():
            self.skipTest("history/nfc.json not built")
        doc = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual((doc["licence"], doc["commit"]), ("Apache-2.0", nfc.SHA))
        keys = {"id", "vehicle", "vehicle_zh", "site", "site_zh", "time", "date", "notices", "paths", "from", "gcat"}
        nkeys = {"fir", "number", "label", "start", "end", "ring"}
        for x in doc["launches"]:
            self.assertLessEqual(set(x), keys)
            for n in x["notices"]:
                self.assertLessEqual(set(n), nkeys)


if __name__ == "__main__":
    unittest.main()
