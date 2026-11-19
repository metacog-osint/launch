"""GPS/GNSS NOTAMs from the nms lane's pulls (launch/gnss.py), offline, on made-up NOTAMs."""
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import gnss  # noqa: E402

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
NOTE = "made-up source note"
OK = {"status": "ok"}


def feat(number="A0001/26", text="GNSS UNRELIABLE DUE TO INTERFERENCE WI 50NM OF 3300N03500E.", q="QGWXX",
         kind="N", fir="LLLL", start="2026-11-18T06:00:00Z", end="2026-11-19T06:00:00Z", issued=None, icao=None,
         nid=None, account="LLLLYNYX") -> dict:
    n = {"id": nid or "NMS_ID_" + number, "number": number, "type": kind, "affectedFir": fir, "location": fir,
         "selectionCode": q, "effectiveStart": start, "effectiveEnd": end, "issued": issued or start,
         "text": text, "classification": "INTL", "accountId": account}
    if q is None:
        del n["selectionCode"]
    tr = [{"type": "ICAO", "formattedText": icao}] if icao else []
    return {"type": "Feature", "geometry": {"type": "GeometryCollection", "geometries": []},
            "properties": {"coreNOTAMData": {"notam": n, "notamTranslation": tr}}}


class Select(unittest.TestCase):
    def test_q_code(self):
        self.assertEqual(gnss.select(feat(text="SEE AIP SUP 12/26"))["matched_by"], "q-code")
        self.assertEqual(gnss.select(feat(q="QGAAU", text="RNAV APCH NOT AVBL"))["matched_by"], "q-code")

    def test_q_code_from_icao_text(self):
        f = feat(q=None, text="SEE SUP", icao="A0001/26 NOTAMN\nQ) LLLL/QGWAU/IV/NBO/E/000/999/3300N03500E050\nE) X")
        self.assertEqual(gnss.select(f)["q_code"], "QGWAU")

    def test_text(self):
        for t in ("CIVIL AIRCRAFT MAY ENCOUNTER GPS INTERFERENCE AND COMMUNICATIONS JAMMING.",
                  "AIRSPACE DUE TO GPS TESTING GPS MAY NOT BE AVAILABLE WI A 295MI RADIUS",
                  "GPS SATELLITE SVN43 (PRN13) WILL BE UNUSABLE NO EARLIER THAN 1500Z",
                  "APV SBAS APPROACHES ARE SUSPENDED. LPV OCA/H NOT AVBL"):
            s = gnss.select(feat(q="QXXXX", text=t))
            self.assertEqual(s and s["matched_by"], "text", t)

    def test_text_not_kept(self):
        for t in ("FOR ACFT EQUIPPED WITH SUITABLE RNAV SYSTEM WITH GPS, EUG VOR OUT OF SERVICE.",
                  "FOR ACFT EQUIPPED WITH SUITABLE RNAV SYSTEM WITH GPS. MCB VOR R-014 UNUSABLE.",
                  "RNAV (GPS) RWY 18, AMDT 2... LPV DA NA",
                  "TO BE ASSIGNED IN CASE OF GNSS FAILURE OR LOSS. UNDER NORMAL CONDITIONS USE STAR",
                  "V320 RUNTL TO FRIDA UNUSABLE EXCEPT FOR GNSS EQUIPPED AIRCRAFT.",
                  "GPS SONDE MET UNMANNED BALLOON FLT OPS FM THUMBA",
                  "SID EL PASO INTL. NEVUE THREE DEPARTURE (RNAV)... GPS REQUIRED, HUP TACAN OUT OF SERVICE, NA",
                  "IAP BRACKETT FLD. VOR OR GPS-A, AMDT 5E... VOR PORTION NA, POM VORTAC OUT OF SERVICE.",
                  "RNAV 1 (DME/DME OR GNSS) MID RWY 18, RNAV 1 GNSS MID RWY 36, NOT AVBL DUE PENDING CHART",
                  "RWY 09 ILS U/S"):
            self.assertIsNone(gnss.select(feat(q="QPIAU", text=t)), t)


