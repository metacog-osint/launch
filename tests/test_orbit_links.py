"""Links to Orbit (site_src/app.js, site_src/history.js): a launch's objects are Orbit's, found by GCAT's tag. The
kinds that get the link match launch/programs.py, and the addresses use Orbit's launch-row ids and search form."""
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import programs as P  # noqa: E402


class OrbitLinks(unittest.TestCase):
    def test_orbital_kinds_match_programs(self):
        src = (ROOT / "site_src" / "history.js").read_text(encoding="utf-8")
        m = re.search(r"const ORBITAL_KINDS = (\[[^\]]*\]);", src)
        self.assertIsNotNone(m)
        self.assertEqual(tuple(json.loads(m.group(1))), P.ORBITAL_KINDS)

    def test_addresses(self):
        app = (ROOT / "site_src" / "app.js").read_text(encoding="utf-8")
        hist = (ROOT / "site_src" / "history.js").read_text(encoding="utf-8")
        self.assertIn('ORBIT.site + "launches.html#launch-"', app)          # Orbit's row ids: launch-<tag>
        self.assertIn('"?q=" + encodeURIComponent(tag) + "#obj-search"', app)
        self.assertIn('orbit.theintelligence.company/?q=" + encodeURIComponent(r.gcat) + "#obj-search"', hist)
        self.assertNotIn("snap.orbit || {}).upcoming", app)                # Orbit publishes no schedule


if __name__ == "__main__":
    unittest.main()
