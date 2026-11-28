"""The nms lane (launch/nms.py) and closure timing (launch/timing.py), offline, on made-up NOTAMs."""
import json
import sys
import unittest
import urllib.error

import gh_api
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import gnss, nms, timing  # noqa: E402

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

    def test_off_live_kept_but_not_a_live_area(self):
        """Notices that say they are not a launch (22 Nov 2026's live list) stay kept, for the ledger, and are no
        live area; launch and debris notices are left alone."""
        mil = icao(fir="RJJJ", a="RJJJ", q="QRACA", e="MULTIPLE U.S. MIL ACT WILL BE CONDUCTED WI FUKUOKA FIR AS FLW, "
                   "AREA: 255335N1283000E-254837N1290219E-254415N1292552E-255335N1283000E.")
        missile = icao(fir="FAJA", a="FAJA", q="QWMLW", e="FAR 148 MISSILE FRNG EXER WI 340000S0230000E-340000S0240000E-"
                       "350000S0240000E-340000S0230000E.")
        age = icao(fir="KZDC", a="KZDC", q="QRRCA", e="AEROSPACE GROUND EQUIPMENT RUNS NOT AUTH DURING QUIET HOURS.")
        hpr = icao(fir="KZLC", a="KZLC", q="QRRCA", e="CLASS 2 HIGH-POWER ROCKETS WI 2NM RADIUS OF 431415N1161927W.")
        drop = icao(fir="HAAA", a="HDAM", q="QWPLW", e="MULTIPLE PASSES OF HIGH-ALTITUDE AIRDROPS AT KATHERINE DZ.")
        for t, why in ((mil, "military exercise"), (missile, "missile firing"), (age, "aerodrome notice"),
                       (hpr, "amateur rocketry"), (drop, "airdrop or airlift")):
            self.assertEqual(nms.off_live(nms.notam.parse(t)["e_text"]), why)
        n = nms.notice(feat(mil), [])
        self.assertEqual((n["kept"] is not None, n["off_live"]), (True, "military exercise"))
        st = {"notices": [n | {"start": "2026-11-23T00:00:00Z", "end": "2026-11-23T02:00:00Z"}]}
        got = nms.areas(st)
        self.assertEqual([a["off_live"] for a in got], ["military exercise"])   # kept as an area, for the toggle
        from launch import live
        up = [{"id": "u1", "name": "X", "net": "2026-11-23T01:00:00Z", "lat": 26.2, "lon": 127.6}]
        self.assertEqual(live.match(up, got, [], []), [])   # and matches no launch
        for t in ("DANGER AREA ACTIVATED WITHIN TTZP DUE TO THE ARIANE 6 LAUNCH VA271",
                  "TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN OF SPACEX NROL-136", "AIRSPACE CLSD WI AREA:",
                  "A MISSILE RANGE CLOSED FOR A ROCKET LAUNCH"):
            self.assertIsNone(nms.off_live(t), t)

    def test_off_live_24_nov(self):
        """24 Nov 2026's live list: an EOD demolition, a navaid flight inspection, a 5,000 ft civilian rocket test and
        a prohibited area matched launches. Launch and debris notices stay live."""
        for t, why in (
                ("H&HS EOD DEMOLITION OF EXPLOSIVES. LOCATION: TARGET ISLAND, MAX FRAGMENTATION DISTANCE VERTICAL: "
                 "1,217 FT", "explosives demolition"),
                ("ILS/NAVAID FLT INSPECTION OPS WILL TAKE PLACE\nFLT TEST ACFT HAVE PRIORITY", "navaid flight inspection"),
                ("CIVILIAN ROCKET TEST WITHIN 1NM RADIUS OF 35-52-59N/126-47-40E , SFC TO 5,000 AGL ON 28 NOVEMBER",
                 "ceiling under 10,000 ft"),
                ("TEMPO PROHIBITED AREA ACT AS FLW:\n1. AREA : A CIRCLE RADIUS 2NM CENTERED ON 373508N1265440E",
                 "prohibited area")):
            self.assertEqual(nms.off_live(t), why, t)
        for t in ("TRIGGER NOTAM - AIP AIRAC SUP 58/26. TEMPO DANGER AREAS ESTABLISHED IN CONNECTION WITH ROCKET "
                  "LAUNCH FROM ANDOYA SPACE.",
                  "SPECIAL OPS (AEROSPACE FLT ACT) WILL BE CONDUCTED BY CHINA. EST FALL AREA OF UNBURNED DEBRIS WI:",
                  "A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY: 400000N1100000E, SFC TO UNL",
                  "PROHIBITED AREA ACT DUE TO ROCKET LAUNCH", "SFC TO 60,000 FT AMSL ROCKET LAUNCH"):
            self.assertIsNone(nms.off_live(t), t)

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


