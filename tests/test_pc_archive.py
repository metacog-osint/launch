"""Private archive after the PC-only commands: `launch.py payloads` and `nfc|joey|wayback fetch` write their folders
first, then put the payloads or copies lane (tools/tic_archive.py) against a local DirStore here. A failed put
prints an error and exits non-zero, after the local files are written; --no-archive skips the put."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
sys.path.append(str(ROOT / "tools"))   # after ROOT: tools/launch.py must not shadow the package
import tic_archive as ta  # noqa: E402

_spec = importlib.util.spec_from_file_location("launch_cli_pc_archive", ROOT / "tools" / "launch.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class FailingStore(ta.DirStore):
    def upload(self, tag, paths):
        raise ta.ArchiveError("upload refused")


class PcArchive(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name)
        self.root, self.store = base / "repo", base / "store"
        (self.root / "history").mkdir(parents=True)
        (self.root / "history" / "history.json").write_text("{}", encoding="utf-8")   # public, not in a lane
        self.patches = [mock.patch.object(cli, "ROOT", self.root),
                        mock.patch.object(cli, "PAYLOADS_DIR", self.root / "history" / "payloads_source"),
                        mock.patch("subprocess.run", side_effect=AssertionError("no subprocess in tests"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.td.cleanup()

    def run_cli(self, argv, store_cls=ta.DirStore):
        with mock.patch.object(ta, "GhStore", lambda *a, **k: store_cls(self.store)):
            return cli.main(argv)

    def snapshots(self, lane):
        arch = ta.Archive(ta.DirStore(self.store), "launch", lane)
        return sorted(n for t in arch.store.tags(arch.prefix) for n in arch.store.assets(t) if n.endswith(".files.json"))

    def restored(self, lane):
        dest = Path(self.td.name) / f"restore-{lane}"
        ta.Archive(ta.DirStore(self.store), "launch", lane).restore(dest)
        return sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())

    def fake_payloads(self, data=None, out=None, **kw):
        out.mkdir(parents=True, exist_ok=True)
        with (out / "ledger.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"n": 1}) + "\n")
        (out / "rates.json").write_text("{}", encoding="utf-8")
        return {"launches": 0, "new_ledger_lines": 1, "score": {}, "results": []}

    def test_payloads_puts_its_lane(self):
        with mock.patch.object(cli, "run_payloads", self.fake_payloads):
            self.assertEqual(self.run_cli(["payloads"]), 0)
            self.assertEqual(len(self.snapshots("payloads")), 1)
            self.assertEqual(self.restored("payloads"), ["ledger.jsonl", "rates.json"])
            self.assertEqual(self.run_cli(["payloads"]), 0)   # the ledger grew: a second snapshot, nothing replaced
        self.assertEqual(len(self.snapshots("payloads")), 2)

    def test_fetches_put_the_copies_lane(self):
        def writer(name):
            def fetch(src, **kw):
                src.mkdir(parents=True, exist_ok=True)
                (src / f"{name}.txt").write_text(name, encoding="utf-8")
                return {"files": 1}
            return fetch
        (self.root / "history" / "NOTAMFORCHINA-LICENSE.txt").write_text("licence", encoding="utf-8")
        with mock.patch.object(cli.nfc, "fetch", writer("nfc")), mock.patch.object(cli.joey, "fetch", writer("joey")), \
                mock.patch.object(cli.wayback, "fetch", writer("wayback")):
            for argv in (["nfc", "fetch"], ["joey", "fetch"], ["wayback", "fetch"]):
                self.assertEqual(self.run_cli(argv), 0, argv)
        self.assertEqual(len(self.snapshots("copies")), 3)
        self.assertEqual(self.restored("copies"), ["history/NOTAMFORCHINA-LICENSE.txt", "history/joey_source/joey.txt",
                                                   "history/nfc_source/nfc.txt", "history/wayback_source/wayback.txt"])

    def test_failed_put_exits_nonzero_after_the_local_write(self):
        with mock.patch.object(cli, "run_payloads", self.fake_payloads), mock.patch.object(ta, "error") as err:
            self.assertEqual(self.run_cli(["payloads"], FailingStore), 1)
        self.assertTrue((self.root / "history" / "payloads_source" / "ledger.jsonl").exists())
        self.assertIn("after the local write", err.call_args[0][0])
        self.assertEqual(self.snapshots("payloads"), [])

    def test_no_archive_skips_the_put(self):
        with mock.patch.object(cli, "run_payloads", self.fake_payloads), \
                mock.patch.object(ta, "GhStore", side_effect=AssertionError("no put with --no-archive")):
            self.assertEqual(cli.main(["payloads", "--no-archive"]), 0)

    def test_a_failed_fetch_puts_nothing(self):
        def boom(src, **kw):
            raise OSError("network down")
        with mock.patch.object(cli.joey, "fetch", boom), \
                mock.patch.object(ta, "GhStore", side_effect=AssertionError("no put before the local write")):
            with self.assertRaises(OSError):
                cli.main(["joey", "fetch"])


if __name__ == "__main__":
    unittest.main()
