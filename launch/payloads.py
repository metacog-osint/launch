"""Reference rates for the payload of an upcoming launch whose payload is not known.

For each upcoming launch in the History list with mission type "Payload not known", the past orbital launches of the
same vehicle from the same site (pad within SITE_NM) form the reference class. It is narrowed in two steps, and every
step is shown with its own count:

1. inclination: the past launches whose GCAT inclination lies within INC_TOL of the inclination the launch's own
   matched closure areas imply (the farthest place-matched area's `inclination_est` in the snapshot, the same one
   live.on_track reads; incbias corrects it on the site's history);
2. closure signature: of those, the past launches with a notice area (NotamForChina, Joey0609, archived FAA TFRs, a
   provisional record's closures, or the charted notices in history/history.json) whose centre lies within SIG_NM of
   the centre of one of the launch's matched areas beyond NEAR_PAD_NM (an area at the pad says nothing of the orbit).

A step with fewer than MIN_N launches is shown but not used. When the vehicle has fewer than MIN_N launches from the
site, the vehicle's launches from any site are shown as a wider class. Each class counts the payload series (the
record's first programme, else its mission type) and the mission types, each with a 95% Clopper-Pearson range, and
lists the last LAST_N launches.

What the counts cannot show: launches of one series come in batches planned together, so they are not independent
draws and the ranges are too narrow; the samples are small; a new series has no history at all; and the vehicle and
site in the schedule may change. These are counts of what flew before, not a forecast of what flies next.

Scoring (`score`): each run appends the rates of the narrowest used step to an append-only ledger, once per change.
When the launch has flown and its payload is known, the last forecast made before launch is scored once: whether the
top series was right, and the multi-class Brier score over the series (classes not seen in the sample count as one
"other" class with rate 0). The ledger is never pruned.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

from . import notam

METHOD = "payloads-0.1"
SITE_NM = 30          # a past launch's pad this near the upcoming pad counts as the same site
INC_TOL = 3.0         # degrees either side of the implied inclination (incbias: mean absolute error 1.8)
SIG_NM = 60           # a past notice area's centre this near one of the launch's area centres is the same place
NEAR_PAD_NM = 50      # areas nearer the pad than this are pad closures and give no signature
MIN_N = 3             # a step with fewer launches is shown, not used
LAST_N = 10
ALPHA = 0.05
UNKNOWN = "Payload not known"
NOTICE_KEYS = ("nfc_notices", "joey_notices", "archive_notices", "closures")


def _dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


# ---------------------------------------------------------------- Clopper-Pearson, standard library only
def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), summed in logs so large n does not underflow."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k + 1)]
    m = max(terms)
    return min(1.0, math.exp(m) * sum(math.exp(t - m) for t in terms))


def _solve(f, target: float) -> float:
    """p in [0, 1] with f(p) = target, f decreasing in p; bisection."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(k: int, n: int, alpha: float = ALPHA) -> tuple[float, float]:
    """The exact two-sided (1 - alpha) range for k successes in n trials."""
    if n <= 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else _lower(k, n, alpha)
    hi = 1.0 if k == n else _solve(lambda p: _binom_cdf(k, n, p), alpha / 2)
    return lo, hi


def _lower(k: int, n: int, alpha: float) -> float:
    # P(X >= k | p) = 1 - cdf(k - 1) rises with p; find where it reaches alpha / 2.
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 1 - _binom_cdf(k - 1, n, mid) < alpha / 2:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- classes and steps
def series(rec: dict) -> str:
    progs = rec.get("programmes") or []
    return progs[0] if progs else (rec.get("mtype") or "Not classified")


def known(rec: dict) -> bool:
    return rec.get("mtype") not in (None, "", UNKNOWN)


def _past(records: list[dict], before: datetime | None) -> list[dict]:
    out = []
    for r in records:
        t = _dt(r.get("time"))
        if (r.get("status") == "launched" and r.get("kind") == "Orbital" and not r.get("cancelled") and t
                and (before is None or t < before)):
            out.append(r)
    return sorted(out, key=lambda r: r["time"])


def _same_site(a: dict, b: dict) -> bool:
    pa, pb = a.get("pad"), b.get("pad")
    if pa and pb:
        return notam.haversine_nm(pa[1], pa[0], pb[1], pb[0]) <= SITE_NM
    return bool(a.get("site")) and a.get("site") == b.get("site")


