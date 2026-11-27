"""Closure with no listing: a live closure near a launch site, with no listed launch from that site in its windows.

An area qualifies when it has a window of MAX_WINDOW_H or less ahead, inside the schedule's horizon, and
`timing.expect` finds a site with launch-timing history within its NEAR_NM. A notice is judged whole: if a listed launch
from within LISTED_NM of that site falls in any of its windows, the other windows are that launch's reserve days and
the notice is left out. The same holds for a launch that has flown (`flown`: Launch Library 2's flown launches, which
its upcoming read drops about a day after launch): a notice with a window in which a launch flew from within LISTED_NM
of the site is that launch's, and its later windows are reserve days. A separate notice for a reserve day is left out
too: when every window of it overlaps (RESERVE_OVERLAP) a window of a notice already placed on a listed launch at the
same site, such as a later day of a NAVAREA warning that lists the launch's reserve days. A listing dated only to a day or a month cannot be placed in a window, so it is named beside
the closure (`maybe_listed`) and the closure stays. Areas at one site opening within GROUP_H are one row.

This says a closure exists and the schedule shows no launch for it. It does not say a launch is coming: closures are
also issued for tests and other activity, and some are cancelled. With no schedule read there is no row at all,
because an empty schedule would make every closure look unlisted.

Schedule records (Ascent move step 1b, 25 Nov 2026): each row is also a record in the multi-source upcoming store
(`launch/schedule.py`), source `closure`, evidence "closure with no listing", id `upcoming:closure:<notice key>`. The
record keeps the key it was first made under while any of its notices stays in a row, so a regrouped row keeps its
record. When a source lists an exactly dated launch from within LISTED_NM of the site inside the record's window
(the same test that removes a closure from the rows), the two records are joined with `schedule.join()`: the one seen
first keeps its id. A closure record never counts as a listing here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import notam, schedule, timing

MAX_WINDOW_H = timing.MAX_WINDOW_H
LISTED_NM = 100      # a listed launch this near the site counts as that site's (one range's pads lie well inside it)
BEFORE_H = 1         # as the live match: a launch up to an hour before the window opens still counts
GROUP_H = 2
RESERVE_OVERLAP = 0.5   # share of an area's window that a placed notice's window must cover to call it a reserve day
HORIZON_DAYS = 14    # schedule.HORIZON_DAYS: past it, the schedule cannot show that nothing is listed
EXACT = ("second", "minute", "hour")
SOURCE = "closure"   # the schedule store's source name for these rows
EVIDENCE = "closure with no listing"
PRECISION = "closure window"   # net is the window's opening, not a launch time


def _dt(s) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except (AttributeError, ValueError):
        return None


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _windows(area: dict) -> list[tuple[datetime, datetime]]:
    out = []
    for w in area.get("windows") or []:
        s, e = _dt((w or {}).get("start")), _dt((w or {}).get("end"))
        if s and e and e > s:
            out.append((s, e))
    return sorted(out)


def _exact(rec: dict) -> bool:
    p = (rec.get("net_precision") or "").lower()
    return any(x in p for x in EXACT)


def _in_window(rec: dict, s: datetime, e: datetime) -> bool:
    a, b = _dt(rec.get("window_start")) or _dt(rec.get("net")), _dt(rec.get("window_end")) or _dt(rec.get("net"))
    return bool(a and b and a <= e and b >= s - timedelta(hours=BEFORE_H))


def _may_be(rec: dict, s: datetime) -> bool:
    """A listing dated only roughly: the same day (a day either side), or the same month for anything coarser."""
    net = _dt(rec.get("net"))
    if not net:
        return False
    if "day" in (rec.get("net_precision") or "").lower():
        return abs(net - s) <= timedelta(days=1, hours=12)
    return (net.year, net.month) == (s.year, s.month)


def _listing(rec: dict) -> bool:
    """A schedule record that a source other than this module lists in its latest read. A record joined to a listing
    that has since gone reads as a closure with no listing again. Public records carry `listed_by`; store records
    their per-source `listed`; a bare row (tests, older copies) counts as listed unless its evidence says otherwise."""
    if "listed_by" in rec:
        return any(s != SOURCE for s in rec["listed_by"] or [])
    if rec.get("by_source"):
        return any(s != SOURCE for s in schedule.listed_by(rec))
    return "listed" in (rec.get("evidence") or ["listed"])


def _reserve_windows(areas: list[dict], placed: set, sites: dict) -> dict[str, list[tuple[datetime, datetime]]]:
    """By site: every window of the areas already placed on a listed launch (`placed`) that lie near that site. A
    notice placed on a launch often lists its reserve days as later windows (a NAVAREA warning: day one, then each
    following day), while the FAA issues a separate TFR for each reserve day."""
    out: dict[str, list] = {}
    for a in areas:
        if (a.get("key") or a.get("id")) not in placed:
            continue
        ws = [(s, e) for s, e in _windows(a) if e - s <= timedelta(hours=MAX_WINDOW_H)]
        x = timing.expect(a.get("ring") or [], _iso(ws[0][0]), _iso(ws[0][1]), sites) if ws else None
        if x:
            out.setdefault(x["site"], []).extend(ws)
    return out


def _reserve_day(short: list[tuple[datetime, datetime]], reserve: list[tuple[datetime, datetime]]) -> bool:
    """Every window of an area overlaps, for at least RESERVE_OVERLAP of its length, a window of a notice placed on a
    listed launch at the same site: the area is that launch's reserve day (27 Nov 2026: NG-25's NAVAREA IV warning
    listed 30 Nov and 1 Dec windows ending at the same minute as the Cape's separate TFRs for those days)."""
    def covered(s, e):
        return any((min(e, re) - max(s, rs)) >= (e - s) * RESERVE_OVERLAP for rs, re in reserve)
    return bool(short and reserve) and all(covered(s, e) for s, e in short)


