"""FAA NOTAMs (NMS-API) through Cordon: the `nms` live lane.

Cordon is the suite's one NMS reader (decided 18 Nov 2026): it holds the only keys, makes the one bulk pull a day the
FAA allows and the deltas, and publishes subset files of the active set at
https://cordon.theintelligence.company/data/notams/ (index.json; Cordon's cordon/nms.py). Launch reads its
`launch-areas` subset (restricted, danger and prohibited areas, warnings and "other" notices reaching FL100, not
permanent, open at most 62 days) and applies its own rules here (keep()); launch/gnss.py reads the `gnss` subset.
Launch makes no FAA request and holds no NMS keys. From 16 to 19 Nov 2026 Launch read NMS itself; that client
moved to Cordon.

Nothing is lost (decided 18 Nov 2026: storage keeps everything; live views may filter): the live state drops a closure
a day after it ends, but every closure notice Launch ever kept stays in the ledger (ledger(): data/nms-closures.json,
published at LEDGER_URL), each version once. Cordon keeps every raw NMS feature for good (its release archive).

The FAA's terms allow redistribution but not calling it FAA data; the FAQ asks that NMS not be presented as the
authoritative source for non-US NOTAMs. SOURCE_NOTE says both on the page.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import joey, notam, timing
from .gnss import EMAIL, EMAIL_NOTE

CORDON_NOTAMS = "https://cordon.theintelligence.company/data/notams/"   # Cordon's index.json and subsets
SUBSET = "launch-areas"
SOURCE_NOTE = ("NOTAMs read through the FAA NOTAM Management Service API (NMS-API). Not FAA data as published "
               "by Launch, and not the authoritative source for NOTAMs issued outside the United States.")

# Launch's rules for keeping a NOTAM (after joey.launch_related, the rules used for Joey0609/notams):
NOT_LAUNCH = re.compile(r"MODEL ROCKET|GENERAL AVIATION|AEROBATIC|LASER|FIREWORK|BALLOON|GUN F|MORTAR|FLARE|"
                        r"PARACHUT|ARTILLERY|SMALL ARMS|\bUAS\b|\bUAV\b|DRONE|DETONAT|DISPLAY|AERODROME CLOSED")
AREA_SUBJECTS = ("R", "W")      # Q-code subject first letter: restricted/danger/prohibited areas, warnings
WORD_SUBJECTS = ("R", "W", "X")  # ... and "other": a notice with launch words but a Q-code of another subject
                                 # (aerodrome lighting, procedures) is not a closure
MIN_UPPER_FL = 100               # a launch closure reaches at least FL100 (Q-line upper limit)
# notam.LAUNCH_WORDS, with "STAGE" only where it names a rocket's stage (aerodrome works have stages too).
WORDS = re.compile(notam.LAUNCH_WORDS.pattern.replace(
    "|STAGE|", r"|\b(?:ROCKET|BOOSTER|FIRST|SECOND|THIRD|UPPER|1ST|2ND|3RD) STAGES?\b|\bSTAGES? (?:FALL|IMPACT|DEBRIS|DROP|SPLASH)|"))
assert WORDS.pattern != notam.LAUNCH_WORDS.pattern, "STAGE was not narrowed"
UNL_MAX_HOURS = joey.CN_MAX_HOURS
LEDGER_URL = "https://launch.theintelligence.company/data/nms-closures.json"
LEDGER_ABOUT = ("Every NMS closure notice Launch has kept (nms.keep), ended ones included, kept for good: one record "
                "per version (number, FIR, lastUpdated), with when Launch first and last saw it in Cordon's active "
                "set (first_seen, last_seen). Email addresses in the text are replaced by '" + EMAIL_NOTE + "'. The "
                "live areas are in snapshot.json; every raw NMS feature is in Cordon's archive "
                "(its release assets nms-archive-YYYY-MM; Cordon's notams index.json, field archive, links them).")
# Kept, and left off the live view: notices whose text says what they are, and it is not a space launch (decided 22
# Nov 2026, from the live list of that day). They stay in the ledger (storage keeps everything); they are not live
# areas and match no launch. First that applies, each with its reason; then, unless the text has SPACE words, the rest.
OFF_LIVE_ALWAYS = [
    ("amateur rocketry", re.compile(r"ROCKETRY|TRIPOLI|HIGH[- ]POWER ROCKET|AMATEUR ROCKET")),
    ("no longer in force", re.compile(r"NO LONGER IN FORCE|(?:WAS|HAS BEEN|IS) COMPLETED")),
    ("aerodrome notice", re.compile(r"AEROSPACE GROUND EQUIPMENT|QUIET HOURS")),
]
SPACE = re.compile(r"\bSPACE\b|\bSPACE ?(?:DEBRIS|LAUNCH|VEHICLE|CRAFT|OPS|OPERATIONS|FLIGHT|FLT)|SATELLITE|\bORBIT|"
                   r"LAUNCH VEHICLE|ROCKET LAUNCH|AEROSPACE (?:FLIGHT|ACT)|RE-?ENTRY|SPLASH ?DOWN|DEBRIS")
OFF_LIVE = [
    ("missile firing", re.compile(r"MISSILE")),
    ("airdrop or airlift", re.compile(r"AIR ?DROP|AIRLIFT|OFF-?LOAD|\bDZ\b|DROP ZONE")),
    ("military exercise", re.compile(r"\bMIL(?:ITARY)? (?:ACT|ACTIVITY|ACTIVITIES|EXER|EXERCISE|FLYING|TRAINING|OPS)\b|"
                                     r"\bEXER(?:CISE)?\b")),
]


def off_live(text: str | None) -> str | None:
    """Why a kept notice is left off the live view (OFF_LIVE_ALWAYS, then OFF_LIVE without SPACE words), or None."""
    t = (text or "").upper()
    for why, rx in OFF_LIVE_ALWAYS:
        if rx.search(t):
            return why
    if SPACE.search(t):
        return None
    for why, rx in OFF_LIVE:
        if rx.search(t):
            return why
    return None


RECUR_NM = 25                   # an area centred this close to a past launch closure area is "recurring"
RECUR_MAX_DAYS = 7


class Waiting(Exception):
    """No keys in the environment: the lane waits."""


# ---------- Cordon's files ----------

def features(j) -> list[dict]:
    """The GeoJSON features of a response, a classification file or a FeatureCollection."""
    if isinstance(j, list):
        return j
    g = j.get("data", {}).get("geojson") if isinstance(j.get("data"), dict) else None
    if g is None:
        g = j
    return g if isinstance(g, list) else g.get("features") or []


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


# ---------- one NOTAM ----------

def icao_text(f: dict) -> str | None:
    core = (f.get("properties") or {}).get("coreNOTAMData") or {}
    for t in core.get("notamTranslation") or []:
        if t.get("type") == "ICAO" and t.get("formattedText"):
            return t["formattedText"]
    return None


def past_areas(root: Path) -> list[tuple[float, float]]:
    """Centres of the closure areas in Launch's history (charted, NotamForChina, Joey0609/notams)."""
    out = []

    def add(ring):
        if ring and len(ring) >= 3:
            out.append(notam.centroid(ring))

    def read(name):
        p = root / "history" / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    for e in read("history.json").get("events") or []:
        for a in e.get("areas") or []:
            add(a.get("ring"))
    for la in read("nfc.json").get("launches") or []:
        for n in la.get("notices") or []:
            add(n.get("ring"))
    for n in read("joey.json").get("notices") or []:
        for r in n.get("rings") or []:
            add(r)
    return out


