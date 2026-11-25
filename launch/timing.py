"""When launches come inside their closure windows: from closure opening to launch, by launch site.

For each launch in the History list with a launch time to the minute (GCAT's) and a pad, the notice taken is the
one nearest the pad whose window holds the launch time (NotamForChina's, Joey0609/notams', the archived FAA TFRs);
with the pad inside or near it, it is the first-stage or pad closure. The offset is launch time minus that window's
opening, in minutes; the window's length is kept too. A site's figures (count, median, quartiles) say how its
launches have sat in their windows, e.g. "Jiuquan: median 8 min after the nearest closure opened". They describe
the history; they are not a forecast of any one launch.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median, quantiles

from . import notam

NEAR_NM = 450        # the nearest notice must lie within this of the pad (the first stage's fall area or nearer;
                     # Taiyuan's southward first-stage areas lie about 330 NM off)
MAX_WINDOW_H = 6     # a longer window says little about when in it the launch came
MIN_LAUNCHES = 5     # a site's figures are given from this many launches


def _dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def _rings(n: dict) -> list:
    if n.get("ring"):
        return [n["ring"]]
    return n.get("rings") or []


def offset(rec: dict) -> dict | None:
    t, pad = _dt(rec.get("time")), rec.get("pad")
    if not t or not pad or (rec.get("time_basis") or "time") != "time" or len(rec.get("time") or "") < 16:
        return None
    best = None
    for key in ("nfc_notices", "joey_notices", "archive_notices"):
        for n in rec.get(key) or []:
            s, e = _dt(n.get("start")), _dt(n.get("end"))
            if not (s and e and s <= t <= e) or (e - s).total_seconds() > MAX_WINDOW_H * 3600:
                continue
            for r in _rings(n):
                if len(r) < 3:
                    continue
                la, lo = notam.centroid(r)
                d = notam.haversine_nm(pad[1], pad[0], la, lo)
                if d <= NEAR_NM and (best is None or d < best["nm"]):
                    best = {"nm": round(d), "open_min": round((t - s).total_seconds() / 60, 1),
                            "window_min": round((e - s).total_seconds() / 60, 1), "source": key.split("_")[0]}
    return best


def by_site(records: list[dict]) -> dict:
    sites: dict[str, list[dict]] = {}
    for r in records:
        if r.get("kind") == "Combat launch":
            continue
        o = offset(r)
        if o:
            sites.setdefault(r.get("site") or "?", []).append({**o, "pad": r["pad"]})
    out = {}
    for site, xs in sites.items():
        if len(xs) < MIN_LAUNCHES:
            continue
        mins = sorted(x["open_min"] for x in xs)
        q = quantiles(mins, n=4) if len(mins) >= 4 else [mins[0], median(mins), mins[-1]]
        out[site] = {"pad": [round(median(x["pad"][0] for x in xs), 3), round(median(x["pad"][1] for x in xs), 3)],
                     "launches": len(xs), "median_min": round(median(mins), 1), "q1_min": round(q[0], 1),
                     "q3_min": round(q[2], 1), "within_15_min": sum(1 for m in mins if m <= 15),
                     "median_window_min": round(median(x["window_min"] for x in xs), 1),
                     "max_window_min": round(max(x["window_min"] for x in xs), 1)}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["launches"]))


def expect(ring: list, start: str, end: str, sites: dict) -> dict | None:
    """For a live closure area: the nearest site with figures whose pad is within NEAR_NM, and the time its
    median offset gives from the area's opening ("if a launch from there, around ..."). None when no site fits,
    the window is longer than MAX_WINDOW_H, or it is longer than the longest window any of that site's launches had
    (`max_window_min`; 24 Nov 2026: a 6 h Vietnamese "ROCKET FRNG" area 260 NM from Wenchang, whose launches' windows
    ran 20 min at the median and 205 at most, read as a Wenchang launch)."""
    s, e = _dt(start), _dt(end)
    if not (s and e and ring and len(ring) >= 3 and sites) or (e - s).total_seconds() > MAX_WINDOW_H * 3600:
        return None
    la, lo = notam.centroid(ring)
    best = None
    for name, f in sites.items():
        d = notam.haversine_nm(la, lo, f["pad"][1], f["pad"][0])
        if d <= NEAR_NM and (best is None or d < best[0]):
            best = (d, name, f)
    if not best:
        return None
    d, name, f = best
    if f.get("max_window_min") and (e - s).total_seconds() / 60 > f["max_window_min"]:
        return None
    at = s + timedelta(minutes=f["median_min"])
    return {"site": name, "nm": round(d), "median_min": f["median_min"], "q1_min": f["q1_min"], "q3_min": f["q3_min"],
            "launches": f["launches"], "at": at.strftime("%Y-%m-%dT%H:%M:%SZ")}
