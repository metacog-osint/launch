"""nsf.py (NotamForChina's list of forum thread links) and catalog.nsf_join(). Made-up titles and records, offline."""
import unittest

from launch import catalog, nsf

HTML = ("<H2>NSF Link List</H2>"
        "<a target=_blank href=https://forum.nasaspaceflight.com/index.php?topic=101.0;all>001: Page01: Sat-A - CZ-2C - JSLC - 05:28UTC, September 28, 2014</a><br>"
        "<a target=_blank href=https://forum.nasaspaceflight.com/index.php?topic=102.0;all>002: Page02: Alpha-B - CZ-11H - Yellow Sea - 4 July 2021</a><br>"
        "<a target=_blank href=https://forum.nasaspaceflight.com/index.php?topic=103.0;all>003: Page03: Station walk - 4 July 2021 (UTC)</a><br>"
        "<a target=_blank href=https://forum.nasaspaceflight.com/index.php?topic=104.0;all>004: Page04: Sat-C - ? - ? - 2024</a><br>"
        "<a target=_blank href=https://forum.nasaspaceflight.com/index.php?topic=101.0;all>duplicate</a><br>"
        "<a href=https://example.org/other>not the forum</a>"
        "<a target=_blank href=https://forum.nasaspaceflight.com/index.php?topic=105.0;all>005: Page05: Sat-D, Long March-4B, Taiyuan - December 9, 2013 (0326UTC)</a>")


def rec(i, t, veh, actor="CN", chart=None, payload=None):
    return {"id": i, "time": t, "vehicle": veh, "actor": actor, "status": "launched", "payload": payload,
            **({"chart": chart} if chart else {})}


class NsfTest(unittest.TestCase):
    def test_parse(self):
        ls = nsf.parse(HTML)
        self.assertEqual([x["topic"] for x in ls], ["101", "102", "103", "104", "105"])  # one per thread, forum only
        self.assertEqual(ls[0]["url"], "https://forum.nasaspaceflight.com/index.php?topic=101.0")
        self.assertEqual(ls[0]["title"], "Sat-A - CZ-2C - JSLC - 05:28UTC, September 28, 2014")
        self.assertEqual({k: ls[0][k] for k in ("date", "time", "vehicle")}, {"date": "2014-09-28", "time": "05:28", "vehicle": "LM-2C"})
        self.assertEqual({k: ls[1][k] for k in ("date", "time", "vehicle")}, {"date": "2021-07-04", "time": None, "vehicle": "LM-11H"})
        self.assertEqual((ls[2]["date"], ls[2]["time"]), ("2021-07-04", None))   # "(UTC)" after the year is no time
        self.assertIsNone(ls[3]["date"])
        self.assertEqual({k: ls[4][k] for k in ("date", "time", "vehicle")}, {"date": "2013-12-09", "time": "03:26", "vehicle": "LM-4B"})

    def test_join(self):
        recs = [rec("a", "2014-09-28T05:30:00Z", "LM-2C"), rec("a2", "2014-09-28T06:00:00Z", "LM-3B"),
                rec("b", "2021-07-04T03:00:00Z", "LM-11", payload="Alpha-B 01"),  # LM-11H is LM-11; untimed: payload word
                rec("x", "2021-07-04T09:00:00Z", "Falcon 9", actor="US"),
                rec("e", "2022-01-09T22:00:00Z", "LM-7A", payload="Delta-23"),  # untimed title of another payload
                rec("d", "2013-12-09T03:26:00Z", "LM-4B", chart=["ev"])]
        links = nsf.parse(HTML) + [{"topic": "106", "url": "u/106.0", "title": "Gamma-E - CZ-7A - WSLC - January 9, 2022",
                                    **nsf.read_title("Gamma-E - CZ-7A - WSLC - January 9, 2022")}]
        counts = catalog.nsf_join(recs, {"links": links}, {"d": {"105"}})
        got = {r["id"]: [f["url"][-5:] for f in r.get("forum", [])] for r in recs}
        self.assertEqual(got, {"a": ["101.0"], "a2": [], "b": ["102.0"], "x": [], "e": [], "d": []})
        self.assertEqual(counts, {"links": 6, "dated": 5, "joined": 2, "already_charted": 1, "records": 2})


if __name__ == "__main__":
    unittest.main()