INDEX = {"env": "prod", "lane_status": "ok", "bulk_at": "2026-11-17T00:30:00Z", "pulled_to": "2026-11-17T11:40:00Z",
         "subsets": [{"name": "launch-areas", "file": "launch-areas.json"}, {"name": "gnss", "file": "gnss.json"}]}


class FromCordon(unittest.TestCase):
    def test_set_is_whole_active_set(self):
        st = nms.from_set([feat(icao()), feat(icao(num="A5898/26", q="QFALC", e="AD CLSD"))], INDEX, [], NOW)
        self.assertEqual((st["mode"], st["requests"], st["env"]), ("cordon", 0, "prod"))
        self.assertEqual((st["bulk_at"], st["pulled_to"]), (INDEX["bulk_at"], INDEX["pulled_to"]))
        self.assertEqual([n["number"] for n in st["notices"]], ["A5897/26"])
        self.assertEqual(st["counts"]["kept_by_rule"], {"cn-area": 1})
        self.assertIn("Not FAA data", st["source_note"])

    def test_no_faa_client_left(self):
        self.assertFalse(hasattr(nms, "Client") or hasattr(nms, "pull") or hasattr(nms, "HOSTS"))
        self.assertTrue(nms.CORDON_NOTAMS.startswith("https://cordon.theintelligence.company/"))

    def test_lane_reads_cordon_files(self):
        import runpy
        import tempfile
        mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "launch.py"), run_name="lane_test")
        # the lane uses the real clock, so the notice's window is built from it (a fixed date expires)
        t0 = datetime.now(timezone.utc)
        soon = ((t0 - timedelta(hours=1)).strftime("%y%m%d%H%M"), (t0 + timedelta(days=2)).strftime("%y%m%d%H%M"))
        site = {nms.CORDON_NOTAMS + "index.json": INDEX,
                nms.CORDON_NOTAMS + "launch-areas.json": {"type": "FeatureCollection", "features": [feat(icao(b=soon[0], c=soon[1]))]},
                nms.CORDON_NOTAMS + "gnss.json": {"type": "FeatureCollection", "features": []}}
        asked = []

        def getter(url, timeout=0):
            asked.append(url)
            if url not in site:   # Launch's own published GNSS files: none yet
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return json.dumps(site[url]).encode()
        with tempfile.TemporaryDirectory() as t:
            raw = Path(t) / "data" / "raw"
            result, recs = mod["_lane_nms"](raw, {}, getter)
            self.assertTrue((Path(t) / "data" / "gnss" / "store.json").exists())
        self.assertEqual([u for u in asked if u in site], list(site))
        self.assertTrue(all(u in site or u.startswith(gnss.PUBLISHED) for u in asked))
        self.assertTrue(all("faa.gov" not in u for u in asked))
        self.assertEqual(len(result["nms"]["notices"]), 1)
        self.assertEqual(len(recs), 3)

    def test_areas_leave_fdc_to_tfr_lane(self):
        st = {"notices": [{"number": "6/7113", "classification": "FDC", "fir": None, "start": "2026-11-18T00:00:00Z",
                           "end": "2026-11-18T02:00:00Z", "rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]], "kept": "words"}]}
        self.assertEqual(nms.areas(st, {"6/7113"}), [])
        self.assertEqual(len(nms.areas(st, set())), 1)

    def test_areas_carry_the_issuing_state(self):
        """25 Nov 2026: the Live map's country filter puts an area on no launch's path under the state that issued it."""
        ring = [[[0, 0], [1, 0], [1, 1], [0, 0]]]
        st = {"notices": [{"number": "A1/26", "fir": "ZWUQ", "issuing_state": "CN", "start": "2026-11-18T00:00:00Z",
                           "end": "2026-11-18T02:00:00Z", "rings": ring, "kept": "cn-area"},
                          {"number": "A2/26", "fir": None, "start": "2026-11-18T00:00:00Z",
                           "end": "2026-11-18T02:00:00Z", "rings": ring, "kept": "words"}]}
        self.assertEqual([a.get("state") for a in nms.areas(st)], ["CN", None])
        self.assertNotIn("state", nms.areas(st)[1])


class Ledger(unittest.TestCase):
    """Every closure notice ever kept stays (data/nms-closures.json), each version once."""

    N = {"number": "A5897/26", "fir": "ZXXX", "last_updated": "2026-11-17T10:00:00.000Z", "start": "2026-11-18T00:00Z",
         "text": "ROCKET LAUNCH. CTC OPS" + chr(64) + "EXAMPLE.CN"}   # an address, built so no file holds one

    def test_union_and_versions(self):
        one = nms.ledger([], [self.N], "2026-11-17T12:00:00Z")
        self.assertEqual(one["n"], 1)
        self.assertNotIn("@", one["notices"][0]["text"])
        # later: the same version again (".000Z" written as "Z"), and a new version of it
        two = nms.ledger([one], [{**self.N, "last_updated": "2026-11-17T10:00:00Z"},
                                 {**self.N, "last_updated": "2026-11-17T18:00:00.000Z"}], "2026-11-17T18:00:00Z")
        self.assertEqual(two["n"], 2)
        first = next(e for e in two["notices"] if e["last_updated"].startswith("2026-11-17T10"))
        self.assertEqual((first["first_seen"], first["last_seen"]), ("2026-11-17T12:00:00Z", "2026-11-17T18:00:00Z"))
        # the live set is empty now (ended): the ledger keeps both
        three = nms.ledger([two, None], [], "2026-12-30T00:00:00Z")
        self.assertEqual(three["n"], 2)
        self.assertIn("Not FAA data", three["source_note"])

    def test_the_newer_copy_wins_whatever_the_order(self):
        # collect passes [published, release, cache]; a cached or archived copy older than the release copy must not
        # revert what a later run derived on a notice version both hold.
        old = nms.ledger([], [{**self.N, "kept": "words", "off_live": None}], "2026-11-17T12:00:00Z")
        new = nms.ledger([old], [{**self.N, "kept": "cn-area", "off_live": "not a launch"}], "2026-11-18T12:00:00Z")
        got = nms.ledger([None, new, old], [], "2026-11-19T00:00:00Z")
        (e,) = got["notices"]
        self.assertEqual((e["kept"], e["off_live"]), ("cn-area", "not a launch"))
        self.assertEqual((e["first_seen"], e["last_seen"]), ("2026-11-17T12:00:00Z", "2026-11-18T12:00:00Z"))
        # equal times keep the order given (the last copy wins), as before
        same = {**old, "notices": [{**old["notices"][0], "kept": "same-time"}]}
        self.assertEqual(nms.ledger([old, same], [], "2026-11-19T00:00:00Z")["notices"][0]["kept"], "same-time")

    def lane(self, getter, cached=None, lane=None):
        import runpy
        import tempfile
        mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "launch.py"), run_name="ledger_test")
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            if cached:
                (d / "nms-closures.json").write_text(json.dumps(cached), encoding="utf-8")
            snap = {"generated_at": "2026-11-19T00:11:00Z",
                    "lanes": {"nms": lane or {"status": "ok", "fetched_at": "2026-11-19T00:11:00Z"}},
                    "nms": {"notices": [self.N]}}
            st = mod["update_nms_ledger"](snap, d, getter)
            return st, json.loads((d / "nms-closures.json").read_text(encoding="utf-8"))

    def test_lane_unions_published_copy(self):
        old = nms.ledger([], [{**self.N, "number": "A0001/26"}], "2026-11-01T00:00:00Z")
        st, led = self.lane(lambda url, timeout=0: json.dumps(old).encode())
        self.assertEqual((st["status"], led["n"], st["added"]), ("ok", 2, 1))

    def test_failed_lane_keeps_the_carried_copy_at_its_read_time(self):
        def none(url, timeout=0):
            if (api := gh_api.answer(url)) is not None:   # release listed without the asset: no copy yet
                return api
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        st, led = self.lane(none, lane={"status": "failed", "from_previous": True,
                                        "fetched_at": "2026-11-18T23:30:00Z"})
        self.assertEqual(led["n"], 1)
        self.assertEqual((led["notices"][0]["first_seen"], led["generated_at"]),
                         ("2026-11-18T23:30:00Z", "2026-11-19T00:11:00Z"))

    def test_first_run_404(self):
        def none(url, timeout=0):
            if (api := gh_api.answer(url)) is not None:   # release listed without the asset: no copy yet
                return api
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        st, led = self.lane(none)
        self.assertEqual(led["n"], 1)

    def test_pages_html_fallback_is_not_published(self):
        """Cloudflare Pages answers an undeployed path with the index page, 200 text/html (19 Nov 2026)."""
        st, led = self.lane(lambda url, timeout=0: b"<!doctype html>\n<html lang=\"en\"><head>")
        self.assertEqual((st["status"], led["n"], st["published"]), ("ok", 1, False))

    def test_no_cache_and_site_down_stops(self):
        def down(url, timeout=0):
            raise urllib.error.URLError("down")
        with self.assertRaises(RuntimeError):
            self.lane(down)
        st, led = self.lane(down, cached=nms.ledger([], [{**self.N, "number": "A0002/26"}], "2026-11-01T00:00:00Z"))
        self.assertEqual((st["status"], led["n"]), ("failed", 2))

    def test_release_copy_restores_when_site_404_and_no_cache(self):
        """ideas#222: a site that answers 404 and an empty cache restore from the release, not from empty."""
        old = nms.ledger([], [{**self.N, "number": "A0003/26"}], "2026-11-01T00:00:00Z")

        def get(url, timeout=0):
            if "releases/download" in url:
                return json.dumps(old).encode()
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        st, led = self.lane(get)
        self.assertEqual((st["status"], led["n"], st["published"], st["release"]), ("ok", 2, False, True))

    def test_site_down_but_release_readable_goes_on(self):
        old = nms.ledger([], [{**self.N, "number": "A0004/26"}], "2026-11-01T00:00:00Z")

        def get(url, timeout=0):
            if "releases/download" in url:
                return json.dumps(old).encode()
            raise urllib.error.URLError("down")
        st, led = self.lane(get)
        self.assertEqual((st["status"], led["n"], st["release"]), ("ok", 2, True))

    def test_release_down_and_site_404_with_no_cache_stops(self):
        def get(url, timeout=0):
            if "releases/download" in url:
                raise urllib.error.URLError("down")
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        with self.assertRaises(RuntimeError):
            self.lane(get)


class CordonNgaState(unittest.TestCase):
    """ideas#222: Cordon withholds its NGA set when its reader is stale or never read; Launch's lane is then unread
    (it fails and keeps its last good copy), not zero warnings."""

    def doc(self, state):
        return json.dumps({"generated_at": "2026-11-24T00:00:00Z",
                           "health": {"nga-navwarnings": {"state": state}}, "features": []}).encode()

    def test_withheld_states_fail_the_lane(self):
        import runpy
        mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "launch.py"), run_name="nga_test")
        for state in ("stale", "never"):
            with self.assertRaises(RuntimeError):
                mod["_lane_cordon"](None, {}, lambda url, timeout=0, s=state: self.doc(s))
        for state in ("fresh", "failing", None):
            got, _ = mod["_lane_cordon"](None, {}, lambda url, timeout=0, s=state: self.doc(s))
            self.assertEqual((got["cordon"]["nga_state"], got["cordon"]["areas"]), (state, []))


