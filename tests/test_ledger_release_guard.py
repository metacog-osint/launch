"""tools/launch.py update_ledger: a run that can read neither the release copy of the launch ledger (anything but a
404) nor the published copy stops before writing, so the workflow never uploads a possibly smaller ledger over the
release's copy and that day's dated copy."""
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

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
    def run_ledger(self, release, site, cached=None):
        """release / site: a ledger dict to serve, or a function url -> exception to raise."""
        def get(url, timeout=0):
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

    def test_release_and_site_unreadable_stops_even_with_a_local_copy(self):
        # The local copy (a restored or stale cache) lacks what the release holds; writing it would be uploaded.
        with self.assertRaises(RuntimeError):
            self.run_ledger(server_error, server_error, cached={"launches": [rec(1)]})
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

    def test_site_readable_goes_on(self):
        st, led = self.run_ledger(server_error, {"launches": [rec(1), rec(2)]})
        self.assertEqual((st["published"], st["release"]), (True, False))
        self.assertEqual({r["id"] for r in led["launches"]}, {"gcat:2026-001", "gcat:2026-002"})

    def test_release_readable_goes_on(self):
        st, led = self.run_ledger({"launches": [rec(1), rec(3)]}, server_error)
        self.assertEqual((st["status"], st["release"]), ("failed", True))
        self.assertIn("gcat:2026-003", {r["id"] for r in led["launches"]})

    def test_first_run_404s_go_on(self):
        st, led = self.run_ledger(not_found, not_found)
        self.assertEqual((st["published"], st["release"]), (False, False))
        self.assertEqual([r["id"] for r in led["launches"]], ["gcat:2026-001"])


if __name__ == "__main__":
    unittest.main()