def _rings(n: dict) -> list:
    return [n["ring"]] if n.get("ring") else (n.get("rings") or [])


def centres(rec: dict, charted: dict) -> list[tuple[float, float]]:
    """(lat, lon) of each notice area a past launch carries, its charted notices' areas included."""
    out = []
    for key in NOTICE_KEYS:
        for n in rec.get(key) or []:
            for r in _rings(n):
                if r and len(r) >= 3:
                    out.append(notam.centroid(r))
    for hid in rec.get("chart") or []:
        for a in (charted.get(hid) or {}).get("areas") or []:
            c = a.get("centroid")
            if c:
                out.append((c[1], c[0]))
            elif a.get("ring") and len(a["ring"]) >= 3:
                out.append(notam.centroid(a["ring"]))
    return out


def _rate_rows(cnt: Counter, n: int) -> list[dict]:
    rows = []
    for name, k in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])):
        lo, hi = clopper_pearson(k, n)
        rows.append({"class": name, "k": k, "rate": round(k / n, 3), "lo": round(lo, 3), "hi": round(hi, 3)})
    return rows


def step(name: str, recs: list[dict], basis: str) -> dict:
    kn = [r for r in recs if known(r)]
    n = len(kn)
    return {"step": name, "basis": basis, "n": n, "unknown": len(recs) - n, "used": n >= MIN_N,
            "series": _rate_rows(Counter(series(r) for r in kn), n) if n else [],
            "mtypes": _rate_rows(Counter(r["mtype"] for r in kn), n) if n else [],
            "last": [{"time": r["time"][:10], "id": r["id"], "payload": r.get("payload"), "series": series(r),
                      "inc": r.get("inc")} for r in kn[-LAST_N:]][::-1]}


def implied(launch_uuid: str, matches: list[dict]) -> dict | None:
    """The launch's farthest place-matched area beyond NEAR_PAD_NM and its implied inclination, else None."""
    placed = [m for m in matches if m.get("launch") == launch_uuid and m.get("level") != "time"
              and (m.get("distance_nm") or 0) > NEAR_PAD_NM and m.get("inclination_est") is not None]
    if not placed:
        return None
    far = max(placed, key=lambda m: m["distance_nm"])
    return {"inc": far["inclination_est"], "area": far.get("area"), "basis": far.get("inclination_basis")}


def area_centres(launch_uuid: str, matches: list[dict], areas: list[dict]) -> list[tuple[float, float]]:
    out = []
    for m in matches:
        if m.get("launch") != launch_uuid or m.get("level") == "time" or (m.get("distance_nm") or 0) <= NEAR_PAD_NM:
            continue
        i = m.get("area_i")
        ring = (areas[i] if isinstance(i, int) and 0 <= i < len(areas) else {}).get("ring")
        if ring and len(ring) >= 3:
            c = notam.centroid(ring)
            if c not in out:
                out.append(c)
    return out


def _near_any(cs: list, targets: list) -> bool:
    return any(notam.haversine_nm(a[0], a[1], b[0], b[1]) <= SIG_NM for a in cs for b in targets)


def rates_for(up: dict, records: list[dict], snap: dict, charted: dict) -> dict:
    uuid = up.get("ll2") or (up.get("id") or "").split(":")[-1]
    past = _past(records, _dt(up.get("time")))
    veh = [r for r in past if r.get("vehicle") == up.get("vehicle")]
    site = [r for r in veh if _same_site(r, up)]
    steps = [step("vehicle and site", site, f"orbital launches of the {up.get('vehicle')} from {up.get('site')} "
                                            f"(pad within {SITE_NM} NM) in the History list")]
    if len(site) < MIN_N and len(veh) > len(site):
        steps.append(step("vehicle, any site", veh, f"orbital launches of the {up.get('vehicle')} from any site: a "
                                                    "wider class, as the site has too few"))
    matches = snap.get("matches") or []
    inc = implied(uuid, matches)
    base = site if len(site) >= MIN_N else veh
    if inc:
        near = [r for r in base if r.get("inc") is not None and abs(r["inc"] - inc["inc"]) <= INC_TOL]
        steps.append(step("inclination", near, f"of those, GCAT inclination within {INC_TOL:g} degrees of "
                                               f"{inc['inc']:g} (implied by area {inc['area']}: {inc['basis']})"))
        tc = area_centres(uuid, matches, snap.get("areas") or [])
        if tc and len(near) >= MIN_N:
            sig = [r for r in near if _near_any(centres(r, charted), tc)]
            steps.append(step("closure signature", sig, f"of those, a past notice area within {SIG_NM} NM of one of "
                                                        f"this launch's {len(tc)} matched areas beyond {NEAR_PAD_NM} NM"))
    used = [s for s in steps if s["used"]]
    return {"launch": up.get("id"), "ll2": uuid, "label": up.get("label"), "net": up.get("time"),
            "vehicle": up.get("vehicle"), "site": up.get("site"), "implied_inclination": inc, "steps": steps,
            "forecast_step": used[-1]["step"] if used else None}