def _span_h(n: dict) -> float | None:
    return joey._hours(n.get("start"), n.get("end"))


HEIGHT = re.compile(r"^\s*(?:FL\s*(\d{2,3})|(\d+(?:\.\d+)?)\s*(FT|M)\b)")


def height_ft(s: str | None) -> float | None:
    """F) or G) text -> feet (UNL is infinite), or None when it does not read."""
    s = (s or "").upper()
    if s.startswith("UNL"):
        return float("inf")
    if s.startswith(("SFC", "GND")):
        return 0.0
    m = HEIGHT.match(s)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1)) * 100.0
    return float(m.group(2)) * (3.2808 if m.group(3) == "M" else 1)


def _surface(n: dict) -> bool:
    lo = height_ft(n.get("lower"))
    return lo == 0.0 if lo is not None else (n.get("q") or {}).get("lower_fl") == 0


def _unl(n: dict) -> bool:
    up = height_ft(n.get("upper"))
    unl = up == float("inf") if up is not None else (n.get("q") or {}).get("upper_fl") == 999
    return unl and _surface(n)


def keep(n: dict, rings: list, past: list[tuple[float, float]]) -> str | None:
    """Why a parsed NOTAM is kept, or None. Not kept: a cancellation, a permanent notice, a window over
    joey.MAX_DAYS, or text in NOT_LAUNCH (model rockets, gun, mortar and flare firing, lasers, fireworks,
    balloons, drones, general aviation, aerobatics). Kept, first that applies:
      (every rule: the G) upper limit, and the Q-line's when there is one, reaching at least MIN_UPPER_FL)
      words             WORDS (notam.LAUNCH_WORDS, "stage" narrowed) in the E) text, and a Q-code, if any, of an
                        area, a warning or "other" (a WM Q-code alone is not enough here: worldwide it is mostly
                        gun and mortar firing);
      cn-area           joey.launch_related's rule for China's SFC-UNL danger areas;
      unl-area          any state: a restricted, danger or prohibited area or a warning (Q-code R.. or W..) from
                        the surface to unlimited, open at most UNL_MAX_HOURS, or at most joey.CN_MAX_DAYS in
                        periods of at most joey.CN_MAX_PERIOD_HOURS (the "-UNL" search, everywhere);
      recurring-area    the same kind of area from the surface, open at most RECUR_MAX_DAYS, centred within RECUR_NM of a closure
                        area in Launch's history (charted, NotamForChina, Joey0609/notams)."""
    if n.get("type") == "cancel" or n.get("permanent"):
        return None
    span = _span_h(n)
    if span is None or span > joey.MAX_DAYS * 24 or NOT_LAUNCH.search(n.get("e_text") or ""):
        return None
    q = n.get("q") or {}
    code = q.get("code") or ""
    up = height_ft(n.get("upper"))
    if (up is not None and up < MIN_UPPER_FL * 100) or (q and q.get("upper_fl", 999) < MIN_UPPER_FL):
        return None
    if WORDS.search(n.get("e_text") or "") and (not code or code[1:2] in WORD_SUBJECTS):
        return "words"
    if joey.launch_related({**n, "launch_related": False}):
        return "cn-area"
    if code[1:2] not in AREA_SUBJECTS:
        return None
    if _unl(n):
        if span <= UNL_MAX_HOURS:
            return "unl-area"
        per = joey._periods(n.get("schedule"))
        if per and span <= joey.CN_MAX_DAYS * 24 and max(per) <= joey.CN_MAX_PERIOD_HOURS:
            return "unl-area"
    if span <= RECUR_MAX_DAYS * 24 and rings and past and _surface(n):
        for r in rings:
            la, lo = notam.centroid(r)
            if any(abs(la - pa) < 0.5 and notam.haversine_nm(la, lo, pa, po) <= RECUR_NM for pa, po in past):
                return "recurring-area"
    return None


