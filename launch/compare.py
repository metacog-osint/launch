"""Side-by-side check of Launch's new lanes against Orbit's (Ascent move, step 1; decided 19 Nov 2026: two days of both
before Orbit retires anything). Temporary: it goes when Orbit's lanes retire.

Each Launch run adds one row to data/ascent-compare.json (also on the release `ledger`):
  upcoming  Launch's scheduled launches (its own LL2 read) against Orbit's (`upcoming` in Orbit's snapshot): the LL2
            ids both list over the span both reads cover, the ids only one lists, and for ids both list a NET or
            status that differs. A difference where LL2's last_updated differs between the two reads is put down to
            the reads' times ("explained"); the rest are counted as unexplained.
  ledger    Launch's LL2 ledger against Orbit's ledger file (release `ledger` of Orbit): rows up to the older
            ledger's newest NET, ids only one holds, and compared fields that differ, explained the same way.
            `launch_own` counts the rows Launch has read itself (the rest still stand as seeded from Orbit).
The two days pass when no row has an unexplained difference and every launch either lists turns up in the other
by the next run.
"""
from __future__ import annotations

from datetime import datetime, timedelta

SCHEMA = "launch-ascent-compare/1"
HOW = ("Each Launch run compares its own Launch Library 2 schedule and ledger with Orbit's: the same scheduled "
       "launches over the span both reads cover, the same NETs and statuses, and the same ledger rows up to the older "
       "ledger's newest launch. A difference where LL2's own last_updated differs between the two reads is put down "
       "to the reads' times. Two days from the first row; Orbit's lanes retire only after that review.")
UPCOMING_FIELDS = ("net", "status")
LEDGER_FIELDS = ("name", "net", "status", "window_start", "window_end", "vehicle", "pad")
LIST_MAX = 25   # ids listed per bucket in a row (the counts are whole)


def _dt(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _diffs(a: dict, b: dict, fields, ids) -> tuple[list[dict], int]:
    out, unexplained = [], 0
    for i in sorted(ids):
        x, y = a[i], b[i]
        d = {k: [x.get(k), y.get(k)] for k in fields if x.get(k) != y.get(k)}
        if not d:
            continue
        explained = bool(x.get("last_updated") and y.get("last_updated") and x["last_updated"] != y["last_updated"])
        unexplained += not explained
        out.append({"id": i, "name": y.get("name") or x.get("name"), "fields": d, "explained": explained})
    return out, unexplained


def upcoming(orbit_rows: list[dict], orbit_read: str | None, launch_rows: list[dict], launch_read: str | None,
             horizon_days: int = 14) -> dict:
    """orbit_rows: Orbit's `upcoming` (LL2 rows); launch_rows: Launch's LL2 rows of the same read (refs.ll2 ids)."""
    ro, rl = _dt(orbit_read), _dt(launch_read)
    if ro is None or rl is None:
        return {"status": "no read", "orbit_read": orbit_read, "launch_read": launch_read}
    lo, hi = max(ro, rl), min(ro, rl) + timedelta(days=horizon_days)

    def span(rows):
        out = {}
        for r in rows:
            net, end = _dt(r.get("net")), _dt(r.get("window_end")) or _dt(r.get("net"))
            if r.get("id") and net is not None and net <= hi and (end or net) >= lo:
                out[r["id"]] = r
        return out
    o, l = span(orbit_rows), span(launch_rows)
    both = set(o) & set(l)
    diff, unexplained = _diffs(o, l, UPCOMING_FIELDS, both)
    only_o, only_l = sorted(set(o) - set(l)), sorted(set(l) - set(o))
    return {"status": "compared", "orbit_read": orbit_read, "launch_read": launch_read,
            "span": [lo.strftime("%Y-%m-%dT%H:%M:%SZ"), hi.strftime("%Y-%m-%dT%H:%M:%SZ")],
            "orbit": len(o), "launch": len(l), "both": len(both),
            "only_orbit": [{"id": i, "name": o[i].get("name"), "net": o[i].get("net")} for i in only_o][:LIST_MAX],
            "only_launch": [{"id": i, "name": l[i].get("name"), "net": l[i].get("net")} for i in only_l][:LIST_MAX],
            "n_only_orbit": len(only_o), "n_only_launch": len(only_l),
            "differ": diff[:LIST_MAX], "n_differ": len(diff), "unexplained": unexplained}


def ledger(orbit_doc: dict | None, launch_doc: dict | None) -> dict:
    if not orbit_doc or not launch_doc:
        return {"status": "no ledger", "orbit": bool(orbit_doc), "launch": bool(launch_doc)}
    o = {r["id"]: r for r in orbit_doc.get("launches") or [] if r.get("id")}
    l = {r["id"]: r for r in launch_doc.get("launches") or [] if r.get("id")}
    to = min(max((r.get("net") or "" for r in o.values()), default=""),
             max((r.get("net") or "" for r in l.values()), default=""))
    o = {i: r for i, r in o.items() if (r.get("net") or "") <= to}
    l = {i: r for i, r in l.items() if (r.get("net") or "") <= to}
    both = set(o) & set(l)
    diff, unexplained = _diffs(o, l, LEDGER_FIELDS, both)
    only_o, only_l = sorted(set(o) - set(l)), sorted(set(l) - set(o))
    return {"status": "compared", "to": to, "orbit_updated_at": orbit_doc.get("updated_at"),
            "launch_updated_at": launch_doc.get("updated_at"), "orbit": len(o), "launch": len(l), "both": len(both),
            "launch_own": sum(1 for r in l.values() if r.get("read_at")),
            "only_orbit": only_o[:LIST_MAX], "only_launch": only_l[:LIST_MAX],
            "n_only_orbit": len(only_o), "n_only_launch": len(only_l),
            "differ": diff[:LIST_MAX], "n_differ": len(diff), "unexplained": unexplained}


def row(at: str, up: dict, led: dict) -> dict:
    bad = sum(x.get("unexplained") or 0 for x in (up, led))
    gaps = sum((x.get("n_only_orbit") or 0) + (x.get("n_only_launch") or 0) for x in (up, led))
    verdict = ("not compared" if up.get("status") != "compared" or led.get("status") != "compared"
               else "differs" if bad else "listed by one only" if gaps
               else "same but for read times" if up.get("n_differ") or led.get("n_differ") else "same")
    return {"at": at, "verdict": verdict, "upcoming": up, "ledger": led}


def empty() -> dict:
    return {"schema": SCHEMA, "how": HOW, "started_at": None, "runs": []}


def union(*docs: dict | None) -> dict:
    out = empty()
    runs = {}
    for d in docs:
        if not d:
            continue
        for r in d.get("runs") or []:
            runs.setdefault(r.get("at"), r)
    out["runs"] = sorted(runs.values(), key=lambda r: r.get("at") or "")
    out["started_at"] = out["runs"][0]["at"] if out["runs"] else None
    return out