class Store(unittest.TestCase):
    def test_cancel_marks_and_is_kept(self):
        s = gnss.update(gnss.empty(), [feat()], "bulk", NOW, "staging")
        c = feat(number="A0002/26", kind="C", q="QGWXX", text="NOTAMC A0001/26", issued="2026-11-18T15:00:00Z",
                 icao="A0002/26 NOTAMC A0001/26\nQ) LLLL/QGWXX/IV/NBO/E/000/999/3300N03500E050\nE) CNL")
        s = gnss.update(s, [c], "delta", NOW + timedelta(hours=4), "staging")
        orig = s["notices"]["A0001/26|LLLL|LLLLYNYX"]
        self.assertEqual(orig["cancelled_by"], "A0002/26")
        self.assertEqual(orig["ended_at"], "2026-11-18T15:00:00Z")
        self.assertIn("A0002/26|LLLL|LLLLYNYX", s["notices"])

    def test_refers_kept_without_gnss_words(self):
        s = gnss.update(gnss.empty(), [feat()], "bulk", NOW, "staging")
        r = feat(number="A0003/26", kind="R", q="QXXXX", text="AREA AMENDED, SEE NEW COORDINATES",
                 icao="A0003/26 NOTAMR A0001/26\nQ) LLLL/QXXXX/IV/NBO/E/000/999/3300N03500E050\nE) X")
        s = gnss.update(s, [r], "delta", NOW + timedelta(hours=1), "staging")
        self.assertEqual(s["notices"]["A0003/26|LLLL|LLLLYNYX"]["matched_by"], "refers")
        self.assertEqual(s["notices"]["A0001/26|LLLL|LLLLYNYX"]["replaced_by"], "A0003/26")

    def test_bulk_marks_gone(self):
        s = gnss.update(gnss.empty(), [feat(), feat(number="A0009/26")], "bulk", NOW, "staging")
        s = gnss.update(s, [feat()], "bulk", NOW + timedelta(days=1), "staging")
        self.assertIsNotNone(s["notices"]["A0009/26|LLLL|LLLLYNYX"]["gone_at"])
        self.assertIsNone(s["notices"]["A0001/26|LLLL|LLLLYNYX"]["gone_at"])

    def test_email_removed(self):
        addr = "ops" + chr(64) + "example.org"  # built here so this file holds no address for the privacy check
        s = gnss.update(gnss.empty(), [feat(text=f"GPS INTERFERENCE TESTING. CONTACT {addr} FOR INFO")],
                        "bulk", NOW, "staging")
        n = next(iter(s["notices"].values()))
        self.assertNotIn("@", n["notam"]["text"])
        self.assertEqual(s["emails_removed"], 1)