def closures(areas: list[dict], records: list[dict], sites: dict, now: datetime,
             schedule_ok: bool = True, matches: list[dict] | None = None,
             flown: list[dict] | None = None) -> list[dict]:
    """`matches` are live.match's rows: an area that already coincides in time and place with a listed launch from
    any site (a downrange area, say, nearer another site), or whose text names a listed launch, is that launch's to
    explain, so it is left out. An area marked `off_live` (its text says it is not a launch) is left out too."""
    if not schedule_ok or not sites:
        return []
    records = [r for r in records if _listing(r)]
    until = now + timedelta(days=HORIZON_DAYS)
    placed = {m.get("area") for m in matches or [] if m.get("level") != "time" or m.get("named")}
    reserve = _reserve_windows(areas, placed, sites)
    found = []
    for a in areas:
        if (a.get("detail") or {}).get("activity"):  # amateur rocketry, named in the TFR's text
            continue
        if a.get("off_live"):  # a NOTAM whose text says it is not a launch (nms.off_live): never a launch's closure
            continue
        if (a.get("key") or a.get("id")) in placed:
            continue
        ahead = [(s, e) for s, e in _windows(a) if e > now and s <= until]
        short = [(s, e) for s, e in ahead if e - s <= timedelta(hours=MAX_WINDOW_H)]
        if not short:
            continue
        x = timing.expect(a.get("ring") or [], _iso(short[0][0]), _iso(short[0][1]), sites)
        if not x:
            continue
        if _reserve_day(short, reserve.get(x["site"]) or []):
            continue
        pad = sites[x["site"]]["pad"]
        near = [r for r in records if r.get("lat") is not None and r.get("lon") is not None
                and notam.haversine_nm(r["lat"], r["lon"], pad[1], pad[0]) <= LISTED_NM]
        if any(_exact(r) and _in_window(r, s, e) for r in near for s, e in ahead):
            continue
        flew = [r for r in flown or [] if r.get("lat") is not None and r.get("lon") is not None
                and notam.haversine_nm(r["lat"], r["lon"], pad[1], pad[0]) <= LISTED_NM]
        if any(_exact(r) and _in_window(r, s, e) for r in flew for s, e in _windows(a)):
            continue
        maybe = sorted({r.get("name") or "" for r in near if not _exact(r) and _may_be(r, short[0][0])} - {""})
        found.append({"key": a.get("key") or a.get("id"), "source": a.get("source"), "start": short[0][0],
                      "end": short[0][1], "more": len(short) - 1, "expect": x, "maybe": maybe})
    rows: list[dict] = []
    for f in sorted(found, key=lambda f: (f["expect"]["site"], f["start"], f["key"] or "")):
        row = rows[-1] if rows and rows[-1]["site"] == f["expect"]["site"] else None
        if row is None or f["start"] - _dt(row["start"]) > timedelta(hours=GROUP_H):
            row = {"id": f"unlisted:{f['key']}", "evidence": "closure with no listing", "site": f["expect"]["site"],
                   "start": _iso(f["start"]), "end": _iso(f["end"]), "more_windows": 0, "notices": [],
                   "expect": f["expect"], "maybe_listed": []}
            rows.append(row)
        row["end"] = max(row["end"], _iso(f["end"]))
        row["more_windows"] = max(row["more_windows"], f["more"])
        if f["key"] not in [n["key"] for n in row["notices"]]:
            row["notices"].append({"key": f["key"], "source": f["source"]})
        row["maybe_listed"] = sorted(set(row["maybe_listed"]) | set(f["maybe"]))
    return sorted(rows, key=lambda r: (r["start"], r["site"]))


