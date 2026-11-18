"""The check that nothing private reaches Launch's site or its public repository.

Two lists of rules:

  public   rules that name nothing private, so they can sit in this file: an email address, a local path (a
           drive letter or a mounted drive followed by Users or Projects), and a few words matched by their
           SHA-256 (WORD_SHA256) so that the words themselves are not written here. These run everywhere,
           GitHub Actions included.
  private  history/source/terms.json, git-ignored, on the machine that holds the source map's export only (see
           history.load_terms). When the file is there its rules are added: "check", regular expressions, and
           "check_pair_sha256", SHA-256 of two-word phrases (lower case, one space). Its rules are reported by
           number, never by what they match.

scan() reads every text file in site/ and every tracked file. Copies of shared files (the house bar and the time
module from the hub, and the doctrine kit) are reported apart and do not fail: a hit there is fixed at its
source and copied in again. The vendored map library is not read.

Nothing is printed but file names, rule names and counts.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMS_FILE = ROOT / "history" / "source" / "terms.json"
TEXT = {".py", ".js", ".mjs", ".css", ".html", ".htm", ".json", ".geojson", ".md", ".txt", ".yml", ".yaml", ".csv",
        ".toml", ".cfg", ".ini", ".svg", ".xml", ".kml", ""}
SKIP = ("site_src/vendor/", "site/vendor/")
SHARED = ("doctrine/kit/", "site_src/tic-nav.", "site_src/tic-time.", "site_src/tic-related.", "site/tic-nav.",
          "site/tic-time.", "site/tic-related.")
# Lower-case words, by SHA-256: a person's name in its usual forms. Words are split at anything that is not a
# letter and at a lower-to-upper change ("chartById" is chart, By, Id), so a key or an identifier counts too.
WORD_SHA256 = frozenset({
    "e1608f75c5d7813f3d4031cb30bfb786507d98137538ff8e128a6ff74e84e643",
    "044f4b3501cd8e8131d40c057893f4fdff66bf4032ecae159e0c892a28cf6c8e",
    "d38681074467c0bc147b17a9a12b9efa8cc10bcf545f5b0bccccf5a93c4a2b79",
    "1e79f6794931ef59a7825ea40e5b00346d48e7b6a9ada0904a3b9738b2baca92",
})
PUBLIC_RULES = (
    ("an email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("a local path", re.compile(r"(?i)(?<![A-Za-z])[A-Z]:[\\/]+(?:Users|Projects)\b|(?<![\w.])/[a-z]/(?:Users|Projects)\b")),
)
_WORD = re.compile(r"[^\W\d_]+")
_LETTER = re.compile(r"[^\W\d_]")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def private_terms(path: Path = TERMS_FILE) -> dict | None:
    """The private rules, or None where the file is not here (GitHub Actions, a fresh clone)."""
    if not Path(path).is_file():
        return None
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"rules": [(f"private term {i}", re.compile(rx)) for i, rx in enumerate(doc.get("check") or [], 1)],
            "pairs": frozenset(doc.get("check_pair_sha256") or [])}


def words(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text):
        out += [p.lower() for p in _CAMEL.split(w) if p]
    return out


def hits(text: str, private: dict | None = None, word_sha=WORD_SHA256) -> dict[str, int]:
    """{rule: count} for one text. The data files repeat the same strings thousands of times, so the rules run
    over each distinct piece between double quotes once (pieces with no letter cannot match any rule), and a
    rule that matches is counted exactly, piece by piece, times how often the piece occurs. A match would be
    missed only if it ran across a double quote; every rule is a word or a short phrase."""
    found: dict[str, int] = {}
    pieces = Counter(x for x in text.split('"') if _LETTER.search(x))
    joined = '"\n"'.join(pieces)
    for name, rx in PUBLIC_RULES + tuple((private or {}).get("rules") or ()):
        if rx.search(joined):
            n = sum(len(rx.findall(p)) * c for p, c in pieces.items())
            if n:
                found[name] = found.get(name, 0) + n
    pairs = (private or {}).get("pairs")
    wc: Counter = Counter()
    pc: Counter = Counter()
    for piece, c in pieces.items():
        ws = words(piece)
        for w in ws:
            wc[w] += c
        if pairs:
            for pr in zip(ws, ws[1:]):
                pc[pr] += c
    n = sum(c for w, c in wc.items() if sha(w) in word_sha)
    if n:
        found["a listed name"] = n
    if pairs:
        n = sum(c for pr, c in pc.items() if sha(pr[0] + " " + pr[1]) in pairs)
        if n:
            found["a listed person"] = n
    return found


def tracked_files(root: Path = ROOT) -> list[str] | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def site_files(root: Path = ROOT) -> list[str]:
    site = root / "site"
    return sorted(p.relative_to(root).as_posix() for p in site.rglob("*") if p.is_file()) if site.is_dir() else []


def scan(paths: list[str], root: Path = ROOT, private: dict | None = None) -> tuple[list[tuple], list[tuple]]:
    """([(path, rule, count)] that fail, [(path, rule, count)] in shared copies, reported only)."""
    fail, shared = [], []
    for rel in paths:
        if rel.startswith(SKIP) or Path(rel).suffix.lower() not in TEXT:
            continue
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for rule, n in hits(text, private).items():
            (shared if rel.startswith(SHARED) else fail).append((rel, rule, n))
    return fail, shared


def problems(root: Path = ROOT, include_tracked: bool = True, terms: Path = TERMS_FILE) -> tuple[list[str], list[str]]:
    """(errors, notes) for launch.py check and build: every listed term in site/ and, when git is here, in every
    tracked file."""
    private = private_terms(terms)
    paths = site_files(root)
    notes = [] if private else ["privacy check: public rules only (history/source/terms.json is not here)"]
    if include_tracked:
        t = tracked_files(root)
        if t is None:
            notes.append("privacy check: git is not available, so tracked files were not read")
        else:
            paths = sorted(set(paths) | set(t))
    fail, shared = scan(paths, root, private)
    errs = [f"{rel}: {n} x {rule}" for rel, rule, n in fail]
    notes += [f"shared copy, fix at its source: {rel}: {n} x {rule}" for rel, rule, n in shared]
    return errs, notes
