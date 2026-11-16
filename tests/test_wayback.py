"""Internet Archive copies (launch/wayback.py, launch/ngawarn.py) and their joins (catalog.py). Offline; the pages
below are synthetic, trimmed to the shape of the archived FAA and NGA pages."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from launch import catalog, wayback  # noqa: E402
from test_catalog import NOW, SITES, gcat_rec  # noqa: E402

LIST = """<table>
<tr valign="top"><td><a href = "../save_pages/detail_5_1234.html">03/01/2024</a></td>
<td><a href = "../save_pages/detail_5_1234.html"><u>5/1234</u></a></td><td><a href="x">ZJX</a></td>
<td><a href="x">FL</a></td><td><a href = "../save_pages/detail_5_1234.html">SPACE OPERATIONS</a></td>
<td><a href="x">CAPE CANAVERAL, FL, Friday, March 01, 2024 UTC</a></td><td>zoom</td></tr>
<tr valign="top"><td><a href = "../save_pages/detail_5_2000.html">03/01/2024</a></td>
<td><a href="x">5/2000</a></td><td>ZDC</td><td>DC</td><td><a href="x">VIP</a></td><td>WASHINGTON</td><td></td></tr>
</table>"""

DETAIL = """<html><head><style>td {font-size: x-small}</style></head><body>
<table><tr><td>NOTAM Number :</td><td>FDC 5/1234</td></tr>
<tr><td>Issue Date :</td><td>February 27, 2024 at 1500 UTC</td></tr>
<tr><td>Location :</td><td>CAPE CANAVERAL, Florida</td></tr>
<tr><td>Beginning Date and Time :</td><td>March 01, 2024 at 0100 UTC</td></tr>
<tr><td>Ending Date and Time :</td><td>March 01, 2024 at 0500 UTC</td></tr>
<tr><td>Reason for NOTAM :</td><td>Space Operations Area</td></tr>
<tr><td>Type :</td><td>Space Operations</td></tr></table>
<p>Airspace Definition:</p><p>From: 28&#186;40'00"N 80&#186;40'00"W To: 28&#186;40'00"N 80&#186;20'00"W
To: 28&#186;20'00"N 80&#186;20'00"W To: 28&#186;20'00"N 80&#186;40'00"W</p>
<p>Operating Restrictions and Requirements</p><p>Point of Contact: A NAME TEL 555-0100</p>
<p>Email: EMAIL_HERE</p></body></html>"""
DETAIL = DETAIL.replace("EMAIL_HERE", "someone" + chr(64) + "example.gov")  # built here: no address in the file

NGA = {"broadcast-warn": [
    {"msgYear": 2023, "msgNumber": 1234, "navArea": "P", "issueDate": "090000Z MAR 2023",
     "text": "NORTH PACIFIC.\n1. ROCKET LAUNCHING 110100Z TO 110200Z MAR 23\n   IN AREA BOUND BY\n"
             "   18-00.00N 112-00.00E, 18-00.00N 113-00.00E,\n   17-00.00N 113-00.00E.\n2. CANCEL THIS MSG 110300Z MAR 23."},
    {"msgYear": 2023, "msgNumber": 1235, "navArea": "P", "issueDate": "090000Z MAR 2023",
     "text": "SOUTH CHINA SEA.\n1. GUNNERY EXERCISES 110100Z TO 110200Z MAR 23\n   IN AREA BOUND BY\n   18-00.00N 112-00.00E."}]}


class Pages(unittest.TestCase):
    def test_list_rows_keep_space_operations(self):
        rows = wayback.list_rows(LIST)
        self.assertEqual([r["detail"] for r in rows if wayback.is_space_ops(r)], ["detail_5_1234.html"])

    def test_detail_fields_and_area_without_contacts(self):
        d = wayback.parse_detail(DETAIL)
        self.assertEqual((d["number"], d["issued"], d["start"], d["end"], d["zone"]),
                         ("5/1234", "2024-02-27T15:00:00Z", "2024-03-01T01:00:00Z", "2024-03-01T05:00:00Z", "UTC"))
        self.assertEqual(d["type"], "Space Operations")
        self.assertEqual(len(d["areas"]), 1)
        self.assertEqual(d["areas"][0]["ring"][0], [-80.66667, 28.66667])
        self.assertNotIn("555", json.dumps(d))
        self.assertNotIn("@", json.dumps(d))

    def test_daily_window(self):
        page = DETAIL.replace("March 01, 2024 at 0100 UTC", "January 22, 2025 UTC 0445-1415 Daily").replace(
            "March 01, 2024 at 0500 UTC", "February 08, 2025 UTC")
        d = wayback.parse_detail(page)
        self.assertEqual((d["start"], d["end"], d["schedule"]),
                         ("2025-01-22T04:45:00Z", "2025-02-08T14:15:00Z", "0445-1415 daily"))

    def test_local_zone_converted(self):
        self.assertEqual(wayback._when("March 01, 2024 at 0100 EST"), ("2024-03-01T06:00:00Z", "EST"))
        self.assertEqual(wayback._when("March 01, 2024 at 0100 XYZ"), (None, "XYZ"))

    def test_nga_on_orbits_rule(self):
        ws = wayback.nga_warnings(NGA)
        self.assertEqual([w["id"] for w in ws], ["HYDROPAC 1234/23"])  # gunnery is left out
        self.assertEqual(ws[0]["windows"], [{"start": "2023-03-11T01:00:00Z", "end": "2023-03-11T02:00:00Z"}])


class Fetch(unittest.TestCase):
    def test_paced_cached_and_resumable(self):
        calls = []

        def opener(url):
            calls.append(url)
            if "cdx" in url and "list.html" in url:
                return b"20240301000000 http://tfr.faa.gov/tfr2/list.html\n"
            if "showNumPages" in url:
                return b"1\n"
            if "cdx" in url and "save_pages" in url:
                return b"http://tfr.faa.gov/save_pages/detail_5_1234.html 20240301010000\n"
            if "cdx" in url:
                return b"20230309000000 https://msi.nga.mil/api/publications/broadcast-warn?output=json\n"
            if "list.html" in url:
                return LIST.encode()
            if "detail_5_1234" in url:
                return DETAIL.encode()
            if "broadcast-warn" in url:
                return json.dumps(NGA).encode()
            if "nasaspaceflight" in url:
                raise AssertionError("never read")
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            r1 = wayback.fetch(Path(tmp), opener=opener, log=lambda m: None, pause=0)
            n1 = len(calls)
            r2 = wayback.fetch(Path(tmp), opener=opener, log=lambda m: None, pause=0)
            self.assertEqual(len(calls), n1)  # nothing fetched twice
            self.assertEqual((r1["space_ops_tfrs"], r1["detail_pages"], r1["nga_fetched"]), (1, 1, 1))
            self.assertEqual(r2["requests"], 0)
            doc = wayback.build(Path(tmp))
        self.assertEqual([t["number"] for t in doc["tfrs"]], ["5/1234"])
        # the detail page is asked for at the list capture's time: the archive serves its nearest copy
        self.assertTrue(doc["tfrs"][0]["source"].startswith("https://web.archive.org/web/20240301000000/"))
        self.assertTrue(doc["tfrs"][0]["detail"])
        self.assertEqual([w["id"] for w in doc["nga"]], ["HYDROPAC 1234/23"])
        self.assertTrue(all("WEB" not in u for u in calls))
        with self.assertRaises(ValueError):
            wayback.Archive(Path(tempfile.gettempdir()) / "wb-never", opener=opener, pause=0).get(
                "https://web.archive.org/web/2020id_/https://forum.nasaspaceflight.com/")


    def test_another_years_page_is_refused(self):
        def opener(url):
            if "cdx" in url and "list.html" in url:
                return b"20240301000000 http://tfr.faa.gov/tfr2/list.html\n"
            if "cdx" in url:
                return b""
            if "list.html" in url:
                return LIST.encode()
            if "detail_5_1234" in url:  # the same page name, used for a 2015 TFR
                return DETAIL.replace("2024", "2015").encode()
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            wayback.fetch(Path(tmp), opener=opener, log=lambda m: None, pause=0)
            doc = wayback.build(Path(tmp))
        self.assertEqual((doc["tfr_pages_refused"], doc["tfrs"][0]["detail"], doc["tfrs"][0]["list_date"]),
                         (1, False, "2024-03-01"))


class Joins(unittest.TestCase):
    def test_tfr_and_nga_join_by_window_and_place(self):
        cape = gcat_rec("2024-040", "2024-03-01T02:00:00Z", "Falcon 9", "Starlink", "CC", country="US")
        wen = gcat_rec("2023-030", "2023-03-11T01:30:00Z", "Chang Zheng 7A", "Y", "WEN")
        tfr = {"id": "faa-tfr:5/1234", "number": "5/1234", "start": "2024-03-01T01:00:00Z", "end": "2024-03-01T05:00:00Z",
               "location": "CAPE CANAVERAL", "reason": None, "source": "https://web.archive.org/web/1/x",
               "areas": [{"kind": "polygon", "ring": [[-80.7, 28.7], [-80.3, 28.7], [-80.3, 28.3], [-80.7, 28.3], [-80.7, 28.7]]}]}
        standing = dict(tfr, id="faa-tfr:1/4189", number="1/4189", start="2024-02-01T00:00:00Z", end="2024-03-31T00:00:00Z")
        doc = {"source": "s", "rule": "r", "tfrs": [tfr, standing],
               "nga": [dict(w, source="https://web.archive.org/web/2/y") for w in wayback.nga_warnings(NGA)]}
        ix = catalog.build_index({"events": []}, {"since": "2023-01-01", "sites": SITES, "launches": [cape, wen],
                                                   "closures": []}, [], [], NOW, None, None, doc)
        r = {x["id"]: x for x in ix["records"]}
        self.assertEqual([n["id"] for n in r["gcat:2024-040"]["archive_notices"]], ["faa-tfr:5/1234"])
        self.assertIn("wayback", r["gcat:2024-040"]["sources"])
        self.assertEqual([n["id"] for n in r["gcat:2023-030"]["archive_notices"]], ["HYDROPAC 1234/23"])
        c = ix["counts"]["wayback"]
        self.assertEqual((c["tfr_joined"], c["nga_joined"]), (1, 1))
        self.assertEqual(c["unjoined_why"], {"tfr: window over 7 days": 1})


if __name__ == "__main__":
    unittest.main()