def notice(f: dict, past: list[tuple[float, float]]) -> dict | None:
    """One NMS feature -> Launch's record of the notice, or None when it is not kept."""
    raw = icao_text(f)
    if not raw:
        return None
    try:
        n = notam.parse(raw)
    except notam.ParseError:
        return None
    rings = [s["ring"] for s in n["shapes"] if s["kind"] in ("polygon", "circle")
             and not (s.get("derived") or "").startswith("Q-line")]
    basis = "text" if rings else None
    why = keep(n, rings, past)
    if not why:
        return None
    if not rings:
        rings = [s["ring"] for s in n["shapes"] if s["kind"] == "circle"]
        basis = "Q-line circle (approximate)" if rings else None
    core = (f.get("properties") or {}).get("coreNOTAMData") or {}
    meta = core.get("notam") or {}
    q = n.get("q") or {}
    return {"id": meta.get("id"), "number": n.get("number") or meta.get("number"), "type": n.get("type"),
            "refers_to": n.get("refers_to"), "classification": meta.get("classification"),
            "fir": q.get("fir"), "locations": n.get("locations") or [], "q_code": q.get("code"),
            "start": n.get("start"), "end": n.get("end"), "schedule": n.get("schedule"),
            "lower": n.get("lower"), "upper": (n.get("upper") or "").split("\n")[0].strip() or None,
            "issuing_state": n.get("issuing_state"), "named_states": n.get("named_states") or [],
            "kept": why, "rings": [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings], "ring_basis": basis,
            "issued": meta.get("issued"), "last_updated": meta.get("lastUpdated"), "text": n.get("e_text") or "",
            "off_live": off_live(n.get("e_text"))}


# ---------- the store ----------

def _key(n: dict) -> str:
    return f"{n.get('number')}|{n.get('fir') or ''}"


def apply(store: dict, feats: list[dict], past, now: datetime, replace_all: bool = False) -> dict:
    """Bulk (replace_all) or delta features -> the kept notices, keyed by number and FIR. A replacing or
    cancelling NOTAM removes the one it refers to; a notice ended over a day ago is dropped."""
    out = {} if replace_all else dict(store)
    counts = {"features": len(feats), "kept_new": 0, "removed": 0}
    for f in feats:
        raw = icao_text(f)
        try:
            n = notam.parse(raw) if raw else None
        except notam.ParseError:
            n = None
        if n and n.get("refers_to"):
            ref = f"{n['refers_to']}|{(n.get('q') or {}).get('fir') or ''}"
            if out.pop(ref, None) is not None:
                counts["removed"] += 1
        k = notice(f, past)
        if k:
            out[_key(k)] = k
            counts["kept_new"] += 1
    cut = now - timedelta(days=1)
    for key in [k for k, v in out.items() if (_dt(v.get("end")) or now) < cut]:
        del out[key]
        counts["removed"] += 1
    counts["kept"] = len(out)
    return {"notices": out, "counts": counts}