def build(records: list[dict], snap: dict, charted: dict) -> list[dict]:
    ups = [r for r in records if r.get("status") == "upcoming" and r.get("mtype") == UNKNOWN]
    return [rates_for(u, records, snap, charted) for u in sorted(ups, key=lambda r: r.get("time") or "")]


def charted_index(history_doc: dict | None) -> dict:
    return {e["id"]: e for e in (history_doc or {}).get("events") or [] if e.get("id")}


# ---------------------------------------------------------------- scoring ledger (append-only)
def forecast_entry(res: dict, at: str) -> dict | None:
    s = next((x for x in res["steps"] if x["step"] == res["forecast_step"]), None)
    if not s:
        return None
    probs = {r["class"]: r["rate"] for r in s["series"]}
    return {"kind": "forecast", "at": at, "method": METHOD, "ll2": res["ll2"], "label": res["label"],
            "net": res["net"], "step": s["step"], "n": s["n"], "top": s["series"][0]["class"], "probs": probs}


def brier(probs: dict, actual: str) -> float:
    total = sum((p - (1.0 if c == actual else 0.0)) ** 2 for c, p in probs.items())
    if actual not in probs:
        other = max(0.0, 1.0 - sum(probs.values()))
        total += (other - 1.0) ** 2
    return round(total, 4)


def score(ledger: list[dict], results: list[dict], records: list[dict], at: str) -> list[dict]:
    """New ledger lines: a forecast for each result whose rates changed since its last forecast, and an outcome for
    each forecast launch that has flown with a known payload and has no outcome yet."""
    new = []
    last = {}
    for e in ledger:
        if e.get("kind") == "forecast":
            last[e["ll2"]] = e
    for res in results:
        f = forecast_entry(res, at)
        if not f:
            continue
        prev = last.get(f["ll2"])
        if not prev or (prev["probs"], prev["step"], prev["n"]) != (f["probs"], f["step"], f["n"]):
            new.append(f)
            last[f["ll2"]] = f
    scored = {e["ll2"] for e in ledger if e.get("kind") == "outcome"}
    flown = {}
    for r in records:
        u = r.get("ll2") or ((r.get("id") or "").split(":", 1)[1] if (r.get("id") or "").startswith("ll2:") else None)
        if u and r.get("status") == "launched" and known(r):
            if u not in flown or "gcat" in (r.get("sources") or []):
                flown[u] = r
    forecasts = [e for e in ledger + new if e.get("kind") == "forecast"]
    for u, r in sorted(flown.items()):
        if u in scored:
            continue
        t = _dt(r.get("time"))
        mine = [e for e in forecasts if e["ll2"] == u and (t is None or _dt(e["at"]) < t)]
        if not mine:
            continue
        f = max(mine, key=lambda e: e["at"])
        actual = series(r)
        new.append({"kind": "outcome", "at": at, "method": f["method"], "ll2": u, "launch": r.get("id"),
                    "time": r.get("time"), "payload": r.get("payload"), "actual": actual, "forecast_at": f["at"],
                    "top": f["top"], "top_right": f["top"] == actual, "p_actual": f["probs"].get(actual, 0.0),
                    "brier": brier(f["probs"], actual)})
        scored.add(u)
    return new


def summary(ledger: list[dict]) -> dict:
    outs = [e for e in ledger if e.get("kind") == "outcome"]
    if not outs:
        return {"scored": 0}
    return {"scored": len(outs), "top_right": sum(1 for e in outs if e["top_right"]),
            "mean_brier": round(sum(e["brier"] for e in outs) / len(outs), 4)}
