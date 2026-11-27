"""Private archive lanes: every file a run of update.yml leaves outside the tracked code (data/, site/) and the
history/ it ran with land in the private archive (tools/tic_archive.py, metacog-osint/tic-archive) and restore byte
for byte. A file that a later run removes, trims or replaces stays restorable from the snapshot that held it, and
the step before collect fills gaps in the state from the archive without overwriting what the cache gave back.

The test makes a real offline run in a temporary folder (collect against a stand-in network, build, the release
copies as the workflow makes them), with a trimmed copy of the committed history so the build is quick. It then
runs the workflow's own tic_archive.py commands, read from update.yml, against a local DirStore. Nothing reaches
GitHub: GhStore is replaced by the DirStore and any subprocess call during an archive command fails the test."""
from __future__ import annotations

import gzip
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
from launch import fetch, gnss, ll2ledger, news, schedule  # noqa: E402
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


def run_block(text: str) -> str:
    """A step's `run: |` script as Actions hands it to bash: the block's lines with their indentation removed."""
    lines = text.split("\n")
    (i,) = [n for n, line in enumerate(lines) if line.strip() == "run: |"]
    body = []
    for line in lines[i + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break                                   # the comments above the next step
        body.append(line)
    return textwrap.dedent("\n".join(body)).strip("\n") + "\n"


def find_bash() -> str | None:
    """bash as Actions runs it. On Windows only Git's bash (System32's bash is WSL, which does not see this tree)."""
    if os.name == "nt":
        p = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(p) if p.exists() else None
    return shutil.which("bash")


BASH = find_bash()


def stub(bin_dir: Path, name: str, body: str) -> None:
    """A stand-in command on PATH (a shell script; Git's bash runs one without an extension too)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    f = bin_dir / name
    f.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    f.chmod(0o755)


def run_step_shell(text: str, cwd: Path, env: dict[str, str], bin_dir: Path) -> subprocess.CompletedProcess:
    """A step's own script under bash as Actions runs it (-e, pipefail), with stand-ins first on PATH and `python`
    the interpreter running the tests."""
    stub(bin_dir, "python", f'exec "{Path(sys.executable).as_posix()}" "$@"\n')
    script = cwd.parent / f"{cwd.name}-step.sh"
    script.write_text(run_block(text), encoding="utf-8", newline="\n")
    full = {**os.environ, **env, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    return subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", script.as_posix()], cwd=cwd, env=full,
                          capture_output=True, text=True, timeout=120)


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
        self.assertIn("DEPLOYED: ${{ steps.deploy.outputs.deployed }}", text)   # not the outcome: a skip succeeds
        self.assertIn("id: collect", step("Live collection"))
        self.assertIn("id: deploy", STEPS["Deploy site/ to Cloudflare Pages"])
        flat = text.replace("\\\n", " ")
        self.assertRegex(flat, r'if \[ -d data/raw \]; then\s+python tools/tic_archive\.py put '
                               r'--program launch --lane raw ')
        self.assertRegex(flat, r'if \[ "\$COLLECTED" = "success" \]; then\s+python tools/tic_archive\.py put '
                               r'--program launch --lane state ')
        self.assertRegex(flat, r'if \[ "\$DEPLOYED" = "true" \]; then\s+python tools/tic_archive\.py put '
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
        # What it may fill: the Actions cache's own paths, and the stores collect reads back from release `ledger`
        # (data/ledger.json, filed there as launch-ledger.json, is a cache path).
        cached, released = re.findall(r"for f in ([^;]+); do", text)
        cache_paths = re.findall(r"(?m)^\s{12}data/(\S+)\s*$", STEPS["Keep this run's state for the next run"])
        self.assertEqual(cached.split(), cache_paths)
        self.assertEqual(set(released.split()), {cli.STORE["upcoming"], cli.STORE["ll2"], cli.STORE["compare"],
                                                 cli.RELEASE_COPY["closures"]})
        self.assertNotIn("2>/dev/null || true", text)          # a failed listing is not read as "the release is empty"

    def test_bounded_in_time_and_never_fails_the_job(self):
        fill = step("Fill gaps in the state from the private archive")
        self.assertRegex(fill, r"(?m)^        timeout-minutes: 5$")
        self.assertRegex(fill, r"(?m)^        continue-on-error: true$")
        last = step("Private archive (raw")
        (minutes,) = re.findall(r"(?m)^        timeout-minutes: (\d+)$", last)
        (job,) = re.findall(r"(?m)^    timeout-minutes: (\d+)$", WF)
        self.assertLess(int(minutes), int(job))              # a hung put ends as a failed step, not a cancelled job

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
            names = sorted({rel.split("/")[0] for rel in tree(run_root / "data")} - {"raw", "release-copy"})
            r = subprocess.run([sys.executable, "-", str(runner_temp / "archive-state"), "data", *names],
                               input=fill_script(), cwd=fresh, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = tree(fresh / "data")
            want = {rel: sha for rel, sha in tree(run_root / "data").items()
                    if not rel.startswith(("raw/", "release-copy/"))}
            self.assertEqual(got.pop("snapshot.json"), hashlib.sha256(b'{"from": "the Actions cache"}\n').hexdigest())
            self.assertEqual(got, {k: v for k, v in want.items() if k != "snapshot.json"})
            for p in ("ledger.json", "nms-closures.json", "upcoming-store.json", "ll2-ledger.json", "gnss/store.json"):
                self.assertIn(p, got)
            self.assertIn(f"{len(got)} files from the private archive", r.stdout)


# ---------- the fill step's own script, with stand-ins for gh and the archive ----------

# A stand-in for tools/tic_archive.py in the run folder: logs each call and the token it got, and restores a prepared
# folder as the newest `state` snapshot.
ARCHIVE_STUB = '''import os, shutil, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_ARCHIVE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(argv) + " token=" + os.environ.get("GH_TOKEN", "") + "\\n")
if os.environ.get("FAKE_ARCHIVE_FAIL"):
    sys.exit(1)
shutil.copytree(os.environ["FAKE_ARCHIVE_SNAPSHOT"], argv[argv.index("--dest") + 1], dirs_exist_ok=True)
'''
RELEASE_ALL = ("ascent-compare.json", "launch-ledger.json", "ll2-ledger.json", "nms-closures.json",
               "upcoming-store.json")
CACHE_FILES = ["gnss/days/2026-11-20.json", "gnss/store.json", "ledger.json", "snapshot.json"]


def fill_run(run_dir: Path, work: Path, archived: Path, release: list[str] | None, token: str = "archive-token",
             archive_fails: bool = False) -> tuple[subprocess.CompletedProcess, str, str]:
    """The fill step's script in run_dir. release: the assets `gh release view ledger` lists, None when the listing
    fails (a GitHub 5xx). Returns (bash's result, the archive calls, the gh calls)."""
    (run_dir / "tools").mkdir(parents=True, exist_ok=True)
    (run_dir / "data").mkdir(exist_ok=True)
    (run_dir / "tools" / "tic_archive.py").write_text(ARCHIVE_STUB, encoding="utf-8")
    bin_dir, log, gh_log = work / f"{run_dir.name}-bin", work / f"{run_dir.name}-archive.log", \
        work / f"{run_dir.name}-gh.log"
    head = f'echo "$*" >> "{gh_log.as_posix()}"\n'
    if release is None:
        stub(bin_dir, "gh", head + 'echo "HTTP 502: Bad Gateway" >&2\nexit 1\n')
    else:
        stub(bin_dir, "gh", head + "".join(f"echo {n}\n" for n in release))
    temp = work / f"{run_dir.name}-runner-temp"
    temp.mkdir(exist_ok=True)
    env = {"GH_TOKEN": "run-token", "ARCHIVE_TOKEN": token, "CACHED": "", "RUNNER_TEMP": temp.as_posix(),
           "FAKE_ARCHIVE_LOG": str(log), "FAKE_ARCHIVE_SNAPSHOT": str(archived),
           "FAKE_ARCHIVE_FAIL": "1" if archive_fails else ""}
    r = run_step_shell(step("Fill gaps in the state from the private archive"), run_dir, env, bin_dir)
    read = log.read_text(encoding="utf-8") if log.exists() else ""
    return r, read, gh_log.read_text(encoding="utf-8") if gh_log.exists() else ""


@unittest.skipIf(BASH is None, "needs bash (Git's bash on Windows)")
class TestFillStepShell(unittest.TestCase):
    """Which archived files the step may copy into data/, case by case. The archive's newest `state` can be older
    than release `ledger`, so a store the release holds is filled only when the release was listed and lacks it."""

    ARCHIVED = (*CACHE_FILES, "upcoming-store.json", "ll2-ledger.json", "nms-closures.json", "ascent-compare.json",
                "launches.json")

    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="launch-fill-"))
        self.addCleanup(shutil.rmtree, self.td, True)
        self.archived = self.td / "archived"
        for rel in self.ARCHIVED:
            (self.archived / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.archived / rel).write_text('{"from": "the archive"}\n', encoding="utf-8")
        self.run_dir = self.td / "run"

    def cache_hit(self):
        for rel in ("snapshot.json", "ledger.json", "gnss/store.json"):
            p = self.run_dir / "data" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"from": "the Actions cache"}\n', encoding="utf-8")

    def fill(self, release, **kw):
        r, read, gh = fill_run(self.run_dir, self.td, self.archived, release, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = self.run_dir / "data"
        filled = sorted(rel for rel in tree(data) if "the archive" in (data / rel).read_text(encoding="utf-8"))
        return filled, read, gh, r.stdout

    def test_cache_and_release_hold_it_all_so_the_archive_is_not_read(self):
        self.cache_hit()
        filled, read, gh, out = self.fill(list(RELEASE_ALL))
        self.assertEqual((filled, read), ([], ""))
        self.assertIn("the archive is not read", out)
        self.assertEqual(gh.split(), ["release", "view", "ledger", "--json", "assets", "--jq", ".assets[].name"])

    def test_cache_miss_fills_only_the_cache_paths_while_the_release_holds_its_stores(self):
        filled, read, _, _ = self.fill(list(RELEASE_ALL))
        self.assertEqual(filled, CACHE_FILES)            # not the Ascent stores, the NMS ledger or anything else
        self.assertIn("restore --program launch --lane state", read)
        self.assertIn("token=archive-token", read)

    def test_release_unreadable_fills_none_of_its_stores(self):
        # A failed listing is not "the release lacks them": collect's guard must still see no local copy.
        self.cache_hit()
        filled, read, _, out = self.fill(None)
        self.assertEqual((filled, read), ([], ""))
        self.assertIn("::warning::release ledger could not be listed", out)

    def test_release_unreadable_and_cache_miss_fills_only_the_cache_paths(self):
        filled, _, _, _ = self.fill(None)
        self.assertEqual(filled, CACHE_FILES)

    def test_a_store_the_release_lacks_is_filled(self):
        self.cache_hit()
        filled, _, _, _ = self.fill([n for n in RELEASE_ALL if n != "upcoming-store.json"])
        self.assertEqual(filled, ["upcoming-store.json"])

    def test_what_data_holds_stays(self):
        (self.run_dir / "data").mkdir(parents=True)
        (self.run_dir / "data" / "snapshot.json").write_text('{"from": "the Actions cache"}\n', encoding="utf-8")
        filled, _, _, _ = self.fill(list(RELEASE_ALL))
        self.assertEqual(filled, [p for p in CACHE_FILES if p != "snapshot.json"])
        self.assertIn("the Actions cache", (self.run_dir / "data" / "snapshot.json").read_text(encoding="utf-8"))

    def test_no_token_or_a_failed_restore_never_fails_the_step(self):
        filled, read, _, out = self.fill(list(RELEASE_ALL), token="")
        self.assertEqual((filled, read), ([], ""))
        self.assertIn("TIC_ARCHIVE_TOKEN is not set", out)
        filled, read, _, out = self.fill(list(RELEASE_ALL), archive_fails=True)
        self.assertEqual(filled, [])
        self.assertIn("could not be read", out)


@unittest.skipIf(BASH is None, "needs bash (Git's bash on Windows)")
class TestArchiveOlderThanRelease(unittest.TestCase):
    """The archive's newest `state` is older than release `ledger` (the run that uploaded the release had its
    archive step fail). The fill and collect together never put the older copy over a newer release record: with
    the release unreadable the run stops before it writes a store, and with it readable the newer record wins."""

    MARK = {"at": "2026-11-27T05:00:00Z", "source": "ll2", "fields": {"name": ["older", "newer than the archive"]}}
    LL2_MARK = {"at": "2026-11-27T05:00:00Z", "id": "release-only", "fields": {"net": ["older", "newer"]}}

    @classmethod
    def setUpClass(cls):
        cls.base = RunTree.make()
        cls.td = Path(tempfile.mkdtemp(prefix="launch-older-"))
        cls.archived = cls.td / "archived"          # the state as an earlier run left it
        shutil.copytree(cls.base / "data", cls.archived, ignore=shutil.ignore_patterns("raw", "release-copy"))
        # The archived store holds one scheduled launch; the release holds a later change to it and one launch more.
        old = json.loads((cls.base / "data" / "upcoming-store.json").read_text(encoding="utf-8"))
        schedule.ingest(old, "ll2", [schedule.ll2_row(rec(7, "2026-12-01T00:00:00Z"))], "2026-11-27T01:00:00Z",
                        link_key="ll2_url")
        (cls.archived / "upcoming-store.json").write_text(json.dumps(old), encoding="utf-8")
        up = json.loads(json.dumps(old))
        schedule.ingest(up, "ll2", [schedule.ll2_row(rec(8, "2026-12-02T00:00:00Z"))], "2026-11-27T04:00:00Z",
                        link_key="ll2_url")
        up["records"][0]["changes"].append(cls.MARK)
        ll2 = json.loads((cls.base / "data" / "ll2-ledger.json").read_text(encoding="utf-8"))
        ll2["changes"].append(cls.LL2_MARK)
        d = cls.base / "data"
        cls.release = {"upcoming-store.json": json.dumps(up).encode(), "ll2-ledger.json": json.dumps(ll2).encode(),
                       "launch-ledger.json": (d / "ledger.json").read_bytes(),
                       "nms-closures.json": (d / "nms-closures.json").read_bytes()}
        if (d / "ascent-compare.json").exists():     # written only when the run read Orbit's upcoming lane
            cls.release["ascent-compare.json"] = (d / "ascent-compare.json").read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def run_case(self, name: str, listed, release_up: bool, lost: tuple[str, ...] = ()):
        """A new run (no Actions cache) after the fill step. listed: what the release listing gives (None: it
        fails). release_up: collect's reads of release `ledger` answer, or fail with a 502. lost: assets gone."""
        root = self.td / name
        for top in ("doctrine", "site_src", "history"):
            shutil.copytree(self.base / top, root / top)
        r, _, _ = fill_run(root, self.td, self.archived, listed)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        def net(url: str, timeout: int = 0) -> bytes:
            if url.startswith(ll2ledger.RELEASE):
                if not release_up:
                    raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
                asset = url[len(ll2ledger.RELEASE):]
                if asset in self.release and asset not in lost:
                    return self.release[asset]
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return network(url, timeout)
        return root, net

    def assert_stops_without_writing_a_store(self, root, net):
        for f in ("upcoming-store.json", "ll2-ledger.json", "nms-closures.json"):
            self.assertFalse((root / "data" / f).exists(), f"{f} filled from the older archive")
        with self.assertRaisesRegex(RuntimeError, "not writing a smaller store"):
            cli.collect(root, getter=net)
        for f in ("upcoming-store.json", "ll2-ledger.json"):
            self.assertFalse((root / "data" / f).exists(), f"{f} written: the next step would upload it over the release")

    def test_release_listed_then_unreadable_stops_the_run(self):
        self.assert_stops_without_writing_a_store(*self.run_case("listed-then-502", list(RELEASE_ALL), False))

    def test_release_listing_fails_stops_the_run(self):
        self.assert_stops_without_writing_a_store(*self.run_case("listing-502", None, False))

    def test_release_readable_keeps_every_newer_record_over_an_older_local_copy(self):
        root, net = self.run_case("readable", list(RELEASE_ALL), True)
        for f in ("upcoming-store.json", "ll2-ledger.json"):           # an older local copy as well
            shutil.copyfile(self.archived / f, root / "data" / f)
        cli.collect(root, getter=net)
        got = {r["id"]: r for r in json.loads((root / "data" / "upcoming-store.json").read_text(encoding="utf-8"))
               ["records"]}
        rel = json.loads(self.release["upcoming-store.json"])
        for r in rel["records"]:
            self.assertIn(r["id"], got)
            for c in r["changes"]:
                self.assertIn(c, got[r["id"]]["changes"])
        self.assertIn(self.MARK, got[rel["records"][0]["id"]]["changes"])
        led = json.loads((root / "data" / "ll2-ledger.json").read_text(encoding="utf-8"))
        self.assertIn(self.LL2_MARK, led["changes"])
        self.assertLessEqual({r["id"] for r in json.loads(self.release["ll2-ledger.json"])["launches"]},
                             {r["id"] for r in led["launches"]})

    def test_a_store_the_release_lost_comes_back_from_the_archive(self):
        root, net = self.run_case("lost", [n for n in RELEASE_ALL if n != "upcoming-store.json"], True,
                                  lost=("upcoming-store.json",))
        self.assertEqual((root / "data" / "upcoming-store.json").read_bytes(),
                         (self.archived / "upcoming-store.json").read_bytes())
        self.assertFalse((root / "data" / "ll2-ledger.json").exists())   # the release still holds that one
        cli.collect(root, getter=net)
        got = {r["id"] for r in json.loads((root / "data" / "upcoming-store.json").read_text(encoding="utf-8"))
               ["records"]}
        archived = json.loads((self.archived / "upcoming-store.json").read_text(encoding="utf-8"))
        self.assertLessEqual({r["id"] for r in archived["records"]}, got)


# ---------- the deploy step's output gates the site lane ----------

@unittest.skipIf(BASH is None, "needs bash (Git's bash on Windows)")
class TestDeployedOutput(unittest.TestCase):
    def deploy(self, token: str, wrangler_ok: bool) -> tuple[int, str]:
        td = Path(tempfile.mkdtemp(prefix="launch-deploy-"))
        self.addCleanup(shutil.rmtree, td, True)
        (td / "run").mkdir()
        stub(td / "bin", "npx", "exit 0\n" if wrangler_ok else "exit 1\n")
        stub(td / "bin", "sleep", "exit 0\n")
        out = td / "github-output"
        out.write_text("", encoding="utf-8")
        env = {"CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": "account" if token else "",
               "GITHUB_OUTPUT": out.as_posix(), "GITHUB_SHA": "0" * 40}
        r = run_step_shell(STEPS["Deploy site/ to Cloudflare Pages"], td / "run", env, td / "bin")
        return r.returncode, out.read_text(encoding="utf-8")

    def test_deployed_only_after_wrangler_succeeded(self):
        self.assertEqual(self.deploy("", True), (0, ""))                # no secrets: skipped, and the step succeeds
        self.assertEqual(self.deploy("token", True), (0, "deployed=true\n"))
        self.assertEqual(self.deploy("token", False), (1, ""))


# ---------- the raw lane ----------

class TestRawRepliesKeepNoFetchTime(unittest.TestCase):
    """A gzipped reply holds no fetch time, so a reply that has not changed is the same file in every run and the
    raw lane's put (deduped by sha256) uploads it once."""

    def test_the_same_reply_is_the_same_bytes_in_every_run(self):
        body = json.dumps({"launches": list(range(500))}).encode()
        got = []
        with tempfile.TemporaryDirectory() as td:
            for run, t in (("run1", 1_795_000_000.0), ("run2", 1_795_086_400.0)):
                with mock.patch("time.time", return_value=t):
                    fetch.fetch("orbit-ledger", "https://example.invalid/ledger.json", Path(td) / run, "json",
                                getter=lambda url, timeout=0: body, gz=True)
                (f,) = (Path(td) / run / "orbit-ledger").iterdir()
                got.append(f.read_bytes())
        self.assertEqual(got[0], got[1])
        self.assertEqual(gzip.decompress(got[0]), body)


if __name__ == "__main__":
    unittest.main()
