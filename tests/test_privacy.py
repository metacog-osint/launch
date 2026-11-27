"""Offline tests for the privacy check (launch/privacy.py) and for the import's refusal to run without the private
term file. Every private word here is made up, and the strings the public rules must catch are put together at run
time, so this file holds nothing the check itself would refuse.
Run: python -m unittest discover -s tests"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import history, privacy  # noqa: E402

AT = "@"
DRIVE = "Q" + ":" + "\\"


class Rules(unittest.TestCase):
    def test_public_rules(self):
        self.assertEqual(privacy.hits("write to someone" + AT + "example.org today"), {"an email address": 1})
        self.assertEqual(privacy.hits("see " + DRIVE + "Proj" + "ects\\x and /q/Us" + "ers/y"), {"a local path": 2})
        self.assertEqual(privacy.hits("@media (max-width: 600px) {} and a.b@c"), {})

    def test_listed_words_by_hash_in_any_form(self):
        word_sha = frozenset({privacy.sha("zebrafish")})
        text = 'Zebrafish, ZEBRAFISH\'s note, zebrafish_time, "zebrafish", src=zebrafish, zebrafishById, Zebrafishes'
        self.assertEqual(privacy.hits(text, word_sha=word_sha), {"a listed name": 6})

    def test_private_rules_and_pairs_from_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "terms.json"
            p.write_text(json.dumps({"check": [r"\bQQSECRET\b"], "check_pair_sha256": [privacy.sha("alpha bravo")]}))
            private = privacy.private_terms(p)
        found = privacy.hits("qqsecret QQSECRET. Met Alpha  Bravo, not alpha charlie.", private)
        self.assertEqual(found, {"private term 1": 1, "a listed person": 1})
        self.assertIsNone(privacy.private_terms(Path("no/such/terms.json")))

    def test_only_the_copyright_line_is_set_aside_in_licence_files(self):
        word_sha = frozenset({privacy.sha("zebrafish")})
        line = "Copyright © 2026 Zebrafish Quux, The Intelligence Company."
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "NOTICE").write_text(line + "\n", encoding="utf-8")
            (root / "README.md").write_text(line + " Zebrafish wrote this.\n", encoding="utf-8")
            (root / "docs.md").write_text(line + "\n", encoding="utf-8")
            real = privacy.hits
            with mock.patch.object(privacy, "hits", lambda t, pr=None: real(t, pr, word_sha=word_sha)):
                fail, _ = privacy.scan(["NOTICE", "README.md", "docs.md"], root)
        self.assertEqual(fail, [("README.md", "a listed name", 1), ("docs.md", "a listed name", 1)])

    def test_shared_copies_are_reported_apart(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ("site_src/tic-nav.js", "launch/x.py", "site_src/vendor/lib.js"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("mail someone" + AT + "example.org", encoding="utf-8")
            fail, shared = privacy.scan(["site_src/tic-nav.js", "launch/x.py", "site_src/vendor/lib.js"], root)
        self.assertEqual(fail, [("launch/x.py", "an email address", 1)])
        self.assertEqual(shared, [("site_src/tic-nav.js", "an email address", 1)])


class Repository(unittest.TestCase):
    def test_no_listed_term_in_tracked_files_or_the_built_site(self):
        """The regression test: public rules always, the private file's rules too where it is here."""
        if privacy.tracked_files() is None:
            self.skipTest("git is not available")
        errs, _ = privacy.problems()
        self.assertEqual(errs, [])


class ImportNeedsTerms(unittest.TestCase):
    def test_load_refuses_without_terms(self):
        with mock.patch.object(history, "_TERMS_SET", False):
            with self.assertRaises(SystemExit):
                history.load("<kml/>")

    def test_load_terms_refuses_without_the_file(self):
        with mock.patch.object(history, "TERMS_FILE", Path("no/such/terms.json")):
            with self.assertRaises(SystemExit):
                history.load_terms(Path("nor/this.json"))


def str_hash(s: str) -> int:
    """site_src/history.js strHash: h * 31 + code unit, as a signed 32-bit integer."""
    h = 0
    for ch in s.encode("utf-16-le").decode("utf-16-le"):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h - (1 << 32) if h >= (1 << 31) else h


class LegacyAddresses(unittest.TestCase):
    """Old addresses' values are matched by hash (history.js LEGACY). No current value may share one."""

    def test_no_current_value_shares_a_legacy_hash(self):
        js = (ROOT / "site_src" / "history.js").read_text(encoding="utf-8")
        legacy = {int(x) for x in re.findall(r'"?(-?\d{4,})"?:\s*"', js.split("const LEGACY")[1].split("\n")[0])}
        self.assertEqual(len(legacy), 2)
        sources = re.search(r"const SOURCES = \{([^}]*)\}", js).group(1)
        current = re.findall(r"(\w+):", sources) + ["As charted", "Estimated from an azimuth", "None"]
        self.assertTrue(current)
        self.assertFalse({str_hash(v) for v in current} & legacy)
        self.assertEqual(str_hash("chart"), 94623710)  # the same function as the page's


if __name__ == "__main__":
    unittest.main()
