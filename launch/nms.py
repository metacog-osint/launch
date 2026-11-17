"""The FAA NOTAM Management Service API (NMS-API): the `nms` live lane.

Access: OAuth2 client credentials from the environment (NMS_CLIENT_ID, NMS_CLIENT_SECRET, set by hand; never
in this repository). NMS_ENV picks the host: "staging" (the pre-production environment the FAA opens first, the
default) or "prod" (after the FAA moves the account to production). Without both keys the lane says "waiting".

What it reads (the FAA's limits, NMS-API FAQ, Nov 2026: production allows one bulk pull a day and one delta pull
every 3 minutes; pre-production one request a second):
  - bulk, at most once in BULK_HOURS: every active NOTAM of each classification in CLASSES, as GeoJSON files;
  - otherwise a delta: every NOTAM created, replaced or cancelled since the last pull (lastUpdatedDate, at most 24 h
    back), applied to the notices kept from the last run (Launch's snapshot, kept in the Actions cache).
Every NOTAM is filtered here, not at the FAA: one bulk or delta pull, then Launch's own rules (keep()).

The FAA's terms allow redistribution but not calling it FAA data; the FAQ asks that NMS not be presented as the
authoritative source for non-US NOTAMs. SOURCE_NOTE says both on the page.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import joey, notam, timing

HOSTS = {"staging": "https://api-staging.cgifederal-aim.com", "prod": "https://api-nms.aim.faa.gov"}
UA = "tic-launch (+https://launch.theintelligence.company)"
CLASSES = ("INTERNATIONAL", "FDC", "MILITARY", "DOMESTIC")
BULK_HOURS = 24          # one bulk pull a day at most (FAA production limit)
DELTA_MAX_HOURS = 23.5   # lastUpdatedDate reaches 24 h back at most; older state means a bulk pull
OVERLAP_S = 60           # each delta starts a minute before the last one ended (FAA's advice)
PAUSE_S = 1.2            # between requests (pre-production: one a second)
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
RECUR_NM = 25                   # an area centred this close to a past launch closure area is "recurring"
RECUR_MAX_DAYS = 7


class Waiting(Exception):
    """No keys in the environment: the lane waits."""


# ---------- the client ----------

class Client:
    def __init__(self, env: dict | None = None, opener=None, pause: float = PAUSE_S):
        env = os.environ if env is None else env
        self.cid, self.secret = env.get("NMS_CLIENT_ID"), env.get("NMS_CLIENT_SECRET")
        if not (self.cid and self.secret):
            raise Waiting("NMS_CLIENT_ID and NMS_CLIENT_SECRET are not set")
        self.env_name = env.get("NMS_ENV") or "staging"
        self.host = HOSTS[self.env_name]
        self.open = opener or urllib.request.urlopen
        self.pause = pause
        self.token, self.token_until, self.requests, self._last = None, 0.0, 0, 0.0

    def _call(self, req: urllib.request.Request, timeout: int = 120) -> bytes:
        wait = self.pause - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        with self.open(req, timeout=timeout) as r:
            body = r.read()
        return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body

    def _auth(self) -> str:
        if self.token and time.monotonic() < self.token_until:
            return self.token
        basic = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        req = urllib.request.Request(self.host + "/v1/auth/token", data=b"grant_type=client_credentials",
                                     method="POST", headers={"User-Agent": UA, "Authorization": "Basic " + basic,
                                                             "Content-Type": "application/x-www-form-urlencoded"})
        j = json.loads(self._call(req, 60))
        self.token = j["access_token"]
        self.token_until = time.monotonic() + int(j.get("expires_in") or 1799) - 120
        return self.token

    def get(self, path: str, params: dict | None = None, fmt: str | None = "GEOJSON", timeout: int = 300) -> bytes:
        url = self.host + path + ("?" + urllib.parse.urlencode(params) if params else "")
        h = {"User-Agent": UA, "Authorization": "Bearer " + self._auth(), "Accept": "application/json"}
        if fmt:
            h["nmsResponseFormat"] = fmt
        return self._call(urllib.request.Request(url, headers=h), timeout)

    def classification(self, name: str) -> list[dict]:
        """Every active NOTAM of one classification: a content path, then the file it points to."""
        j = json.loads(self.get("/nmsapi/v1/notams", {"classification": name, "allowRedirect": "false"}))
        path = (j.get("data") or {}).get("url")
        if not path:
            raise ValueError(f"no content path for {name}: {str(j)[:160]}")
        body = self.get(path if path.startswith("/") else urllib.parse.urlparse(path).path, fmt=None)
        return features(json.loads(body))

    def delta(self, since: datetime) -> list[dict]:
        j = json.loads(self.get("/nmsapi/v1/notams", {"lastUpdatedDate": iso(since)}))
        return features(j)


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
            "issued": meta.get("issued"), "last_updated": meta.get("lastUpdated"), "text": n.get("e_text") or ""}


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


def pull(client: Client, prev: dict, past, now: datetime) -> dict:
    """One run: a bulk pull when the last is over BULK_HOURS old (or there is none) or the last pull is too old
    for a delta, else a delta from the last pull. Returns the lane's state for the snapshot."""
    bulk_at, pulled_to = _dt(prev.get("bulk_at")), _dt(prev.get("pulled_to"))
    store = {_key(n): n for n in prev.get("notices") or []}
    if (bulk_at is None or now - bulk_at >= timedelta(hours=BULK_HOURS) or pulled_to is None
            or now - pulled_to >= timedelta(hours=DELTA_MAX_HOURS)):
        feats, by_class = [], {}
        for c in CLASSES:
            got = client.classification(c)
            by_class[c] = len(got)
            feats += got
        res = apply({}, feats, past, now, replace_all=True)
        mode, bulk_at = "bulk", now
        res["counts"]["by_class"] = by_class
    else:
        feats = client.delta(pulled_to - timedelta(seconds=OVERLAP_S))
        res = apply(store, feats, past, now)
        mode = "delta"
    notices = sorted(res["notices"].values(), key=lambda n: (n.get("start") or "", n.get("number") or ""))
    kinds: dict[str, int] = {}
    for n in notices:
        kinds[n["kept"]] = kinds.get(n["kept"], 0) + 1
    return {"env": client.env_name, "mode": mode, "bulk_at": iso(bulk_at), "pulled_to": iso(now),
            "requests": client.requests, "counts": {**res["counts"], "kept_by_rule": kinds},
            "source_note": SOURCE_NOTE, "notices": notices}


def areas(state: dict, tfr_ids: set[str] | None = None, sites: dict | None = None) -> list[dict]:
    """Kept notices as areas for live.match. An FDC notice the tfr lane already holds is left to it. With
    history/timing.json's sites, an area near a pad carries `expect` (timing.expect)."""
    out = []
    for n in state.get("notices") or []:
        num = (n.get("number") or "")
        if tfr_ids and n.get("classification") == "FDC" and any(num.endswith(t) for t in tfr_ids):
            continue
        if not (n.get("start") and n.get("end")):
            continue
        for i, ring in enumerate(n.get("rings") or []):
            out.append({"source": "faa-nms", "id": f"{num} {n.get('fir') or ''}".strip()
                        + (f" area {i + 1}" if len(n["rings"]) > 1 else ""),
                        "label": (n.get("text") or "").split("\n")[0][:120], "ring": ring, "kept": n["kept"],
                        "windows": [{"start": n["start"], "end": n["end"]}], "ring_basis": n.get("ring_basis"),
                        "expect": timing.expect(ring, n["start"], n["end"], sites or {})})
    return out
