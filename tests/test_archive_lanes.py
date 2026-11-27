"""Private archive lanes: every file a run of update.yml leaves outside the tracked code (data/, site/) and the
history/ it ran with land in the private archive (tools/tic_archive.py, metacog-osint/tic-archive) and restore byte
for byte. A file that a later run removes, trims or replaces stays restorable from the snapshot that held it, and
the step before collect fills gaps in the state from the archive without overwriting what the cache gave back.

The test makes a real offline run in a temporary folder (collect against a stand-in network, build, the release
copies as the workflow makes them), with a trimmed copy of the committed history so the build is quick. It then
runs the workflow's own tic_archive.py commands, read from update.yml, against a local DirStore. Nothing reaches
GitHub: GhStore is replaced by the DirStore and any subprocess call during an archive command fails the test."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.append(str(ROOT / "tools"))   # after ROOT: tools/launch.py must not shadow the package
import tic_archive as ta  # noqa: E402
from launch import gnss, ll2ledger, news, schedule  # noqa: E402
from test_ascent_move import page, rec  # noqa: E402

_spec = importlib.util.spec_from_file_location("launch_cli_archive", ROOT / "tools" / "launch.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

WF = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
FIX = ROOT / "tests" / "fixtures"
PROGRAM = "launch"
RUN_OUTPUTS = ("data", "history", "site")          # what a run writes or runs with, beside the tracked code
RUN_INPUTS = ("doctrine", "site_src")              # tracked code the offline run is given
FIRST, SECOND = "20261127T060000Z", "20261127T120000Z"


def steps() -> dict[str, str]:
    """The workflow's steps by name (unnamed `uses:` steps by their action)."""
    out = {}
    for chunk in re.split(r"(?m)^      - ", WF.split("\n    steps:\n", 1)[1])[1:]:
        m = re.match(r"name: (.+)|uses: (\S+)", chunk)
        out[(m.group(1) or m.group(2)).strip()] = chunk
    return out


STEPS = steps()


def step(prefix: str) -> str:
    (name,) = [n for n in STEPS if n.startswith(prefix)]
    return STEPS[name]


def archive_calls(text: str, cmd: str) -> list[list[str]]:
    """Every `python tools/tic_archive.py <cmd> ...` in a step, as argv after the script name."""
    flat = text.replace("\\\n", " ")
    calls = []
    for m in re.finditer(r"python tools/tic_archive\.py (" + cmd + r")\b([^;|&\n]*)", flat):
        calls.append([m.group(1), *shlex.split(m.group(2))])
    return calls


def arg(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, t in enumerate(argv) if t == flag]


def put_calls() -> list[list[str]]:
    return [c for name in STEPS if name.startswith("Private archive") for c in archive_calls(STEPS[name], "put")]


def fill_script() -> str:
    """The Python the restore step runs to copy the archived state into data/ (its heredoc, dedented)."""
    text = step("Fill gaps in the state from the private archive")
    (body,) = re.findall(r"<<'PY'[^\n]*\n(.*?)\n\s*PY\n", text, re.S)
    return textwrap.dedent(body) + "\n"


