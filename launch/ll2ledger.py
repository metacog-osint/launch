"""The launch ledger from Launch Library 2 (The Space Devs): every launch since START, verified and extended each run
(Ascent move, step 1, 19 Nov 2026: Orbit's `ledger` lane, orbit/ledger.py, taken over).

The plan of 15 Nov 2026 (from an earlier launch mapper): one request pulls PAGE launches in NET order from the last
saved launch's NET. The first of them is the last saved launch, which verifies it (its fields are refreshed and any
change is logged); the rest are new and are added. A launch saved before LL2 posted its outcome (Go, TBC, In
Flight) is looked up by id until it has a final status (the earliest such launch from the last OPEN_DAYS, one a
run). So a run makes one request and at most one more (a by-id lookup). On a 429 or any other error nothing is
changed and the next run tries again: no retries.

Launch's ledger starts from Orbit's (its last published file, read once when Launch holds none), so the rows from
1 Jan 2024 are not pulled again; from then on Launch pulls them itself. Rows keep Orbit's field names, so the two
can be compared row for row while both run (two days, decided 19 Nov 2026). The ledger is kept for good on Launch's
public release `ledger` (ll2-ledger.json), credited to The Space Devs; the change log is never cut. Its launches
that GCAT has not listed yet go into Launch's one ledger (data/ledger.json) as provisional records
(catalog.flown_from_ll2), which a GCAT launch joins once GCAT lists it.

Use (decided 15 Nov 2026): freely available ("the entire database is accessible to everyone, for free",
thespacedevs.com/llapi, read 16 Nov 2026), published with credit. Images are not kept.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from . import schedule

API = "https://ll.thespacedevs.com/2.3.0/launches/"
PREVIOUS = API + "previous/"
START = "2024-01-01T00:00:00Z"
PAGE = 14
SCHEMA = "launch-ll2-ledger/1"
ATTRIBUTION = schedule.ATTRIBUTION
RELEASE = "https://github.com/metacog-osint/launch/releases/download/ledger/"
ASSET = "ll2-ledger.json"
PUBLIC_URL = RELEASE + ASSET
ORBIT_LEDGER = "https://github.com/metacog-osint/orbit/releases/download/ledger/launch-ledger.json"
FINAL = ("Success", "Failure", "Partial Failure")
OPEN_DAYS = 14
COMPARED = ("name", "net", "net_precision", "window_start", "window_end", "status", "status_name", "provider",
            "vehicle", "mission", "mission_type", "orbit", "pad", "location", "pad_country")


def page_url(since: str, page: int = PAGE) -> str:
    return PREVIOUS + "?" + urlencode({"net__gte": since, "ordering": "net", "limit": page, "mode": "detailed"})


def id_url(launch_id: str) -> str:
    return API + f"{launch_id}/?" + urlencode({"mode": "detailed"})


def empty() -> dict:
    return {"schema": SCHEMA, "attribution": ATTRIBUTION, "start": START, "page": PAGE, "updated_at": None,
            "caught_up": False, "launches": [], "changes": [], "last_check": None, "seeded_from": None}


def seed(orbit_doc: dict, sha256: str, at: str) -> dict:
    """Launch's ledger begun from Orbit's published one (schema orbit-ledger/1, the same rows)."""
    if not isinstance(orbit_doc, dict) or not isinstance(orbit_doc.get("launches"), list):
        raise ValueError("Orbit's ledger has no launches list")
    doc = empty()
    doc["start"] = orbit_doc.get("start") or START
    doc["launches"] = sorted((dict(r) for r in orbit_doc["launches"] if r.get("id")), key=_key)
    doc["changes"] = [dict(c, source="orbit") for c in orbit_doc.get("changes") or []]
    doc["caught_up"] = bool(orbit_doc.get("caught_up"))
    doc["updated_at"] = orbit_doc.get("updated_at")
    doc["seeded_from"] = {"url": ORBIT_LEDGER, "sha256": sha256, "at": at, "rows": len(doc["launches"]),
                          "orbit_updated_at": orbit_doc.get("updated_at")}
    return doc


def _key(r: dict) -> tuple:
    return (r.get("net") or "", r.get("id") or "")


def _clean(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "mission_description"}


def parse_page(body: bytes) -> list[dict]:
    return [_clean(r) for r in schedule.ll2_parse(body)]


def parse_one(body: bytes) -> dict | None:
    doc = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(doc, dict) or not doc.get("id"):
        return None
    return _clean(schedule.ll2_row(doc))


def _net(r: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(r["net"].replace("Z", "+00:00"))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def open_launch(ledger: dict) -> dict | None:
    rows = ledger["launches"]
    if len(rows) < 2:
        return None
    last = max(rows, key=_key)
    newest = _net(last)
    if newest is None:
        return None
    open_ = [r for r in rows if r is not last and r.get("status") not in FINAL and _net(r) is not None
             and (newest - _net(r)).total_seconds() <= OPEN_DAYS * 86400]
    return min(open_, key=_key) if open_ else None


def _diff(old: dict, new: dict) -> dict:
    return {k: [old.get(k), new.get(k)] for k in COMPARED if old.get(k) != new.get(k)}


def step(ledger: dict, body: bytes, read_at: str, lookup=None) -> dict:
    """Apply one pull to `ledger` in place and return what it found (orbit/ledger.py's step, same rules).

    body: the reply to next_url(ledger). lookup(launch_id) -> bytes | None is the by-id reply (None: LL2 no longer
    has it), called at most once a step: for the newest saved launch when the pull doesn't hold it, otherwise for
    open_launch(). A reply with no results raises ValueError before anything changes."""
    rows = parse_page(body)
    for r in rows:
        r["read_at"] = read_at
    held = {r["id"]: i for i, r in enumerate(ledger["launches"])}
    last = max(ledger["launches"], key=_key) if ledger["launches"] else None
    report = {"read_at": read_at, "pulled": len(rows), "added": 0, "verified": None, "changed": {},
              "open_checked": None, "requests": 1}
    looked = False

    def refresh(old: dict, new: dict):
        d = _diff(old, new)
        if d:
            report["changed"][new["id"]] = d
        ledger["launches"][held[old["id"]]] = new

    if last is not None:
        here = next((r for r in rows if r["id"] == last["id"]), None)
        if here is not None:
            report["verified"] = "ok"
        elif lookup is not None:
            looked = True
            report["requests"] += 1
            raw = lookup(last["id"])
            here = parse_one(raw) if raw else None
            report["verified"] = "moved" if here is not None else "missing"
            if here is None:
                ledger["launches"][held[last["id"]]]["ll2_missing_since"] = read_at
            else:
                here["read_at"] = read_at
        else:
            report["verified"] = "not in pull"
        if here is not None:
            refresh(last, here)
    for r in rows:
        if r["id"] in held:
            if last is None or r["id"] != last["id"]:
                refresh(ledger["launches"][held[r["id"]]], r)
            continue
        ledger["launches"].append(r)
        held[r["id"]] = len(ledger["launches"]) - 1
        report["added"] += 1
    pulled = {r["id"] for r in rows}
    op = open_launch(ledger)
    if op is not None and op["id"] not in pulled and lookup is not None and not looked:
        report["requests"] += 1
        raw = lookup(op["id"])
        new = parse_one(raw) if raw else None
        if new is None:
            ledger["launches"][held[op["id"]]]["ll2_missing_since"] = read_at
        else:
            new["read_at"] = read_at
            refresh(op, new)
        report["open_checked"] = {"id": op["id"], "status": new.get("status") if new else None}
    ledger["launches"].sort(key=_key)
    for lid, d in report["changed"].items():
        ledger["changes"].append({"at": read_at, "id": lid, "fields": d})
    ledger["caught_up"] = len(rows) < PAGE
    ledger["updated_at"] = read_at
    ledger["last_check"] = report
    return report


def next_url(ledger: dict) -> str:
    if not ledger["launches"]:
        return page_url(ledger.get("start") or START)
    return page_url(max(ledger["launches"], key=_key)["net"])


def union(*docs: dict | None) -> dict | None:
    """Ledgers from the release, a local copy and older copies, as one: by id the row read last wins (rows from
    Orbit's seed have no read_at and give way to any of Launch's own reads); changes are the union. None when no
    ledger is given."""
    docs = [d for d in docs if d and isinstance(d.get("launches"), list)]
    if not docs:
        return None
    newest = max(docs, key=lambda d: d.get("updated_at") or "")
    out = {**empty(), **{k: v for k, v in newest.items() if k not in ("launches", "changes")}}
    rows: dict[str, dict] = {}
    seen, changes = set(), []
    for d in docs:
        for r in d["launches"]:
            old = rows.get(r.get("id"))
            if old is None or (r.get("read_at") or "", r.get("last_updated") or "") >= (
                    old.get("read_at") or "", old.get("last_updated") or ""):
                rows[r["id"]] = r
        for c in d.get("changes") or []:
            k = json.dumps(c, sort_keys=True)
            if k not in seen:
                seen.add(k)
                changes.append(c)
        if d.get("seeded_from") and not out.get("seeded_from"):
            out["seeded_from"] = d["seeded_from"]
    out["launches"] = sorted(rows.values(), key=_key)
    out["changes"] = sorted(changes, key=lambda c: (c.get("at") or "", c.get("id") or ""))
    return out


def after(ledger: dict, since_date: str) -> list[dict]:
    """Launches dated after `since_date` (YYYY-MM-DD), oldest first: what GCAT hasn't listed yet."""
    return [r for r in ledger.get("launches") or [] if (r.get("net") or "")[:10] > since_date]


def summary(ledger: dict) -> dict:
    rows = ledger.get("launches") or []
    return {"attribution": ATTRIBUTION, "url": PUBLIC_URL, "start": ledger.get("start"), "held": len(rows),
            "first_net": rows[0]["net"] if rows else None, "last_net": rows[-1]["net"] if rows else None,
            "caught_up": ledger.get("caught_up"), "updated_at": ledger.get("updated_at"),
            "last_check": ledger.get("last_check"), "changes_logged": len(ledger.get("changes") or []),
            "seeded_from": ledger.get("seeded_from")}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
