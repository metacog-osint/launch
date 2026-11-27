"""tools/launch.py update_ledger: a run that can read neither the release copy of the launch ledger (anything but a
404) nor a dated copy of the last days stops before writing, so the workflow never uploads a possibly smaller ledger
over the release's copy and that day's dated copy. The newest dated copy is read as one more source, so a release copy
lost to a failed upload (a 404) loses nothing."""
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("launch_cli_ledger_guard", ROOT / "tools" / "launch.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def rec(n, date="2026-11-01"):
    return {"id": f"gcat:2026-{n:03d}", "source": "gcat", "date": date, "updated": "2026-11-01T00:00:00Z"}


def not_found(url):
    return urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def server_error(url):
    return urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)


class LedgerReleaseGuard(unittest.TestCase):
    def run_ledger(self, release, site, cached=None, dated=not_found):
        """release / site / dated: a ledger dict to serve, or a function url -> exception to raise. `dated` may also
        be {day: ledger}, the dated copies by day (others 404)."""
        self.urls = []

        def get(url, timeout=0):
            self.urls.append(url)
            if "/download/ledger-" in url:
                src = dated
                if isinstance(src, dict) and "launches" not in src:
                    src = next((v for d, v in dated.items() if url.endswith(f"-{d}.json")), not_found)
            else:
                src = release if "releases/download" in url else site
            if callable(src):
                raise src(url)
            return json.dumps(src).encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "history").mkdir()
            (root / "history" / "ledger.json").write_text(json.dumps({"launches": [rec(1)]}), encoding="utf-8")
            data = root / "data"
            data.mkdir()
            if cached is not None:
                (data / "ledger.json").write_text(json.dumps(cached), encoding="utf-8")
            snap = {"generated_at": "2026-11-27T06:11:00Z", "orbit": {}, "matches": []}
            st = cli.update_ledger(snap, [], data, root, get)
            return st, json.loads((data / "ledger.json").read_text(encoding="utf-8"))

    def test_release_and_dated_unreadable_stops_even_with_a_local_copy(self):
        # The local copy (a restored or stale cache) lacks what the release holds; writing it would be uploaded.
        with self.assertRaises(RuntimeError):
            self.run_ledger(server_error, server_error, cached={"launches": [rec(1)]}, dated=server_error)
        with self.assertRaises(RuntimeError):
            self.run_ledger(lambda url: urllib.error.URLError("down"), not_found)

    def test_nothing_written_when_it_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()

            def get(url, timeout=0):
                raise server_error(url)
            with self.assertRaises(RuntimeError):
                cli.update_ledger({"generated_at": "t", "orbit": {}, "matches": []}, [], data, root, get)
            self.assertFalse((data / "ledger.json").exists())

    def test_published_copy_alone_is_not_enough(self):
        """Case (b): a run uploaded the release copy and then failed to deploy, so the published copy is older. With
        the release unreadable, a cache miss and no dated copy, the published copy alone could lose what that run
        added: stop."""
        with self.assertRaises(RuntimeError):
            self.run_ledger(server_error, {"launches": [rec(1), rec(2)]})

    def test_older_published_copy_with_a_dated_copy_keeps_the_last_run(self):
        """Case (b) with the dated copy that last run uploaded beside the release copy: its launches are kept."""
        st, led = self.run_ledger(server_error, {"launches": [rec(1), rec(2)]},
                                  dated={"2026-11-27": {"launches": [rec(1), rec(2), rec(3)]}})
        self.assertEqual((st["published"], st["release"], st["dated"]), (True, False, "2026-11-27"))
        self.assertEqual({r["id"] for r in led["launches"]}, {"gcat:2026-001", "gcat:2026-002", "gcat:2026-003"})

    def test_release_lost_to_a_failed_upload_restores_from_the_dated_copy(self):
        """Case (a): the release copy answers 404 (a failed --clobber upload deleted it), the cache missed and the
        site is unreadable. Today's dated copy is missing too; yesterday's holds the launches, and none is lost."""
        st, led = self.run_ledger(not_found, server_error,
                                  dated={"2026-11-26": {"launches": [rec(1), rec(4), rec(5)]}})
        self.assertEqual((st["release"], st["dated"]), (False, "2026-11-26"))
        self.assertEqual({r["id"] for r in led["launches"]}, {"gcat:2026-001", "gcat:2026-004", "gcat:2026-005"})
        # The dated copies are read from the quarter's release, newest day first.
        dated = [u for u in self.urls if "/download/ledger-" in u]
        self.assertTrue(dated[0].endswith("/ledger-2026-q4/launch-ledger-2026-11-27.json"), dated[0])
        self.assertTrue(dated[1].endswith("/ledger-2026-q4/launch-ledger-2026-11-26.json"), dated[1])

    def test_a_merge_that_drops_an_id_stops(self):
        with mock.patch.object(cli.catalog, "merge", lambda *lgs: {"launches": [rec(1)]}):
            with self.assertRaises(RuntimeError):
                self.run_ledger({"launches": [rec(1), rec(3)]}, not_found)

    def test_release_readable_goes_on(self):
        st, led = self.run_ledger({"launches": [rec(1), rec(3)]}, server_error)
        self.assertEqual((st["status"], st["release"]), ("failed", True))
        self.assertIn("gcat:2026-003", {r["id"] for r in led["launches"]})

    def test_first_run_404s_go_on(self):
        st, led = self.run_ledger(not_found, not_found)
        self.assertEqual((st["published"], st["release"], st["dated"]), (False, False, None))
        self.assertEqual([r["id"] for r in led["launches"]], ["gcat:2026-001"])


if __name__ == "__main__":
    unittest.main()
