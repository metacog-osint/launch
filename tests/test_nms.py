"""The nms lane (launch/nms.py) and closure timing (launch/timing.py), offline, on made-up NOTAMs."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import nms, timing  # noqa: E402

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def feat(text: str, nid: str = "NMS_ID_1", cls: str = "INTL") -> dict:
    return {"type": "Feature", "geometry": None, "properties": {"coreNOTAMData": {
        "notam": {"id": nid, "classification": cls, "issued": "2026-11-16T00:00:00.000Z"},
        "notamTranslation": [{"type": "ICAO", "formattedText": text}]}}}


def icao(num="A5897/26", kind="N", ref="", fir="ZXXX", q="QRDCA", lo="000", up="999", a="ZBPE",
         b="2611182243", c="2611182305", e="A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY: "
         "N333400E1103100-N333200E1104400-N331000E1104100-N331100E1102700.", f="SFC", g="UNL", d=""):
    head = f"{num} NOTAM{kind}" + (f" {ref}" if ref else "")
    return (f"{head}\nQ) {fir}/{q}/IV/BO/W/{lo}/{up}/3322N11036E030\nA) {a} B) {b} C) {c}"
            + (f"\nD) {d}" if d else "") + f"\nE) {e}\nF) {f} G) {g}")


class Keep(unittest.TestCase):
    def kept(self, text, past=()):
        n = nms.notice(feat(text), list(past))
        return n and n["kept"]

    def test_china_area(self):
        self.assertEqual(self.kept(icao()), "cn-area")

    def test_words(self):
        self.assertEqual(self.kept(icao(fir="RPHI", a="RPHI", q="QWMLW", e="AEROSPACE FLT ACT. EST FALL AREA OF "
                                        "UNBURNED DEBRIS WI: 125000N1250000E-125000N1260000E-120000N1260000E-"
                                        "120000N1250000E.")), "words")

    def test_unl_area_anywhere(self):
        self.assertEqual(self.kept(icao(fir="UACN", a="UACN", e="TEMPORARY RESTRICTED AREA ACTIVATED RADIUS 16 NM "
                                        "CENTRE 455946N0631836E.", b="2611241005", c="2611241200")), "unl-area")

    def test_not_kept(self):
        gun = icao(fir="RJJJ", a="RJJJ", q="QWMLW", e="GUN FRNG WILL TAKE PLACE WI AREA 431358N1430249E-"
                   "431401N1430423E-431359N1430451E.", g="FL400", up="400")
        laser = icao(fir="EGTT", a="EGTT", q="QWOLW", e="LASER DISPLAY WI 1NM RADIUS OF 555805N 0025544W.")
        low = icao(fir="WMFC", a="WMFC", q="QWMLW", e="SMALL ROCKET FIRING WITHIN 1 NM RAD OF 021342N 1022732E.",
                   g="500FT AMSL", up="005")
        perm = icao(fir="KZNY", a="KJFK", q="QRACD", e="AIRSPACE ROCKET LAUNCH", c="PERM")
        stage = icao(fir="YMMM", a="YMMM", q="QLXAS", e="TWY LGT U/S DUE WIP STAGE 2", f="SFC", g="UNL")
        cancel = icao(kind="C", ref="A5896/26")
        for t in (gun, laser, low, perm, stage, cancel):
            self.assertIsNone(self.kept(t), t.splitlines()[0])

    def test_recurring(self):
        t = icao(fir="ULLL", a="ULLL", q="QRTCA", e="AIRSPACE CLSD WI AREA: 691700N0340000E-690000N0340000E-"
                 "690000N0325000E-691300N0331500E-691700N0340000E.", g="FL230", up="230",
                 b="2611160500", c="2611201900")
        self.assertIsNone(self.kept(t))
        self.assertEqual(self.kept(t, [(69.1, 33.4)]), "recurring-area")

    def test_height(self):
        self.assertEqual(nms.height_ft("FL245"), 24500)
        self.assertAlmostEqual(nms.height_ft("550M AMSL"), 1804.4, 0)
        self.assertEqual(nms.height_ft("UNL"), float("inf"))
        self.assertIsNone(nms.height_ft("see text"))


class Store(unittest.TestCase):
    def test_replace_and_cancel(self):
        res = nms.apply({}, [feat(icao())], [], NOW, replace_all=True)
        self.assertEqual(list(res["notices"]), ["A5897/26|ZXXX"])
        res = nms.apply(res["notices"], [feat(icao(num="A5901/26", kind="R", ref="A5897/26", b="2611192243",
                                                   c="2611192305"))], [], NOW)
        self.assertEqual(list(res["notices"]), ["A5901/26|ZXXX"])
        res = nms.apply(res["notices"], [feat(icao(num="A5902/26", kind="C", ref="A5901/26"))], [], NOW)
        self.assertEqual(res["notices"], {})

    def test_expired_dropped(self):
        res = nms.apply({}, [feat(icao(b="2611140000", c="2611150100"))], [], NOW, replace_all=True)
        self.assertEqual(res["notices"], {})


class FakeClient:
    env_name, host = "staging", "https://example.invalid"

    def __init__(self):
        self.requests, self.calls = 0, []

    def classification(self, name):
        self.calls.append(("bulk", name))
        return [feat(icao())] if name == "INTERNATIONAL" else []

    def delta(self, since):
        self.calls.append(("delta", since))
        return []


class Pull(unittest.TestCase):
    def test_bulk_then_delta(self):
        c = FakeClient()
        st = nms.pull(c, {}, [], NOW)
        self.assertEqual(st["mode"], "bulk")
        self.assertEqual([x[1] for x in c.calls], list(nms.CLASSES))
        self.assertEqual(len(st["notices"]), 1)
        c2 = FakeClient()
        st2 = nms.pull(c2, st, [], NOW + timedelta(hours=5))
        self.assertEqual(st2["mode"], "delta")
        self.assertEqual(c2.calls, [("delta", NOW - timedelta(seconds=nms.OVERLAP_S))])
        self.assertEqual(len(st2["notices"]), 1)
        c3 = FakeClient()
        self.assertEqual(nms.pull(c3, st2, [], NOW + timedelta(hours=25))["mode"], "bulk")

    def test_waiting_without_keys(self):
        with self.assertRaises(nms.Waiting):
            nms.Client(env={})

    def test_areas_leave_fdc_to_tfr_lane(self):
        st = {"notices": [{"number": "6/7113", "classification": "FDC", "fir": None, "start": "2026-11-18T00:00:00Z",
                           "end": "2026-11-18T02:00:00Z", "rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]], "kept": "words"}]}
        self.assertEqual(nms.areas(st, {"6/7113"}), [])
        self.assertEqual(len(nms.areas(st, set())), 1)


class Timing(unittest.TestCase):
    PAD = [100.29, 40.96]   # made-up pad

    def rec(self, t, start, end, centre=(40.5, 100.5), site="Testsite"):
        la, lo = centre
        ring = [[lo - .1, la - .1], [lo + .1, la - .1], [lo + .1, la + .1], [lo - .1, la - .1]]
        return {"time": t, "time_basis": "time", "pad": self.PAD, "site": site, "kind": "Orbital",
                "joey_notices": [{"start": start, "end": end, "rings": [ring]}]}

    def test_offset_and_site(self):
        recs = [self.rec(f"2026-0{m}-01T10:0{m}:00Z", f"2026-0{m}-01T10:00:00Z", f"2026-0{m}-01T10:30:00Z")
                for m in range(1, 7)]
        self.assertEqual(timing.offset(recs[0])["open_min"], 1.0)
        s = timing.by_site(recs)["Testsite"]
        self.assertEqual((s["launches"], s["median_min"]), (6, 3.5))
        x = timing.expect([[100.4, 40.4], [100.6, 40.4], [100.6, 40.6], [100.4, 40.4]],
                          "2026-12-01T05:00:00Z", "2026-12-01T05:30:00Z", {"Testsite": s})
        self.assertEqual(x["at"], "2026-12-01T05:03:30Z")
        self.assertIsNone(timing.expect(x and [[100.4, 40.4], [100.6, 40.4], [100.6, 40.6], [100.4, 40.4]],
                                        "2026-12-01T05:00:00Z", "2026-12-02T05:00:00Z", {"Testsite": s}))

    def test_window_must_hold_launch(self):
        self.assertIsNone(timing.offset(self.rec("2026-01-01T11:00:00Z", "2026-01-01T10:00:00Z",
                                                 "2026-01-01T10:30:00Z")))


if __name__ == "__main__":
    unittest.main()