def from_set(feats: list[dict], index: dict, past, now: datetime) -> dict:
    """Cordon's launch-areas subset (the active set at its last pull) -> the lane's state for the snapshot."""
    res = apply({}, feats, past, now, replace_all=True)
    notices = sorted(res["notices"].values(), key=lambda n: (n.get("start") or "", n.get("number") or ""))
    kinds: dict[str, int] = {}
    off: dict[str, int] = {}
    for n in notices:
        kinds[n["kept"]] = kinds.get(n["kept"], 0) + 1
        if n.get("off_live"):
            off[n["off_live"]] = off.get(n["off_live"], 0) + 1
    return {"env": index.get("env"), "mode": "cordon", "via": CORDON_NOTAMS, "bulk_at": index.get("bulk_at"),
            "pulled_to": index.get("pulled_to"), "cordon_status": index.get("lane_status"), "requests": 0,
            "counts": {**res["counts"], "kept_by_rule": kinds, "off_live": off}, "source_note": SOURCE_NOTE, "notices": notices}


def areas(state: dict, tfr_ids: set[str] | None = None, sites: dict | None = None) -> list[dict]:
    """Kept notices as areas for live.match. An FDC notice the tfr lane already holds is left to it. One whose text
    says it is not a launch carries `off_live` (its reason): live.match skips it and the page hides it until the
    viewer turns such notices on. With history/timing.json's sites, an area near a pad carries `expect`
    (timing.expect). `text` is for live.match and is not written to the snapshot's areas."""
    out = []
    for n in state.get("notices") or []:
        num = (n.get("number") or "")
        off = off_live(n.get("text"))   # read again: a lane carried from an earlier run has no off_live field
        if tfr_ids and n.get("classification") == "FDC" and any(num.endswith(t) for t in tfr_ids):
            continue
        if not (n.get("start") and n.get("end")):
            continue
        for i, ring in enumerate(n.get("rings") or []):
            out.append({"source": "faa-nms", "id": f"{num} {n.get('fir') or ''}".strip()
                        + (f" area {i + 1}" if len(n["rings"]) > 1 else ""),
                        "label": (n.get("text") or "").split("\n")[0][:120], "ring": ring, "kept": n["kept"],
                        "windows": [{"start": n["start"], "end": n["end"]}], "ring_basis": n.get("ring_basis"),
                        "expect": timing.expect(ring, n["start"], n["end"], sites or {}), "text": n.get("text") or ""}
                       | ({"off_live": off} if off else {}))
    return out


# ---------- the ledger: every closure notice ever kept ----------

def ledger_key(n: dict) -> str:
    """Number, FIR and lastUpdated: one record per version ("2026-11-19T17:59:00.000Z" and "...00Z" are one time)."""
    lu = (n.get("last_updated") or "").replace(".000Z", "Z")
    return f"{n.get('number')}|{n.get('fir') or ''}|{lu}"


def ledger(docs: list, fresh: list[dict], at: str) -> dict:
    """The union of earlier ledgers (the cache's, the published copy) and this run's kept notices."""
    out: dict[str, dict] = {}

    def add(e: dict) -> None:
        k = e.get("ledger_key") or ledger_key(e)
        old = out.get(k)
        if old:
            e = {**old, **e, "first_seen": min(old.get("first_seen") or at, e.get("first_seen") or at),
                 "last_seen": max(old.get("last_seen") or "", e.get("last_seen") or "")}
        out[k] = {**e, "ledger_key": k}

    for d in docs:
        for e in (d or {}).get("notices") or []:
            if isinstance(e, dict) and e.get("number"):
                add(e)
    for n in fresh:
        add({**n, "text": EMAIL.sub(EMAIL_NOTE, n.get("text") or ""), "first_seen": at, "last_seen": at})
    notices = sorted(out.values(), key=lambda e: (e.get("start") or "", e.get("number") or "", e["ledger_key"]))
    return {"program": "launch", "dataset": "nms-closures", "source": "FAA NMS-API via Cordon",
            "source_note": SOURCE_NOTE, "about": LEDGER_ABOUT, "generated_at": at, "n": len(notices),
            "notices": notices}
