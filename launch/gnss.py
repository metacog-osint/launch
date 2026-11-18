"""GPS/GNSS NOTAMs from the nms lane's pulls: a second subset of the same FAA NMS-API reads (no extra requests),
for Noisefloor (asked 17 Nov 2026, built 18 Nov 2026).

No launch filters. A NOTAM is kept, first that applies (`matched_by`):
  q-code   its Q-code subject is GA (GNSS airfield-specific operations) or GW (GNSS area-wide operations);
  text     its text names GNSS (WORDS) with a word about the signal (SIGNAL) within NEAR characters, once the
           phrases that name GNSS without saying anything about the signal are taken out (EQUIPMENT: "aircraft
           equipped with ... GPS", procedure names such as "RNAV (GPS) RWY 18", contingencies "in case of GNSS
           failure"). Measured on the staging bulk pull of 17 Nov 2026 (80,297 NOTAMs): 204 by Q-code; the words
           alone matched about 3,800, nearly all instrument procedures (Q-codes QPI.., QPD..) and "for aircraft
           equipped with suitable RNAV system with GPS";
  refers   a cancellation or replacement of a NOTAM kept here (so cancels and replaces are kept).
Each kept NOTAM keeps the NMS-API's own fields as given (`notam`), its ICAO text, its geometry, and Launch's
fields: why it was kept, the words, when Launch first and last saw it, and what cancelled or replaced it.
Email addresses in the text are removed (Launch's privacy check refuses them on the site); nothing else is.

State (data/gnss/store.json, kept in the Actions cache with the snapshot): every kept NOTAM seen in the last
KEEP_DAYS + 2 days, and a log of the lane's runs. Published (site/data/gnss-notams/, copied by `build`):
  active.json         the kept NOTAMs in the FAA's active set at the last pull (cancels and replaces included,
                      `in_force` says whether each is in force at that time);
  YYYY-MM-DD.json     one per UTC day, written once the day has ended: every kept NOTAM whose window overlaps the
                      day (to its end, or to the cancel that ended it), and the cancels and replaces issued that
                      day. Rewritten for REVISE_HOURS after the day ends when a late cancel changes it
                      (`revised_at`). Written for every day the lane ran, n=0 included, with the lane's runs that
                      day, so a day with no pull says so. KEEP_DAYS days are kept;
  index.json          the day files, with n and when each was written.
The FAA's terms allow redistribution but not calling it FAA data, and NMS is not the authoritative source for
NOTAMs issued outside the United States (nms.SOURCE_NOTE, in every file's header).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

RULE = "gnss-1.0"
KEEP_DAYS = 14
REVISE_HOURS = 48
NEAR = 60
PUBLISHED = "https://launch.theintelligence.company/data/gnss-notams/"
Q_SUBJECTS = ("GA", "GW")

WORDS = re.compile(r"\b(GPS|GNSS|GLONASS|GALILEO|BEIDOU|RAIM|WAAS|EGNOS|SBAS|GBAS|MSAS|GAGAN|SDCM|NAVSTAR|"
                   r"SATELLITE NAVIGATION)\b")
SIGNAL = re.compile(r"INTERFERENCE|JAMM(?:ING|ED|ER)|SPOOF(?:ING|ED)?|UNRELIABLE|UNRELIAB|UNAVBL|UNAVAILABLE|"
                    r"NOT AVBL|NOT AVAILABLE|NOT BE AVBL|NOT BE AVAILABLE|OUTAGE|DEGRAD\w*|\bTEST(?:ING|S)?\b|"
                    r"\bRFI\b|\bU/S\b|\bLOSS\b|DISRUPT\w*|UNUSABLE|INACCURA\w*|ANOMAL\w*|SUSPENDED")
EQUIPMENT = re.compile(
    r"(?:ACFT|AIRCRAFT)\s+EQUIPPED\s+WITH[^.]{0,80}?\b(?:GPS|GNSS)\b"
    r"|EXCEPT\s+FOR\s+(?:GNSS|GPS)\s+EQUIPPED"
    r"|\b(?:NON[- ])?(?:GNSS|GPS)[- ]EQUIPPED"
    r"|\b(?:RNAV|RNP|GLS)\s*-?\s*\d?\s*\((?:GPS|GNSS|RNP)[^)]*\)"
    r"|\((?:GPS|GNSS)\)"
    r"|\b(?:GPS|GNSS)\s+RWY\b"
    r"|\bGNSS\s+(?:MEA|MOCA)\b"
    r"|\b(?:GPS|GNSS)\s+(?:IS\s+)?REQUIRED\b"
    r"|\b(?:VOR|NDB|TACAN|DME)(?:/DME)?\s+OR\s+GPS(?:-[A-Z])?\b"
    r"|\bRNAV\s*-?\s*\d?\s+(?:\(?DME/DME\s+OR\s+)?GNSS\)?(?:\s+MIDS?|\s+RWY)?\b"
    r"|\bIN\s+(?:THE\s+)?(?:CASE|EVENT)\s+OF\b[^.]{0,80}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_NOTE = "[email address removed]"
QLINE = re.compile(r"Q\)\s*[A-Z]{4}/(Q[A-Z]{4})")
REFERS = re.compile(r"NOTAM[CR]\s+([A-Z]?\d{1,4}/\d{2})")
SELECTION = ("No launch filters. Kept, first that applies (matched_by): q-code, a Q-code subject GA or GW; text, a "
             "GNSS word (GPS, GNSS, GLONASS, Galileo, BeiDou, RAIM, WAAS, EGNOS, SBAS, GBAS, MSAS, GAGAN, SDCM, "
             "NAVSTAR, satellite navigation) within 60 characters of a word about the signal (interference, "
             "jamming, spoofing, unreliable, not available, outage, degraded, test, RFI, U/S, loss, disrupted, "
             "unusable, inaccurate, anomaly, suspended), after phrases such as 'aircraft equipped with ... GPS', "
             "procedure names like 'RNAV (GPS) RWY 18' and 'in case of GNSS failure' are taken out; refers, a "
             "cancellation or replacement of a NOTAM kept here.")
WINDOW_RULE = ("A NOTAM is in a day's file when its window (effectiveStart to effectiveEnd, PERM open-ended, cut "
               "at the cancel or replacement that ended it) overlaps the UTC day and it was in the FAA's active "
               "set then; cancels and replaces issued that day are listed too.")


# ---------- one NOTAM ----------

def _core(f: dict) -> dict:
    return (f.get("properties") or {}).get("coreNOTAMData") or {}


def _text(f: dict) -> tuple[str, str | None]:
    """(the NMS text field, the ICAO text or the local format's text)."""
    core = _core(f)
    other = None
    for t in core.get("notamTranslation") or []:
        if t.get("type") == "ICAO" and t.get("formattedText"):
            return (core.get("notam") or {}).get("text") or "", t["formattedText"]
        other = other or t.get("simpleText") or t.get("formattedText")
    return (core.get("notam") or {}).get("text") or "", other


def q_code(f: dict) -> str | None:
    n = _core(f).get("notam") or {}
    if n.get("selectionCode"):
        return n["selectionCode"].upper()
    m = QLINE.search(_text(f)[1] or "")
    return m.group(1) if m else None


def words(text: str) -> list[str]:
    """GNSS words that sit within NEAR characters of a word about the signal, once EQUIPMENT phrases are out."""
    t = EQUIPMENT.sub(" ", re.sub(r"\s+", " ", (text or "").upper()))
    out = []
    for m in WORDS.finditer(t):
        if SIGNAL.search(t[max(0, m.start() - NEAR): m.end() + NEAR]) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def refers_to(f: dict) -> str | None:
    n = _core(f).get("notam") or {}
    if (n.get("type") or "") not in ("C", "R"):
        return None
    m = REFERS.search(_text(f)[1] or "") or REFERS.search(n.get("text") or "")
    return m.group(1) if m else None


def select(f: dict) -> dict | None:
    """Why a feature is kept by Q-code or text (`refers` is decided against the store), or None."""
    q = q_code(f)
    if q and q[1:3] in Q_SUBJECTS:
        return {"matched_by": "q-code", "q_code": q, "words": words(" ".join(t or "" for t in _text(f)))}
    w = words(" ".join(t or "" for t in _text(f)))
    if w:
        return {"matched_by": "text", "q_code": q, "words": w}
    return None


def key(n: dict) -> str:
    """NOTAM number, FIR (else location) and account: stable across pulls."""
    return f"{n.get('number')}|{n.get('affectedFir') or n.get('icaoLocation') or n.get('location') or ''}|{n.get('accountId') or ''}"


def _redact(s: str | None, counter: list) -> str | None:
    if not s:
        return s
    out, k = EMAIL.subn(EMAIL_NOTE, s)
    counter[0] += k
    return out


def record(f: dict, why: dict, now: str, counter: list) -> dict:
    raw = dict(_core(f).get("notam") or {})
    raw["text"] = _redact(raw.get("text"), counter)
    return {"key": key(raw), **why, "refers_to": refers_to(f), "notam": raw,
            "icao_text": _redact(_text(f)[1], counter), "geometry": f.get("geometry"),
            "first_seen": now, "last_seen": now, "gone_at": None,
            "cancelled_by": None, "replaced_by": None, "ended_at": None}


# ---------- the store ----------

def _dt(s) -> datetime | None:
    if not s or not isinstance(s, str) or s.upper() == "PERM":
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty() -> dict:
    return {"rule": RULE, "env": None, "bulk_at": None, "pulled_to": None, "notices": {}, "runs": [],
            "emails_removed": 0}


def load(path: Path) -> dict:
    try:
        s = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except ValueError:
        s = None
    return s if isinstance(s, dict) and isinstance(s.get("notices"), dict) else empty()


def update(store: dict, feats: list[dict], mode: str, now: datetime, env: str | None) -> dict:
    """Apply one pull (mode "bulk" or "delta") to the store. A bulk pull is the FAA's whole active set: a kept
    NOTAM missing from it has left it (`gone_at`). A cancel or replace of a kept NOTAM marks it ended."""
    s = {**empty(), **store, "notices": dict(store.get("notices") or {})}
    t = iso(now)
    counter = [0]
    seen = set()
    for f in feats:
        why = select(f)
        ref = refers_to(f)
        raw = _core(f).get("notam") or {}
        fir = raw.get("affectedFir") or raw.get("icaoLocation") or raw.get("location") or ""
        target = None
        if ref:
            target = next((k for k, v in s["notices"].items()
                           if (v["notam"].get("number") == ref
                               and (v["notam"].get("affectedFir") or v["notam"].get("icaoLocation")
                                    or v["notam"].get("location") or "") == fir)), None)
        if not why and target:
            why = {"matched_by": "refers", "q_code": q_code(f), "words": []}
        if not why:
            continue
        rec = record(f, why, t, counter)
        k = rec["key"]
        seen.add(k)
        old = s["notices"].get(k)
        if old:
            for f_ in ("first_seen", "cancelled_by", "replaced_by", "ended_at"):
                rec[f_] = old.get(f_)
        s["notices"][k] = rec
        if target and target != k:
            tg = dict(s["notices"][target])
            tg["cancelled_by" if raw.get("type") == "C" else "replaced_by"] = raw.get("number")
            tg["ended_at"] = tg.get("ended_at") or raw.get("issued") or t
            s["notices"][target] = tg
    if mode == "bulk":
        for k, v in list(s["notices"].items()):
            if k not in seen and not v.get("gone_at"):
                s["notices"][k] = {**v, "gone_at": t}
            elif k in seen and v.get("gone_at"):
                s["notices"][k] = {**v, "gone_at": None}
        s["bulk_at"] = t
    s["pulled_to"], s["env"], s["rule"], s["mode"] = t, env, RULE, mode
    s["emails_removed"] = int(store.get("emails_removed") or 0) + counter[0]
    return prune(s, now)


def prune(s: dict, now: datetime) -> dict:
    cut = now - timedelta(days=KEEP_DAYS + 2)
    keep = {}
    for k, v in s["notices"].items():
        last = max([d for d in (_end(v), _dt(v.get("gone_at")), _dt(v.get("last_seen"))) if d] or [now])
        if not (v.get("gone_at") or _end(v)) or last >= cut:
            keep[k] = v
    s["notices"] = keep
    s["runs"] = [r for r in s.get("runs") or [] if (_dt(r.get("at")) or now) >= cut]
    return s


def log_run(s: dict, now: datetime, lane: dict) -> dict:
    run = {"at": iso(now), "status": lane.get("status") or "not run"}
    if lane.get("status") == "ok":
        run["mode"] = s.get("mode")
    s = {**s, "runs": list(s.get("runs") or []) + [run]}
    return s


# ---------- windows ----------

def _start(v: dict) -> datetime | None:
    return _dt(v["notam"].get("effectiveStart")) or _dt(v["notam"].get("issued"))


def _end(v: dict) -> datetime | None:
    """effectiveEnd, cut at the cancel or replacement that ended it; None when open-ended (PERM, or none)."""
    ends = [d for d in (_dt(v["notam"].get("effectiveEnd")), _dt(v.get("ended_at"))) if d]
    return min(ends) if ends else None


def in_force(v: dict, at: datetime) -> bool:
    if (v["notam"].get("type") or "") == "C" or v.get("gone_at"):
        return False
    st, en = _start(v), _end(v)
    return (st is None or st <= at) and (en is None or at < en)


def on_day(v: dict, d0: datetime) -> bool:
    d1 = d0 + timedelta(days=1)
    if (v["notam"].get("type") or "") in ("C", "R"):
        issued = _dt(v["notam"].get("issued"))
        if issued and d0 <= issued < d1:
            return True
        if (v["notam"].get("type") or "") == "C":
            return False
    gone = _dt(v.get("gone_at"))
    if gone and gone <= d0:
        return False
    st, en = _start(v), _end(v)
    return (st is None or st < d1) and (en is None or en > d0)


# ---------- the published files ----------

def _public(v: dict, at: datetime | None = None) -> dict:
    out = {k: v.get(k) for k in ("matched_by", "q_code", "words", "refers_to", "notam", "icao_text", "geometry",
                                 "first_seen", "last_seen", "gone_at", "cancelled_by", "replaced_by", "ended_at")}
    if at is not None:
        out["in_force"] = in_force(v, at)
    return out


def _order(v: dict):
    return (v["notam"].get("effectiveStart") or "", v["notam"].get("number") or "", v.get("key") or "")


def _counts(notices: list[dict]) -> dict:
    by, qtext = {}, {}
    for n in notices:
        by[n["matched_by"]] = by.get(n["matched_by"], 0) + 1
        if n["matched_by"] == "text":
            q = n.get("q_code") or "none"
            qtext[q] = qtext.get(q, 0) + 1
    return {"by_rule": by, "q_codes_on_text_matches": dict(sorted(qtext.items(), key=lambda x: (-x[1], x[0])))}


def header(s: dict, lane: dict, source_note: str) -> dict:
    return {"program": "launch", "dataset": "gnss-notams", "rule": RULE, "source": "FAA NMS-API",
            "source_note": source_note, "env": s.get("env"), "lane_status": lane.get("status"),
            "lane_note": lane.get("note") or lane.get("error"), "bulk_at": s.get("bulk_at"),
            "pulled_to": s.get("pulled_to"), "selection": SELECTION,
            "email_note": f"Email addresses in the text are replaced by '{EMAIL_NOTE}'."}


def day_doc(s: dict, day: datetime, lane: dict, source_note: str, now: datetime) -> dict:
    d0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
    d1 = d0 + timedelta(days=1)
    notices = sorted((v for v in s["notices"].values() if on_day(v, d0)), key=_order)
    runs = [r for r in s.get("runs") or [] if d0 <= (_dt(r["at"]) or d0) < d1]
    by = {}
    for r in runs:
        by[r["status"]] = by.get(r["status"], 0) + 1
    pub = [_public(v) for v in notices]
    return {**header(s, lane, source_note), "day": d0.strftime("%Y-%m-%d"), "window_rule": WINDOW_RULE,
            "runs_that_day": by, "written_at": iso(now), "revised_at": None, "n": len(pub), **_counts(pub),
            "notices": pub}


def _same(a: dict, b: dict) -> bool:
    strip = ("last_seen",)
    return ([{k: v for k, v in n.items() if k not in strip} for n in a.get("notices") or []]
            == [{k: v for k, v in n.items() if k not in strip} for n in b.get("notices") or []])


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        return None


def _write(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def restore(gdir: Path, getter) -> int:
    """With no index here (a lost cache), fetch the published day files of the last KEEP_DAYS days."""
    if (gdir / "index.json").exists() or getter is None:
        return 0
    try:
        idx = json.loads(getter(PUBLISHED + "index.json", 60))
    except Exception:  # nothing published yet, or the site is down: start afresh
        return 0
    got = 0
    for d in (idx.get("days") or [])[:KEEP_DAYS]:
        name = d.get("day")
        if not (isinstance(name, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", name)):
            continue
        try:
            doc = json.loads(getter(PUBLISHED + name + ".json", 60))
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("day") == name:
            _write(gdir / "days" / (name + ".json"), doc)
            got += 1
    return got


def publish(gdir: Path, now: datetime, lane: dict, source_note: str, getter=None) -> dict:
    """Log this run, write active.json, the ended days' files and index.json under gdir. Returns a summary."""
    restored = restore(gdir, getter)
    s = log_run(load(gdir / "store.json"), now, lane)
    s = prune(s, now)
    _write(gdir / "store.json", s)
    act = sorted((v for v in s["notices"].values() if not v.get("gone_at")), key=_order)
    pub = [_public(v, _dt(s.get("pulled_to")) or now) for v in act]
    _write(gdir / "active.json", {**header(s, lane, source_note), "generated_at": iso(now),
                                  "active_rule": "The kept NOTAMs in the FAA's active set at the last pull "
                                                 "(pulled_to); in_force is at that time.",
                                  "n": len(pub), **_counts(pub), "notices": pub})
    days_dir = gdir / "days"
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ran = sorted({(_dt(r["at"]) or now).replace(hour=0, minute=0, second=0, microsecond=0)
                  for r in s.get("runs") or []})
    written, revised = [], []
    for d0 in ran:
        if d0 >= today or now >= d0 + timedelta(days=1, hours=REVISE_HOURS):
            continue
        p = days_dir / (d0.strftime("%Y-%m-%d") + ".json")
        new = day_doc(s, d0, lane, source_note, now)
        old = _read(p)
        if old is None:
            _write(p, new)
            written.append(p.stem)
        elif not _same(old, new):
            new["written_at"], new["revised_at"] = old.get("written_at"), iso(now)
            _write(p, new)
            revised.append(p.stem)
    cut = (today - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    days = []
    for p in sorted(days_dir.glob("*.json"), reverse=True) if days_dir.exists() else []:
        if p.stem < cut:
            p.unlink()
            continue
        doc = _read(p) or {}
        days.append({"day": p.stem, "n": doc.get("n"), "written_at": doc.get("written_at"),
                     "revised_at": doc.get("revised_at"), "runs_that_day": doc.get("runs_that_day"),
                     "url": PUBLISHED + p.stem + ".json"})
    _write(gdir / "index.json", {**header(s, lane, source_note), "generated_at": iso(now), "keep_days": KEEP_DAYS,
                                 "active": PUBLISHED + "active.json", "days": days})
    return {"active": len(pub), "kept": len(s["notices"]), "days": len(days), "written": written,
            "revised": revised, "restored": restored, "rule": RULE}


def site_files(gdir: Path) -> dict[str, str]:
    """The published files, for `build` (site/data/gnss-notams/)."""
    out = {}
    for name in ("active.json", "index.json"):
        if (gdir / name).exists():
            out["data/gnss-notams/" + name] = (gdir / name).read_text(encoding="utf-8")
    for p in sorted((gdir / "days").glob("*.json")) if (gdir / "days").exists() else []:
        out["data/gnss-notams/" + p.name] = p.read_text(encoding="utf-8")
    return out
