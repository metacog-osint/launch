"""Joey0609/notams: an open database of the NOTAMs that closed launch drop zones, mostly China's, Dec 2020 onward.

Source: github.com/Joey0609/notams (MIT), pinned at SHA. One part is read: data/notam_db/<YYYY-MM>.json, one file a
month, each a set of columns (CODE, TIME, PLATID, RAWMESSAGE, ALTITUDE, GEOMETRY, classify) with NUM rows, plus
CLASSIFY, the project's own grouping of notices that overlap in time. RAWMESSAGE is the NOTAM as the FAA's NOTAM
search returned it (header, Q-line, items A-G), with two lines the project adds (CREATED, SOURCE); GEOMETRY is the
project's reading of the area ("PATH|M=N..E..|L=...|Z" or "CIRCLE|C=N..E..|R=200KM"). data/archiveMatch/ holds the
project's live comparison of the notices in force with its archive (it changes with every run) and is not read.

The database is mostly launch notices but not only (a 12-day general-aviation ban, a summer-long prohibited area),
so `launch_related` keeps a notice only on explicit rules. `fetch` copies the month files at the pinned commit into
a git-ignored folder; `build` writes history/joey.json (committed): number, FIRs, Q-code, window, areas, the E) text.
The SOURCE line is never kept (public.SOURCE_LINE).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import notam, public

REPO = "Joey0609/notams"
SHA = "8c4b7c8d9799fd295ef3e5864189764d320f0ef0"  # pushed 16 Nov 2026 02:47 UTC
LICENCE = "MIT"
ATTRIBUTION = ("Joey0609/notams by Joey0609 (github.com/Joey0609/notams), MIT License; read by Launch, which keeps "
               "its launch-related NOTAMs and joins them to GCAT.")
DB = "data/notam_db/"
UA = "tic-launch (+https://launch.theintelligence.company)"
MONTH = re.compile(r"^data/notam_db/\d{4}-\d{2}\.json$")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def fetch(dest: Path, pause: float = 0.5) -> dict:
    """Copy every month file and the LICENSE at SHA into dest (git-ignored). Skips files already there."""
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{SHA}?recursive=1"))
    paths = ["LICENSE"] + sorted(t["path"] for t in tree["tree"] if t["type"] == "blob" and MONTH.match(t["path"]))
    got = 0
    for p in paths:
        out = dest / p
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_get(f"https://raw.githubusercontent.com/{REPO}/{SHA}/{p}"))
        got += 1
        time.sleep(pause)
    return {"files": len(paths), "fetched": got}


# ---- which notices are kept ----------------------------------------------------------------------------------

# A Chinese FIR's own danger, restricted or prohibited area from the surface to unlimited, open for a short time:
# how China's launch closures read when their text names no activity ("A TEMPORARY DANGER AREA ESTABLISHED BOUNDED
# BY ... VERTICAL LIMITS:SFC-UNL").
CN_AREA_CODES = {"QRDCA", "QRTCA", "QRPCA"}
CN_MAX_HOURS = 6          # the whole window (B to C), or ...
CN_MAX_PERIOD_HOURS = 2   # ... every period of a D) schedule, within CN_MAX_DAYS
CN_MAX_DAYS = 4
MAX_DAYS = 62             # longer than this is not one launch's notice (a summer-long prohibited area, a typo to 2028)
NOT_LAUNCH = re.compile(r"GENERAL AVIATION|AEROBATIC")
PERIOD = re.compile(r"(?<!\d)(\d{2})(\d{2})\s*-\s*(\d{2})(\d{2})(?!\d)")


def _hours(a: str | None, b: str | None) -> float | None:
    f = "%Y-%m-%dT%H:%M:%SZ"
    try:
        return (datetime.strptime(b, f) - datetime.strptime(a, f)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _periods(schedule: str | None) -> list[float]:
    """Hours of each HHMM-HHMM period in a D) schedule (one past midnight wraps)."""
    out = []
    for m in PERIOD.finditer(schedule or ""):
        a = int(m.group(1)) * 60 + int(m.group(2))
        b = int(m.group(3)) * 60 + int(m.group(4))
        if max(a, b) <= 24 * 60:
            out.append(((b - a) % (24 * 60)) / 60)
    return out


def launch_related(n: dict) -> str | None:
    """Why a parsed notice is kept, or None. In order:
      - not kept: a cancellation; a window over MAX_DAYS; text naming general aviation or aerobatics;
      - "words": notam.LAUNCH_WORDS in the E) text (aerospace, rocket, space debris, reentry, stage, missile...)
        or a Q-code of subject WM (missile, gun or rocket firing): notam.parse's own launch_related;
      - "cn-area": a Chinese FIR (Q-line or A), notam.FIR_STATE CN), Q-code in CN_AREA_CODES, upper limit
        unlimited, and a window of at most CN_MAX_HOURS, or one of at most CN_MAX_DAYS whose D) periods are each at
        most CN_MAX_PERIOD_HOURS."""
    if n.get("type") == "cancel":
        return None
    span = _hours(n.get("start"), n.get("end"))
    if span is not None and span > MAX_DAYS * 24:
        return None
    if NOT_LAUNCH.search(n.get("e_text") or ""):
        return None
    if n.get("launch_related"):
        return "words"
    q = n.get("q") or {}
    firs = [f for f in [q.get("fir")] + list(n.get("locations") or []) if f]
    cn = any(f == "ZXXX" or notam.state_of_fir(f) == "CN" for f in firs)
    unl = "UNL" in (n.get("upper") or "").upper() or q.get("upper_fl") == 999
    if not (cn and q.get("code") in CN_AREA_CODES and unl and span is not None):
        return None
    if span <= CN_MAX_HOURS:
        return "cn-area"
    per = _periods(n.get("schedule"))
    if per and span <= CN_MAX_DAYS * 24 and max(per) <= CN_MAX_PERIOD_HOURS:
        return "cn-area"
    return None


# ---- the month files -----------------------------------------------------------------------------------------

STRIP = re.compile(r"^\s*(?:SOURCE|CREATED)\s*:.*$", re.M | re.I)
CREATED = re.compile(r"^\s*CREATED\s*:\s*(\d{2}) ([A-Z]{3}) (\d{4}) (\d{2}):(\d{2})", re.M | re.I)
GEO_PT = re.compile(r"([NS])(\d{2})(\d{2})(\d{2})([EW])(\d{3})(\d{2})(\d{2})")


def _pt(m) -> tuple[float, float]:
    lat = (int(m.group(2)) + int(m.group(3)) / 60 + int(m.group(4)) / 3600) * (-1 if m.group(1) == "S" else 1)
    lon = (int(m.group(6)) + int(m.group(7)) / 60 + int(m.group(8)) / 3600) * (-1 if m.group(5) == "W" else 1)
    return lat, lon


def geometry_ring(g: str | None) -> list[list[float]] | None:
    """The project's own reading of the area as a [lon, lat] ring; used only when Launch's parser finds no shape."""
    if not g:
        return None
    if g.startswith("CIRCLE"):
        c = GEO_PT.search(g)
        r = re.search(r"R=(\d+(?:\.\d+)?)(KM|NM)", g)
        if not (c and r):
            return None
        lat, lon = _pt(c)
        return notam.circle_ring(lat, lon, float(r.group(1)) / (notam.NM_KM if r.group(2) == "KM" else 1))
    pts = []
    for m in GEO_PT.finditer(g):
        lat, lon = _pt(m)
        pts.append([round(lon, 5), round(lat, 5)])
    if len(pts) < 3:
        return None
    return pts + [pts[0]] if pts[0] != pts[-1] else pts


def rows(doc: dict) -> list[dict]:
    """A month file's columns as one dict a row."""
    n = int(doc.get("NUM") or 0)
    cols = [k for k, v in doc.items() if isinstance(v, list)]
    return [{k: (doc[k][i] if i < len(doc[k]) else None) for k in cols} for i in range(n)]