class SiteSize(unittest.TestCase):
    """check warns as a site file nears Cloudflare Pages' 25 MiB limit and fails before it."""

    def test_warn_then_fail(self):
        import runpy
        import tempfile
        mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "launch.py"), run_name="size_test")
        with tempfile.TemporaryDirectory() as t:
            site = Path(t) / "site"
            (site / "data").mkdir(parents=True)
            (site / "data" / "small.json").write_bytes(b"{}")
            self.assertEqual(mod["site_size_problems"](site), ([], []))
            with open(site / "data" / "nms-closures.json", "wb") as fh:
                fh.truncate(mod["SIZE_WARN"] + 1)
            errs, notes = mod["site_size_problems"](site)
            self.assertEqual((errs, len(notes)), ([], 1))
            self.assertIn("data/nms-closures.json", notes[0])
            with open(site / "data" / "nms-closures.json", "wb") as fh:
                fh.truncate(mod["SIZE_FAIL"] + 1)
            errs, _ = mod["site_size_problems"](site)
            self.assertEqual(len(errs), 1)
            self.assertIn("split it", errs[0])


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

    def test_window_no_longer_than_the_sites_longest(self):
        """24 Nov 2026: a 6 h area near a site whose launches' windows ran 30 min at most gets no expected time."""
        recs = [self.rec(f"2026-0{m}-01T10:0{m}:00Z", f"2026-0{m}-01T10:00:00Z", f"2026-0{m}-01T10:30:00Z")
                for m in range(1, 7)]
        s = timing.by_site(recs)["Testsite"]
        self.assertEqual(s["max_window_min"], 30.0)
        ring = [[100.4, 40.4], [100.6, 40.4], [100.6, 40.6], [100.4, 40.4]]
        self.assertIsNotNone(timing.expect(ring, "2026-12-01T05:00:00Z", "2026-12-01T05:30:00Z", {"Testsite": s}))
        self.assertIsNone(timing.expect(ring, "2026-12-01T05:00:00Z", "2026-12-01T05:31:00Z", {"Testsite": s}))
        self.assertIsNone(timing.expect(ring, "2026-12-01T05:00:00Z", "2026-12-01T11:00:00Z", {"Testsite": s}))
        old = {k: v for k, v in s.items() if k != "max_window_min"}   # a timing.json from before the field: 6 h holds
        self.assertIsNotNone(timing.expect(ring, "2026-12-01T05:00:00Z", "2026-12-01T11:00:00Z", {"Testsite": old}))

    def test_window_must_hold_launch(self):
        self.assertIsNone(timing.offset(self.rec("2026-01-01T11:00:00Z", "2026-01-01T10:00:00Z",
                                                 "2026-01-01T10:30:00Z")))


if __name__ == "__main__":
    unittest.main()