def tree(root: Path) -> dict[str, str]:
    """{posix path relative to root: sha256} for every file."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def run_archive(argv: list[str], cwd: Path, store: Path, stamp: str = FIRST) -> int:
    """One tic_archive.py command as the workflow gives it, in cwd, against a DirStore at store."""
    def no_subprocess(*a, **k):
        raise AssertionError("an archive command tried to run a subprocess (gh): nothing may leave the test")

    old = os.getcwd()
    os.chdir(cwd)
    try:
        env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ta, "GhStore", lambda *a, **k: ta.DirStore(store)), \
                mock.patch.object(ta, "utc_stamp", lambda now=None: stamp), \
                mock.patch.object(subprocess, "run", no_subprocess):
            return ta.main(argv)
    finally:
        os.chdir(old)


def lane_paths(argv: list[str]) -> tuple[str, str]:
    """(lane, the run-tree folder its restored paths are relative to) for a single-source put."""
    (src,) = arg(argv, "--src")
    assert "=" not in src, "named sources: extend lane_paths"
    return arg(argv, "--lane")[0], src


# ---------- a real offline run ----------

def network(url: str, timeout: int = 0) -> bytes:
    """A stand-in for every request collect makes: Launch Library 2's upcoming list, Spaceflight News, Orbit's
    frozen LL2 ledger and one LL2 page; everything else answers 404 (a lane that fails keeps nothing)."""
    if url.startswith(schedule.LL2_API):
        return (FIX / "ll2_upcoming.json").read_bytes()
    if url.startswith(news.API):
        return (FIX / "snapi_articles.json").read_bytes()
    if url == ll2ledger.ORBIT_LEDGER:
        rows = [schedule.ll2_row(rec(i, f"2024-01-0{i}T00:00:00Z")) for i in (1, 2)]
        return json.dumps({"schema": "orbit-ledger/1", "start": ll2ledger.START, "launches": rows, "changes": [],
                           "caught_up": True, "updated_at": "2024-01-03T00:00:00Z"}).encode()
    if url.startswith(ll2ledger.PREVIOUS):
        return page(rec(2, "2024-01-02T00:00:00Z"), rec(3, "2024-01-03T00:00:00Z"))
    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def trimmed_history(src: Path, dest: Path) -> None:
    """The committed history/, every file, with the long lists cut short so the build takes seconds."""
    dest.mkdir(parents=True, exist_ok=True)
    cuts = {"history.json": ("events", 8), "ledger.json": ("launches", 40), "nfc.json": ("launches", 10),
            "joey.json": ("notices", 20), "nsf_links.json": ("links", 10)}
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue          # git-ignored folders (source copies, the private term file) are not in a run
        if p.name in cuts:
            doc = json.loads(p.read_text(encoding="utf-8"))
            key, n = cuts[p.name]
            doc[key] = doc[key][-n:]
            (dest / p.name).write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        elif p.name == "wayback.json":
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["tfrs"], doc["nga"] = doc["tfrs"][-10:], doc["nga"][-10:]
            (dest / p.name).write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(p, dest / p.name)


def release_copies(root: Path) -> None:
    """data/release-copy/ as the release step makes it (its cp lines are checked against update.yml below)."""
    out = root / "data" / "release-copy"
    out.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for src, name in (("ledger.json", "launch-ledger"), ("nms-closures.json", "nms-closures")):
        if (root / "data" / src).exists():
            shutil.copyfile(root / "data" / src, out / f"{name}.json")
            shutil.copyfile(root / "data" / src, out / f"{name}-{day}.json")


class RunTree:
    """A real offline run, made once: the cache's GNSS state from earlier runs, collect, the release copies, build."""
    tmp: Path | None = None
    old_run: str = ""
    day_file: str = ""

    @classmethod
    def make(cls) -> Path:
        if cls.tmp is not None:
            return cls.tmp
        tmp = Path(tempfile.mkdtemp(prefix="launch-lanes-"))
        for d in RUN_INPUTS:
            shutil.copytree(ROOT / d, tmp / d)
        trimmed_history(ROOT / "history", tmp / "history")
        # What the Actions cache gives back from earlier runs: the GNSS store with its run log, and a closed day file.
        now = datetime.now(timezone.utc).replace(microsecond=0)
        cls.old_run = (now - timedelta(days=gnss.RUNS_KEEP_DAYS - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cls.day_file = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        g = tmp / "data" / "gnss"
        (g / "days").mkdir(parents=True)
        (g / "store.json").write_text(json.dumps({**gnss.empty(), "runs": [{"at": cls.old_run, "status": "ok"}]}),
                                      encoding="utf-8", newline="\n")
        (g / "days" / f"{cls.day_file}.json").write_text(json.dumps({"day": cls.day_file, "n": 0, "notices": []}),
                                                         encoding="utf-8", newline="\n")
        cli.collect(tmp, getter=network)
        release_copies(tmp)
        cli.build_site(tmp)
        cls.tmp = tmp
        return tmp


def tearDownModule():
    if RunTree.tmp is not None:
        shutil.rmtree(RunTree.tmp, ignore_errors=True)


# ---------- the workflow ----------

class TestWorkflowLanes(unittest.TestCase):
    def test_lanes_are_raw_state_history_site(self):
        lanes = {arg(c, "--lane")[0]: c for c in put_calls()}
        self.assertEqual(set(lanes), {"raw", "state", "history", "site"})
        self.assertEqual(len(put_calls()), 4)
        for c in lanes.values():
            self.assertEqual(arg(c, "--program"), [PROGRAM])
        self.assertEqual(arg(lanes["raw"], "--src"), ["data/raw"])
        self.assertEqual(arg(lanes["state"], "--src"), ["data"])
        self.assertEqual(arg(lanes["state"], "--exclude"), ["raw/*", "release-copy/*"])   # raw has its own lane
        self.assertEqual(arg(lanes["history"], "--src"), ["history"])
        self.assertEqual(arg(lanes["site"], "--src"), ["site"])
        for lane, c in lanes.items():          # no key in any reply, so the archived bytes are the run's bytes
            self.assertFalse([t for t in c if t.startswith("--redact") or t == "--include"], lane)

    def test_step_last_and_loud_on_failure(self):
        names = list(STEPS)
        new = names.index("Private archive (raw replies, run state, history and site, to tic-archive)")
        self.assertEqual(new, len(names) - 1)
        for before in ("Deploy site/ to Cloudflare Pages", "Keep this run's state for the next run",
                       "Keep the schedule, the LL2 ledger and the comparison for good (release `ledger`)"):
            self.assertGreater(new, names.index(before), before)
        text = STEPS[names[new]]
        self.assertIn("if: ${{ !cancelled() }}", text)
        self.assertIn("GH_TOKEN: ${{ secrets.TIC_ARCHIVE_TOKEN }}", text)
        self.assertNotIn("github.token", text)
        self.assertNotIn("|| true", text)
        self.assertIn('[ -z "$GH_TOKEN" ]', text)
        self.assertEqual(text.count("exit 1"), 2)            # token missing; any lane failed
        self.assertEqual(text.count("|| failed=1"), 4)       # each lane tried even if another failed

    def test_each_lane_only_after_the_step_that_writes_it(self):
        text = step("Private archive (raw")
        self.assertIn("COLLECTED: ${{ steps.collect.outcome }}", text)
        self.assertIn("DEPLOYED: ${{ steps.deploy.outcome }}", text)
        self.assertIn("id: collect", step("Live collection"))
        self.assertIn("id: deploy", STEPS["Deploy site/ to Cloudflare Pages"])
        flat = text.replace("\\\n", " ")
        self.assertRegex(flat, r'if \[ -d data/raw \]; then\s+python tools/tic_archive\.py put '
                               r'--program launch --lane raw ')
        self.assertRegex(flat, r'if \[ "\$COLLECTED" = "success" \]; then\s+python tools/tic_archive\.py put '
                               r'--program launch --lane state ')
        self.assertRegex(flat, r'if \[ "\$DEPLOYED" = "success" \]; then\s+python tools/tic_archive\.py put '
                               r'--program launch --lane site ')
        self.assertRegex(flat, r'(?m)^\s+python tools/tic_archive\.py put --program launch --lane history ')

    def test_what_the_workflow_keeps_for_a_while_or_replaces_is_inside_the_archived_folders(self):
        # The Actions cache (evicted after 7 days unused) holds these paths; the cache key's path list is unchanged.
        save = STEPS["Keep this run's state for the next run"]
        cached = re.findall(r"(?m)^\s{12}(\S+)\s*$", save.split("path: |", 1)[1].split("key:", 1)[0])
        self.assertEqual(cached, ["data/snapshot.json", "data/ledger.json", "data/gnss"])
        restore = STEPS["Last run's state from the Actions cache (none on the first run)"]
        self.assertEqual(re.findall(r"(?m)^\s{12}(\S+)\s*$", restore.split("path: |", 1)[1].split("key:", 1)[0]),
                         cached)
        for p in cached:
            self.assertTrue(p.startswith("data/") and not p.startswith(("data/raw", "data/release-copy")), p)
        # Release `ledger` is replaced each run (--clobber), and so is a day's dated copy: data/ holds every one.
        stores = step("Keep the schedule, the LL2 ledger and the comparison")
        self.assertIn("for f in upcoming-store.json ll2-ledger.json ascent-compare.json; do", stores)
        self.assertIn('files="$files data/$f"', stores)
        copies = step("Keep the launch ledger and the NMS closure ledger")
        for line in ('cp data/ledger.json "$out/launch-ledger.json"', 'cp data/ledger.json "$out/launch-ledger-$day.json"',
                     'cp data/nms-closures.json "$out/nms-closures.json"',
                     'cp data/nms-closures.json "$out/nms-closures-$day.json"'):
            self.assertIn(line, copies)                     # what release_copies() above makes
        self.assertIn("out=data/release-copy", copies)
        self.assertIn("pages deploy site --project-name launch", step("Deploy site/"))


# ---------- the run's files ----------

class TestEveryRunFileIsArchived(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_root = RunTree.make()
        cls.work = Path(tempfile.mkdtemp(prefix="launch-store-"))
        cls.store = cls.work / "store"
        cls.before = {top: tree(cls.run_root / top) for top in RUN_OUTPUTS}
        cls.results = {}
        for argv in put_calls():
            cls.results[arg(argv, "--lane")[0]] = run_archive(argv, cls.run_root, cls.store, FIRST)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def restore_all(self, dest: Path, snapshots: dict[str, str] | None = None) -> dict[str, str]:
        """Every lane restored, mapped back to run-tree paths: {path: sha256}."""
        got = {}
        for argv in put_calls():
            lane, src = lane_paths(argv)
            cmd = ["restore", "--program", PROGRAM, "--lane", lane, "--dest", str(dest / lane)]
            if snapshots and lane in snapshots:
                cmd += ["--snapshot", snapshots[lane]]
            self.assertEqual(run_archive(cmd, self.run_root, self.store), 0, lane)
            for rel, sha in tree(dest / lane).items():
                path = f"{src}/{rel}"
                self.assertNotIn(path, got, "two lanes hold the same file")
                got[path] = sha
        return got

    def snapshot_names(self, stamp: str) -> dict[str, str]:
        out = {}
        for tag in self.store.iterdir():
            for p in tag.iterdir():
                if p.name.startswith(stamp) and p.name.endswith(".files.json"):
                    out[tag.name[len(PROGRAM) + 1:].rsplit("-", 2)[0]] = p.name
        return out

    def test_the_offline_run_writes_only_the_known_folders(self):
        self.assertEqual({p.name for p in self.run_root.iterdir()}, set(RUN_INPUTS) | set(RUN_OUTPUTS))
        for top in RUN_OUTPUTS:
            self.assertTrue(self.before[top], top)
        self.assertTrue([p for p in self.before["data"] if p.startswith("raw/")])

    def test_every_put_succeeded(self):
        self.assertEqual(self.results, {"raw": 0, "state": 0, "history": 0, "site": 0})

    def test_every_file_of_the_run_restores_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            got = self.restore_all(Path(td), self.snapshot_names(FIRST))
        want = {f"{top}/{rel}": sha for top, files in self.before.items() for rel, sha in files.items()}
        # The release copies are byte copies of data/ledger.json and data/nms-closures.json, which the state holds.
        copies = {p: s for p, s in want.items() if p.startswith("data/release-copy/")}
        self.assertEqual(len(copies), 4)
        for p, s in copies.items():
            self.assertIn(s, {got.get("data/ledger.json"), got.get("data/nms-closures.json")}, p)
            del want[p]
        self.assertEqual(sorted(set(want) - set(got)), [], "files of the run missing from the archive")
        self.assertEqual(sorted(set(got) - set(want)), [], "the archive holds files the run did not write")
        self.assertEqual({p: s for p, s in got.items() if want[p] != s}, {}, "restored bytes differ")
        # What other programs read from the site, every store collect keeps, and the source copies' licences.
        for p in ("site/data/snapshot.json", "site/data/feed.geojson", "site/data/launches.json",
                  "site/data/gnss-notams/index.json", f"site/data/gnss-notams/{RunTree.day_file}.json",
                  "data/snapshot.json", "data/ledger.json", "data/nms-closures.json", "data/upcoming-store.json",
                  "data/ll2-ledger.json", "data/gnss/store.json", f"data/gnss/days/{RunTree.day_file}.json",
                  "data/raw/index.jsonl", "history/ledger.json", "history/history.json", "history/nfc.json",
                  "history/joey.json", "history/wayback.json", "history/NOTAMFORCHINA-LICENSE.txt",
                  "history/JOEY-NOTAMS-LICENSE.txt"):
            self.assertIn(p, got)

    def test_removed_trimmed_or_replaced_files_stay_restorable(self):
        root = self.run_root
        paths = ("history/wayback.json", "data/gnss/store.json", "data/snapshot.json", "data/ledger.json",
                 "site/data/launches.json")
        old = {p: (root / p).read_bytes() for p in paths}
        self.assertIn(RunTree.old_run.encode(), old["data/gnss/store.json"])
        try:
            # The next run: a history file no longer committed (a cap), the GNSS run log trimmed as gnss.prune
            # does once the old run is past RUNS_KEEP_DAYS, a new snapshot and ledger, a new deploy.
            (root / "history/wayback.json").unlink()
            s = json.loads(old["data/gnss/store.json"])
            s = gnss.prune(s, datetime.now(timezone.utc) + timedelta(days=2))
            self.assertNotIn(RunTree.old_run, json.dumps(s))
            (root / "data/gnss/store.json").write_text(json.dumps(s), encoding="utf-8", newline="\n")
            for p in ("data/snapshot.json", "data/ledger.json"):
                (root / p).write_bytes(old[p].replace(b"{", b'{"run":2,', 1))
            (root / "site/data/launches.json").write_bytes(old["site/data/launches.json"] + b"\n")
            for argv in put_calls():
                if arg(argv, "--lane")[0] != "raw":
                    self.assertEqual(run_archive(argv, root, self.store, SECOND), 0)
            first, second = self.snapshot_names(FIRST), self.snapshot_names(SECOND)
            self.assertEqual(set(first), {"raw", "state", "history", "site"})
            self.assertEqual(set(second), {"state", "history", "site"})
            with tempfile.TemporaryDirectory() as td:
                now = self.restore_all(Path(td) / "now")
                then = self.restore_all(Path(td) / "then", first)
            self.assertNotIn("history/wayback.json", now)
            for p, data in old.items():
                self.assertEqual(then[p], hashlib.sha256(data).hexdigest(), p)
                if (root / p).exists():
                    self.assertEqual(now[p], hashlib.sha256((root / p).read_bytes()).hexdigest(), p)
                    self.assertNotEqual(now[p], then[p], p)
        finally:
            for p, data in old.items():
                (root / p).parent.mkdir(parents=True, exist_ok=True)
                (root / p).write_bytes(data)


# ---------- reading the state back ----------

class TestStateFromTheArchive(unittest.TestCase):
    """The step before collect: the archive's lane `state` fills what the cache and release `ledger` lack."""

    def test_order_cache_then_archive_then_collect(self):
        names = list(STEPS)
        i_cache = names.index("Last run's state from the Actions cache (none on the first run)")
        (fill,) = [n for n in names if n.startswith("Fill gaps in the state from the private archive")]
        self.assertLess(i_cache, names.index(fill))
        self.assertLess(names.index(fill), names.index(next(n for n in names if n.startswith("Live collection"))))

    def test_reads_the_state_lane_and_never_stops_the_run(self):
        text = step("Fill gaps in the state from the private archive")
        self.assertIn("ARCHIVE_TOKEN: ${{ secrets.TIC_ARCHIVE_TOKEN }}", text)
        self.assertIn("CACHED: ${{ steps.state.outputs.cache-matched-key }}", text)
        self.assertIn('GH_TOKEN="$ARCHIVE_TOKEN" python tools/tic_archive.py restore', text.replace("\\\n", " "))
        (call,) = archive_calls(text, "restore")
        self.assertEqual(arg(call, "--program"), [PROGRAM])
        self.assertEqual(arg(call, "--lane"), ["state"])
        self.assertEqual(arg(call, "--dest"), ["$RUNNER_TEMP/archive-state"])        # not data/ itself
        self.assertNotIn("exit 1", text)
        self.assertNotIn("::error::", text)
        # The release assets it looks for are the stores collect reads back from release `ledger`.
        (names,) = re.findall(r"for f in ([^;]+); do", text)
        self.assertEqual(set(names.split()), {cli.STORE["upcoming"], cli.STORE["ll2"], cli.RELEASE_COPY["ledger"],
                                              cli.RELEASE_COPY["closures"]})

    def test_fills_only_what_data_lacks(self):
        run_root = RunTree.make()
        (call,) = archive_calls(step("Fill gaps in the state from the private archive"), "restore")
        (state_put,) = [c for c in put_calls() if arg(c, "--lane") == ["state"]]
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self.assertEqual(run_archive(state_put, run_root, td / "store"), 0)
            fresh = td / "next-run"
            (fresh / "data").mkdir(parents=True)
            (fresh / "data" / "snapshot.json").write_bytes(b'{"from": "the Actions cache"}\n')   # newer: stays
            runner_temp = td / "runner-temp"
            argv = [t.replace("$RUNNER_TEMP", str(runner_temp)) for t in call]
            self.assertEqual(run_archive(argv, fresh, td / "store"), 0)
            r = subprocess.run([sys.executable, "-", str(runner_temp / "archive-state"), "data"], input=fill_script(),
                               cwd=fresh, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = tree(fresh / "data")
            want = {rel: sha for rel, sha in tree(run_root / "data").items()
                    if not rel.startswith(("raw/", "release-copy/"))}
            self.assertEqual(got.pop("snapshot.json"), hashlib.sha256(b'{"from": "the Actions cache"}\n').hexdigest())
            self.assertEqual(got, {k: v for k, v in want.items() if k != "snapshot.json"})
            for p in ("ledger.json", "nms-closures.json", "upcoming-store.json", "ll2-ledger.json", "gnss/store.json"):
                self.assertIn(p, got)
            self.assertIn(f"{len(got)} files from the private archive", r.stdout)


if __name__ == "__main__":
    unittest.main()