def _created(raw: str) -> str | None:
    c = CREATED.search(raw)
    if not c:
        return None
    try:
        d = datetime.strptime(f"{c.group(1)} {c.group(2).title()} {c.group(3)} {c.group(4)}:{c.group(5)}",
                              "%d %b %Y %H:%M")
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def notice(row: dict) -> dict | None:
    """One row -> Launch's record of the notice, or None when it is not kept (see launch_related)."""
    raw = html.unescape(row.get("RAWMESSAGE") or "")
    created = _created(raw)
    raw = STRIP.sub("", raw).strip()
    try:
        n = notam.parse(raw)
    except notam.ParseError:
        return None
    why = launch_related(n)
    if not why:
        return None
    rings = [s["ring"] for s in n["shapes"] if s["kind"] in ("polygon", "circle")
             and not (s.get("derived") or "").startswith("Q-line")]
    basis = "text" if rings else None
    if not rings:
        g = geometry_ring(row.get("GEOMETRY"))
        if g:
            rings, basis = [g], "geometry"
    q = n.get("q") or {}
    code = str(row.get("CODE") or n.get("number") or "")
    part = code.split("_", 1)[1] if "_" in code else None   # "A3806/24_AREA1": one of a notice's areas
    text = "\n".join(ln for ln in (n.get("e_text") or "").splitlines() if not public.SOURCE_LINE.search(ln)).strip()
    return {"number": n.get("number") or code.split("_")[0], "part": part, "type": n.get("type"),
            "fir": q.get("fir"), "locations": n.get("locations") or [], "q_code": q.get("code"),
            "start": n.get("start"), "end": n.get("end"), "schedule": n.get("schedule"),
            "lower": n.get("lower"), "upper": (n.get("upper") or "").split("\n")[0].strip() or None,
            "issuing_state": n.get("issuing_state"), "named_states": n.get("named_states") or [],
            "kept": why, "rings": [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings], "ring_basis": basis,
            "created": created, "group": row.get("classify"), "text": text}


