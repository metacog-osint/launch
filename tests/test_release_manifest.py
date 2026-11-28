"""Release checksums (tools/release_manifest.py) and the workflow step that publishes them."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("launch_release_manifest", ROOT / "tools" / "release_manifest.py")
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)
WF = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")


def asset(name: str, data: bytes, digest: bool = True) -> dict:
    return {"name": name, "size": len(data), "updated_at": "2026-11-27T00:00:00Z",
            "digest": "sha256:" + hashlib.sha256(data).hexdigest() if digest else None}


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        (self.dir / "copy").mkdir()
        (self.dir / "data").mkdir()

    def test_lists_every_file_but_its_own_and_verifies(self):
        (self.dir / "copy" / "a.json").write_bytes(b"one")
        (self.dir / "data" / "b.json").write_bytes(b"two")
        assets = [asset("b.json", b"two"), asset("a.json", b"one"), asset("old.json", b"three"),
                  asset(rm.SUMS, b"x"), asset(rm.JSON_NAME, b"y")]
        m = rm.build("o/r", "ledger", assets, (self.dir / "copy", self.dir / "data"))
        self.assertEqual([f["name"] for f in m["files"]], ["a.json", "b.json", "old.json"])
        self.assertEqual(m["format"], "launch-manifest/1")
        self.assertIn(f"{hashlib.sha256(b'one').hexdigest()}  a.json\n", rm.sums_text(m))
        self.assertEqual(rm.verify(m, self.dir / "copy"), [])
        (self.dir / "copy" / "a.json").write_bytes(b"changed")
        self.assertEqual(len(rm.verify(m, self.dir / "copy")), 1)

    def test_a_local_copy_that_differs_from_the_upload_fails(self):
        (self.dir / "data" / "a.json").write_bytes(b"mine")
        with self.assertRaises(rm.Mismatch):
            rm.build("o/r", "ledger", [asset("a.json", b"theirs")], (self.dir / "data",))

    def test_no_digest_and_no_local_copy_fails(self):
        with self.assertRaises(rm.Mismatch):
            rm.build("o/r", "ledger", [asset("a.json", b"one", digest=False)])

    def test_unchanged_release_is_not_uploaded_again(self):
        assets = [asset("a.json", b"one")]
        self.assertTrue(rm.release("o/r", "ledger", self.dir / "out", assets=assets))
        own = [asset(n, (self.dir / "out" / n).read_bytes()) for n in rm.OWN]
        self.assertFalse(rm.release("o/r", "ledger", self.dir / "out", assets=assets + own))
        written = json.loads((self.dir / "out" / rm.JSON_NAME).read_text(encoding="utf-8"))
        self.assertEqual(written["release"], "ledger")


class TestWorkflowStep(unittest.TestCase):
    def test_runs_after_both_uploads_and_before_the_archive(self):
        names = re.findall(r"(?m)^      - name: (.+)$", WF)
        i = names.index("Release checksums")
        for before in ("Keep the schedule", "Keep the launch ledger", "Deploy site/"):
            self.assertLess(next(n for n, s in enumerate(names) if s.startswith(before)), i, before)
        self.assertEqual(i, len(names) - 2)
        step = WF.split("      - name: Release checksums\n", 1)[1].split("\n      # What this public", 1)[0]
        self.assertIn("steps.stores.outcome == 'success' && steps.copies.outcome == 'success'", step)
        self.assertRegex(step, r"(?m)^        timeout-minutes: 3$")
        self.assertIn('out="data/manifest/$tag"', step)
        self.assertIn(f'"$out/{rm.SUMS}" "$out/{rm.JSON_NAME}" --clobber', step)
        self.assertIn("id: stores", WF)
        self.assertIn("id: copies", WF)


if __name__ == "__main__":
    unittest.main()