class Days(unittest.TestCase):
    def run_day(self, feats, runs):
        """Pull feats on the first run; then publish at each run time. Returns (dir, last summary)."""
        d = Path(tempfile.mkdtemp())
        out = None
        for i, t in enumerate(runs):
            if i == 0 and feats is not None:
                (d).mkdir(exist_ok=True)
                s = gnss.update(gnss.load(d / "store.json"), feats, "bulk", t, "staging")
                (d / "store.json").write_text(json.dumps(s), encoding="utf-8")
            out = gnss.publish(d, t, OK if feats is not None else {"status": "waiting", "note": "no keys"},
                               NOTE, getter=self.site({}))   # nothing published yet (404)
        return d, out

    def test_day_file_after_day_ends(self):
        day = datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)
        d, out = self.run_day([feat(), feat(number="A0005/26", start="2026-11-20T00:00:00Z",
                                            end="2026-11-21T00:00:00Z")],
                              [day, datetime(2026, 11, 19, 0, 30, tzinfo=timezone.utc)])
        doc = json.loads((d / "days" / "2026-11-18.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["n"], 1)
        self.assertEqual(doc["notices"][0]["notam"]["number"], "A0001/26")
        self.assertEqual(doc["source_note"], NOTE)
        self.assertEqual(doc["rule"], gnss.RULE)
        self.assertEqual(doc["runs_that_day"], {"ok": 1})
        self.assertFalse((d / "days" / "2026-11-19.json").exists())
        act = json.loads((d / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(act["n"], 2)
        idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([x["day"] for x in idx["days"]], ["2026-11-18"])
        self.assertTrue(idx["days"][0]["url"].endswith("/data/gnss-notams/2026-11-18.json"))

    def test_zero_day_while_waiting(self):
        d, _ = self.run_day(None, [datetime(2026, 11, 18, 6, tzinfo=timezone.utc),
                                   datetime(2026, 11, 19, 6, tzinfo=timezone.utc)])
        doc = json.loads((d / "days" / "2026-11-18.json").read_text(encoding="utf-8"))
        self.assertEqual((doc["n"], doc["runs_that_day"], doc["lane_status"]), (0, {"waiting": 1}, "waiting"))

    def test_late_cancel_revises(self):
        d, _ = self.run_day([feat(start="2026-11-18T00:00:00Z", end="2026-11-25T00:00:00Z")],
                            [datetime(2026, 11, 18, 6, tzinfo=timezone.utc),
                             datetime(2026, 11, 19, 1, tzinfo=timezone.utc)])
        p = d / "days" / "2026-11-18.json"
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["n"], 1)
        c = feat(number="A0002/26", kind="C", text="NOTAMC A0001/26", issued="2026-11-18T10:00:00Z",
                 icao="A0002/26 NOTAMC A0001/26\nQ) LLLL/QGWXX/IV/NBO/E/000/999/3300N03500E050\nE) CNL")
        t = datetime(2026, 11, 19, 7, tzinfo=timezone.utc)
        s = gnss.update(gnss.load(d / "store.json"), [c], "delta", t, "staging")
        (d / "store.json").write_text(json.dumps(s), encoding="utf-8")
        gnss.publish(d, t, OK, NOTE)
        doc = json.loads(p.read_text(encoding="utf-8"))
        self.assertIsNotNone(doc["revised_at"])
        self.assertEqual(sorted(n["notam"]["number"] for n in doc["notices"]), ["A0001/26", "A0002/26"])
        self.assertEqual(next(n for n in doc["notices"] if n["notam"]["number"] == "A0001/26")["ended_at"],
                         "2026-11-18T10:00:00Z")

    def test_old_days_kept_for_good(self):
        d = Path(tempfile.mkdtemp())
        (d / "days").mkdir(parents=True)
        old = {"day": "2026-01-01", "n": 2, "written_at": "2026-01-02T00:10:00Z", "revised_at": None, "notices": []}
        (d / "days" / "2026-01-01.json").write_text(json.dumps(old), encoding="utf-8")
        gnss.publish(d, NOW, OK, NOTE)
        self.assertEqual(json.loads((d / "days" / "2026-01-01.json").read_text(encoding="utf-8")), old)
        idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([x["day"] for x in idx["days"]][-1], "2026-01-01")
        self.assertEqual(idx["kept"], "for good")

    def test_ended_notices_never_pruned(self):
        s = gnss.update(gnss.empty(), [feat()], "bulk", NOW, "prod")
        s = gnss.update(s, [], "bulk", NOW + timedelta(days=400), "prod")
        self.assertEqual(len(s["notices"]), 1)
        self.assertIsNotNone(next(iter(s["notices"].values()))["gone_at"])

    @staticmethod
    def site(pub):
        def get(url, timeout=0):
            if url not in pub:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return json.dumps(pub[url]).encode()
        return get

    def test_restore_from_published(self):
        day = {"day": "2026-10-17", "n": 3, "written_at": "2026-10-18T00:11:00Z", "revised_at": None, "notices": []}
        rec = {"key": "A0001/26|LLLL|", **gnss._public(gnss.record(feat(), {"matched_by": "q-code", "q_code": "QGWXX",
                                                                            "words": []}, "2026-10-17T06:00:00Z", [0]))}
        pub = {gnss.PUBLISHED + "index.json": {"days": [{"day": "2026-10-17"}]},
               gnss.PUBLISHED + "2026-10-17.json": day,
               gnss.PUBLISHED + "all.json": {"notices": [rec]}}
        d = Path(tempfile.mkdtemp())
        out = gnss.publish(d, NOW, OK, NOTE, getter=self.site(pub))
        self.assertEqual(out["restored"], 2)
        self.assertEqual(json.loads((d / "days" / "2026-10-17.json").read_text(encoding="utf-8")), day,
                         "fetched back as published: written_at and revised_at unchanged")
        self.assertEqual(list(json.loads((d / "store.json").read_text(encoding="utf-8"))["notices"]),
                         ["A0001/26|LLLL|"])
        allj = json.loads((d / "all.json").read_text(encoding="utf-8"))
        self.assertEqual(allj["n"], 1)

    def test_unreachable_site_with_no_local_copy_stops(self):
        d = Path(tempfile.mkdtemp())

        def down(url, timeout=0):
            raise urllib.error.URLError("down")
        with self.assertRaises(gnss.Unreachable):
            gnss.publish(d, NOW, OK, NOTE, getter=down)
        self.assertFalse((d / "index.json").exists())

    def test_first_run_404_starts_afresh(self):
        d = Path(tempfile.mkdtemp())
        out = gnss.publish(d, NOW, OK, NOTE, getter=self.site({}))
        self.assertEqual(out["restored"], 0)
        self.assertTrue((d / "all.json").exists())

    def test_site_files(self):
        d, _ = self.run_day([feat()], [datetime(2026, 11, 18, 6, tzinfo=timezone.utc),
                                       datetime(2026, 11, 19, 1, tzinfo=timezone.utc)])
        self.assertEqual(sorted(gnss.site_files(d)), ["data/gnss-notams/2026-11-18.json",
                                                      "data/gnss-notams/active.json",
                                                      "data/gnss-notams/all.json",
                                                      "data/gnss-notams/index.json"])


if __name__ == "__main__":
    unittest.main()