def build(src: Path) -> dict:
    """history/joey.json: every kept notice, once per number, part and FIRs (the latest month file's copy)."""
    seen: dict[tuple, dict] = {}
    counts = {"rows": 0, "kept": 0, "words": 0, "cn-area": 0, "duplicates": 0}
    for p in sorted((src / DB).glob("*.json")):
        if not re.match(r"\d{4}-\d{2}\.json$", p.name):
            continue
        for row in rows(json.loads(p.read_text(encoding="utf-8"))):
            counts["rows"] += 1
            n = notice(row)
            if n is None:
                continue
            key = (n["number"], n["part"], " ".join(sorted({n["fir"] or "", *n["locations"]})))
            if key in seen:
                counts["duplicates"] += 1
                counts[seen[key]["kept"]] -= 1
                counts["kept"] -= 1
            counts["kept"] += 1
            counts[n["kept"]] += 1
            seen[key] = n
    notices = sorted(seen.values(), key=lambda n: (n["start"] or "", n["number"], n["part"] or ""))
    for n in notices:
        firs = "-".join(sorted({n["fir"] or "", *n["locations"]} - {""}))
        n["id"] = f"joey:{n['number'].replace('/', '-')}{'-' + n['part'] if n['part'] else ''}-{firs}"
    return {"source": f"github.com/{REPO}", "commit": SHA, "licence": LICENCE, "attribution": ATTRIBUTION,
            "rule": " ".join(launch_related.__doc__.split()), "counts": counts, "notices": notices}


def summary(doc: dict) -> dict:
    N = doc["notices"]
    years: dict[str, int] = {}
    for n in N:
        y = (n["start"] or "?")[:4]
        years[y] = years.get(y, 0) + 1
    return {**doc["counts"], "notices": len(N), "with_ring": sum(1 for n in N if n["rings"]),
            "ring_from_geometry": sum(1 for n in N if n["ring_basis"] == "geometry"),
            "issued_cn": sum(1 for n in N if n["issuing_state"] == "CN"), "by_year": dict(sorted(years.items()))}