# ---------- schedule records (Ascent move step 1b) ----------

def record_rows(rows: list[dict], sites: dict, store: dict) -> list[dict]:
    """Closure rows as the schedule store's source rows. A row whose notices a closure record already holds keeps that
    record's id; otherwise its first notice's key is the id."""
    held: dict[str, str] = {}
    for r in store.get("records") or []:
        ref = (r.get("refs") or {}).get(SOURCE)
        for k in ((r.get("by_source") or {}).get(SOURCE) or {}).get("notices") or []:
            if ref:
                held.setdefault(k, ref)
    out, used = [], set()
    for u in rows:
        keys = [n["key"] for n in u.get("notices") or [] if n.get("key")]
        if not keys:
            continue
        ref = next((held[k] for k in keys if k in held and held[k] not in used), None)
        if ref is None:
            ref = next((k for k in keys if k not in used), None)
        if ref is None:
            continue
        used.add(ref)
        pad = (sites.get(u["site"]) or {}).get("pad") or [None, None]
        out.append({"id": ref, "name": f"Closure with no listed launch near {u['site']}", "net": u["start"],
                    "net_precision": PRECISION, "window_start": u["start"], "window_end": u["end"],
                    "location": u["site"], "lat": pad[1], "lon": pad[0], "notices": keys,
                    "maybe_listed": u.get("maybe_listed") or [], "expect_at": (u.get("expect") or {}).get("at")})
    return out


def _candidates(store: dict, rec: dict) -> list[dict]:
    w = (rec.get("by_source") or {}).get(SOURCE, {}).get("fields") or {}
    s, e = _dt(w.get("window_start")), _dt(w.get("window_end"))
    if not (s and e) or w.get("lat") is None or w.get("lon") is None:
        return []
    out = []
    for r in store.get("records") or []:
        if r is rec or SOURCE in (r.get("refs") or {}) or not _listing(r):
            continue
        if not any(b.get("listed") for b in (r.get("by_source") or {}).values()):
            continue
        if r.get("lat") is None or r.get("lon") is None or not _exact(r) or not _in_window(r, s, e):
            continue
        if notam.haversine_nm(r["lat"], r["lon"], w["lat"], w["lon"]) <= LISTED_NM:
            out.append(r)
    return sorted(out, key=lambda r: (abs((_dt(r.get("net")) - s).total_seconds()), r["id"]))


def apply(store: dict, rows: list[dict], sites: dict, read_at: str) -> dict:
    """This run's closure rows into the schedule store, in place (call only when the rows were judged against a
    schedule read: an empty list then marks every closure record no longer listed). Then each closure-only record
    with a listed launch in its window is joined to it. Returns the ingest report plus `joined`."""
    src = record_rows(rows, sites, store)
    rep = schedule.ingest(store, SOURCE, src, read_at, evidence=EVIDENCE)
    by_ref = {r["id"]: r for r in src}
    for rec in store["records"]:
        ref = (rec.get("refs") or {}).get(SOURCE)
        bs = (rec.get("by_source") or {}).get(SOURCE)
        if ref in by_ref and bs is not None and bs.get("last_seen") == read_at:
            row = by_ref[ref]
            bs["notices"] = sorted(set(bs.get("notices") or []) | set(row["notices"]))
            bs["maybe_listed"] = row["maybe_listed"]
            bs["expect_at"] = row["expect_at"]
    joined = []
    for rec in list(store["records"]):
        if set(rec.get("sources") or []) != {SOURCE} or rec not in store["records"]:
            continue
        cands = _candidates(store, rec)
        if cands:
            kept = schedule.join(store, rec["id"], cands[0]["id"], read_at, "listed launch in the closure window")
            joined.append({"kept": kept["id"], "closure": rec["id"], "listed": cands[0]["id"]})
    rep["joined"] = joined
    return rep
