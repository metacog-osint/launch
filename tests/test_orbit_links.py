"""Links to Orbit (site_src/app.js, site_src/history.js): a launch's objects are Orbit's, found by GCAT's tag. The
kinds that get the link match launch/programs.py, and the addresses use Orbit's launch-row ids and search form."""
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launch import programs as P  # noqa: E402


class OrbitLinks(unittest.TestCase):
    def test_addresses(self):
        app = (ROOT / "site_src" / "app.js").read_text(encoding="utf-8")
        hist = (ROOT / "site_src" / "history.js").read_text(encoding="utf-8")
        self.assertIn('ORBIT.site + "launches.html#launch-"', app)          # Orbit's row ids: launch-<tag>
        self.assertIn('"?q=" + encodeURIComponent(tag) + "#obj-search"', app)
        self.assertIn('orbit.theintelligence.company/?q=" + encodeURIComponent(r.gcat) + "#obj-search"', hist)
        self.assertIn("if (LP.inOrbit(r))", hist)                          # History's link
        self.assertIn("if (!LP.inOrbit(r)) return box;", app)              # Past 7 days' payloads cell
        self.assertNotIn("snap.orbit || {}).upcoming", app)                # Orbit publishes no schedule


NODE = shutil.which("node")
LP = (ROOT / "site_src" / "livepaths.js").as_uri()


@unittest.skipUnless(NODE, "Node is not installed")
class InOrbit(unittest.TestCase):
    def test_only_orbital_launches_with_a_tag(self):
        recs = [{"gcat": "2026-266", "kind": k} for k in P.KINDS] + [{"kind": P.ORBITAL}, {"gcat": "", "kind": P.ORBITAL}]
        script = "const LP = await import(%s); console.log(JSON.stringify(%s.map(LP.inOrbit)));" % (
            json.dumps(LP), json.dumps(recs))
        r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got, [k == P.ORBITAL for k in P.KINDS] + [False, False])
        self.assertEqual(P.KINDS[0], "Orbital")   # the literal in livepaths.js


if __name__ == "__main__":
    unittest.main()
