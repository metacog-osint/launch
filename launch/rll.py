"""RocketLaunch.Live: the next five launches from its free JSON API, a second source for the upcoming store.

One request a run to `fdo.rocketlaunch.live/json/launches/next/5` (the free tier: no key, the next five launches
only, no history). Its terms ask for the credit "Data by RocketLaunch.Live" near the data; every place the data
goes (data/upcoming.json, the snapshot, feed items) carries it. robots.txt allows the path.

Each launch becomes a row in the store's field names (launch/schedule.py FIELDS) under source `rll`, with its own id
(RocketLaunch.Live's numeric launch id). The free tier gives no pad coordinates and no status, so:
  - lat/lon come from a launch Launch Library 2 already lists at the same place (`place()`), else stay empty;
  - status is left empty: RocketLaunch.Live publishes no go/hold state on this tier.

A record that RocketLaunch.Live and Launch Library 2 both list is one launch (`pairs()`): the same place (a shared
place word, `place_words()`), NETs within JOIN_HOURS, and vehicles that do not differ (`same_vehicle()`, an
unconfirmed vehicle differs from none). When more than one LL2 record qualifies, the nearest NET wins only if it is
the only one that near; otherwise nothing is joined and both records stay. Joining keeps the id seen first
(schedule.join()).

The free tier lists five launches, so a launch can drop out of it while still scheduled: the store then marks it
no longer listed by `rll` (schedule.ingest), and a record no other source lists leaves the live view.

Standard-library Python only.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

SOURCE = "rll"
API = "https://fdo.rocketlaunch.live/json/launches/next/5"
SITE = "https://www.rocketlaunch.live"
CREDIT = "Data by RocketLaunch.Live"
JOIN_HOURS = 3.0          # NETs this close, at one place, with vehicles that do not differ: one launch
ROUGH_JOIN_HOURS = 36.0   # when either NET is dated only to the day or coarser
# Words that name a kind of place, not which one: never enough to say two places are the same.
_STOP = {"launch", "complex", "center", "centre", "site", "space", "spaceport", "satellite", "cosmodrome", "station",
         "base", "force", "peninsula", "rocket", "lab", "people's", "peoples", "republic", "china", "usa", "sea",
         "offshore", "platform", "island", "range", "area", "facility", "the", "of", "and", "pad", "national",
         "test", "flight", "air", "sfb", "sfs", "afb", "afs", "spaceflight", "commercial", "federation", "russian",
         "state", "united", "states", "new", "zealand", "india", "japan", "france", "kazakhstan", "korea"}
_UNCONFIRMED = re.compile(r"\bunconfirmed\b|\btbd\b|\bunknown\b", re.I)


def _dt(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _net(r: dict) -> tuple[str | None, str]:
    """(NET, precision in Launch Library 2's words). t0 is the launch time; win_open a window's opening; otherwise
    sort_date, dated only as finely as est_date says."""
    for key in ("t0", "win_open"):
        d = _dt(r.get(key))
        if d:
            return _iso(d), "Minute"
    try:
        d = datetime.fromtimestamp(int(r.get("sort_date")), tz=timezone.utc)
    except (TypeError, ValueError):
        return None, ""
    est = r.get("est_date") or {}
    precision = ("Day" if est.get("day") else "Month" if est.get("month") else "Quarter" if est.get("quarter")
                 else "Year" if est.get("year") else "Day")
    return _iso(d), precision


def row(r: dict) -> dict | None:
    """One RocketLaunch.Live launch in the store's field names, or None without an id or a date."""
    if not isinstance(r, dict) or r.get("id") in (None, ""):
        return None
    net, precision = _net(r)
    if not net:
        return None
    pad = r.get("pad") or {}
    loc = pad.get("location") or {}
    missions = [m.get("name") for m in r.get("missions") or [] if isinstance(m, dict) and m.get("name")]
    vehicle = (r.get("vehicle") or {}).get("name") or ""
    win_open, win_close = _dt(r.get("win_open")), _dt(r.get("win_close"))
    slug = r.get("slug")
    return {
        "id": str(r["id"]), "name": (r.get("name") or "").strip().strip('"') or (missions[0] if missions else ""),
        "net": net, "net_precision": precision,
        "window_start": _iso(win_open) if win_open else None, "window_end": _iso(win_close) if win_close else None,
        "status": "", "status_name": "", "provider": (r.get("provider") or {}).get("name") or "",
        "provider_type": "", "provider_countries": [],
        "vehicle": "" if _UNCONFIRMED.search(vehicle) else vehicle,
        "mission": ", ".join(missions), "mission_type": "", "orbit": "", "orbit_name": "",
        "pad": pad.get("name") or "", "location": loc.get("name") or "", "pad_country": None,
        "lat": None, "lon": None, "country_name": loc.get("country"),
        "last_updated": r.get("modified"), "suborbital": bool(r.get("suborbital")),
        "rll_url": f"{SITE}/launch/{slug}" if slug else SITE,
    }


def parse(body) -> list[dict]:
    doc = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(doc, dict) or not isinstance(doc.get("result"), list):
        raise ValueError(f"RocketLaunch.Live reply has no result list: {str(doc)[:200]}")
    out = [x for x in (row(r) for r in doc["result"]) if x]
    out.sort(key=lambda x: (x["net"], x["id"]))
    return out


def place_words(*names) -> set[str]:
    words = set()
    for n in names:
        for w in re.findall(r"[a-z0-9']+", (n or "").lower()):
            if len(w) >= 4 and not w.isdigit() and w not in _STOP:
                words.add(w)
    return words


def _vehicle_words(v: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (v or "").lower())


def same_vehicle(a: str, b: str) -> bool:
    """True unless both are named and differ: one name's words must begin the other's ("Falcon 9" and "Falcon 9
    Block 5" agree; "Long March 6A" and "Long March 6C" differ)."""
    wa, wb = _vehicle_words(a), _vehicle_words(b)
    if not wa or not wb:
        return True
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return long_[:len(short)] == short


def _rough(p) -> bool:
    return (p or "") not in ("Second", "Minute", "Hour", "")


def _hours(a, b) -> float | None:
    da, db = _dt(a), _dt(b)
    return abs((da - db).total_seconds()) / 3600 if da and db else None


def candidates(rec: dict, others: list[dict]) -> list[tuple[float, dict]]:
    """The records in `others` that could be the same launch as `rec`, with the hours between their NETs."""
    words = place_words(rec.get("location"), rec.get("pad"))
    out = []
    for o in others:
        if o is rec or not words & place_words(o.get("location"), o.get("pad")):
            continue
        h = _hours(rec.get("net"), o.get("net"))
        limit = ROUGH_JOIN_HOURS if _rough(rec.get("net_precision")) or _rough(o.get("net_precision")) else JOIN_HOURS
        if h is None or h > limit or not same_vehicle(rec.get("vehicle"), o.get("vehicle")):
            continue
        out.append((h, o))
    return sorted(out, key=lambda t: t[0])


def pairs(store: dict) -> list[tuple[str, str]]:
    """(RocketLaunch.Live record id, Launch Library 2 record id) for each pair that is one launch. Only records
    one of the two sources holds (a RocketLaunch.Live record may also hold a closure notice); a record with two
    equally near candidates joins neither."""
    recs = store.get("records") or []
    rll_only = [r for r in recs if SOURCE in (r.get("refs") or {}) and "ll2" not in (r.get("refs") or {})]
    ll2 = [r for r in recs if "ll2" in (r.get("refs") or {}) and SOURCE not in (r.get("refs") or {})]
    out, used = [], set()
    for r in rll_only:
        c = [(h, o) for h, o in candidates(r, ll2) if o["id"] not in used]
        if not c or (len(c) > 1 and c[1][0] - c[0][0] < 1.0):
            continue
        used.add(c[0][1]["id"])
        out.append((r["id"], c[0][1]["id"]))
    return out


def place(rows: list[dict], store: dict) -> None:
    """Give each row the coordinates of a Launch Library 2 record at the same place (shared place word and pad),
    else of the place when every such record sits within a few kilometres of each other. In place."""
    known = [r for r in store.get("records") or [] if "ll2" in (r.get("refs") or {})
             and r.get("lat") is not None and r.get("lon") is not None]
    for x in rows:
        words = place_words(x.get("location"))
        if not words:
            continue
        here = [r for r in known if words & place_words(r.get("location"))]
        if not here:
            continue
        pw = place_words(x.get("pad"))
        same_pad = [r for r in here if pw and pw <= place_words(r.get("pad"))] or here
        lats = [r["lat"] for r in same_pad]
        lons = [r["lon"] for r in same_pad]
        if max(lats) - min(lats) > 0.2 or max(lons) - min(lons) > 0.2:
            continue  # several pads far apart (a sea-launch area, say): no single point
        x["lat"], x["lon"] = same_pad[0]["lat"], same_pad[0]["lon"]
        x["coords_from"] = "a Launch Library 2 launch at the same place"
