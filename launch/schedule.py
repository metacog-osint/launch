"""Scheduled launches: one multi-source record per expected launch (Ascent move, step 1, 19 Nov 2026).

Launch Library 2 (The Space Devs) is the first source, read here directly: the `schedule` lane makes one LL2
upcoming request a run (Orbit's `upcoming` lane, taken over; Orbit reads LL2 too until it retires its lanes, and
the two together stay inside LL2's 15 requests an hour without a key). Decided 19 Nov 2026: the schedule is
multi-source. Other sources (a closure with no listed launch, evacuation and drop-zone notices, press and channel
posts) are added one at a time, so nothing here is keyed to LL2.

The record (`store["records"]`, one per expected launch):
  id        "upcoming:<first source>:<its id>", e.g. "upcoming:ll2:<LL2 uuid>". Set once and never changed: a record a
            later source joins keeps its id, and when two records are found to be one launch the one seen first
            keeps its id and the other's id is kept in its `aliases` (and in `store["aliases"]`, so an old address
            still finds it).
  sources   the sources that hold it, first first; `refs` their own ids ({"ll2": uuid}); `evidence` the kinds
            named on the page: "listed" (a schedule lists it). None is a forecast.
  fields    name, net, window, status, provider, vehicle, mission, orbit, pad, place: from the first source in
            PRECEDENCE that holds the record.
  by_source per source: first_seen, last_seen, listed (still in that source's latest read), unlisted_at, the
            source's own last_updated, and its link.
  changes   every change of a compared field, with the time read and the source (kept for good, never cut).

The store keeps every record ever made (never-lose-data rule, 18 Nov 2026); `active()` is the live view. A scheduled
launch is reported, not measured.

Standard-library Python only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

SCHEMA = "launch-upcoming/1"
LL2_API = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"
HORIZON_DAYS = 14
ATTRIBUTION = "Launch data: Launch Library 2, The Space Devs (thespacedevs.com)"
PRECEDENCE = ("ll2",)        # whose fields a record shows, first first; later sources are added here
NET_MOVES_SHOWN = 3   # NET moves kept on each public record (the count is net_changes)
FIELDS = ("name", "net", "net_precision", "window_start", "window_end", "status", "status_name", "provider",
          "provider_type", "provider_countries", "vehicle", "mission", "mission_type", "orbit", "orbit_name", "pad",
          "location", "pad_country", "lat", "lon")
COMPARED = ("name", "net", "net_precision", "window_start", "window_end", "status", "provider", "vehicle", "mission",
            "orbit", "pad", "location")


# ---------- Launch Library 2 ----------

def ll2_url(now: datetime, days: int = HORIZON_DAYS) -> str:
    """Detailed mode, because only it carries the provider's country (Orbit's reading, 13 Nov 2026)."""
    until = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return LL2_API + "?" + urlencode({"limit": 100, "mode": "detailed", "net__lte": until})


def _get(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return d if d is not None else default


def ll2_row(r: dict) -> dict:
    """One LL2 launch in Orbit's field names (orbit/launches.py), so the two can be compared row for row. No images
    (each carries its own licence); the mission text is cut to 600 characters."""
    pad = r.get("pad") or {}
    try:
        lat, lon = float(pad.get("latitude")), float(pad.get("longitude"))
    except (TypeError, ValueError):
        lat = lon = None
    countries = [c.get("alpha_2_code") for c in _get(r, "launch_service_provider", "country", default=[])
                 if isinstance(c, dict) and c.get("alpha_2_code")]
    return {
        "id": r.get("id"), "name": r.get("name", ""), "net": r.get("net"),
        "net_precision": _get(r, "net_precision", "name", default=""),
        "window_start": r.get("window_start"), "window_end": r.get("window_end"),
        "status": _get(r, "status", "abbrev", default=""), "status_name": _get(r, "status", "name", default=""),
        "last_updated": r.get("last_updated"),
        "provider": _get(r, "launch_service_provider", "name", default=""),
        "provider_type": _get(r, "launch_service_provider", "type", "name", default=""),
        "provider_countries": countries,
        "vehicle": _get(r, "rocket", "configuration", "full_name", default="")
                   or _get(r, "rocket", "configuration", "name", default=""),
        "mission": _get(r, "mission", "name", default=""), "mission_type": _get(r, "mission", "type", default=""),
        "mission_description": (_get(r, "mission", "description", default="") or "").replace("\r\n", "\n")[:600],
        "orbit": _get(r, "mission", "orbit", "abbrev", default=""),
        "orbit_name": _get(r, "mission", "orbit", "name", default=""),
        "pad": pad.get("name", ""), "location": _get(pad, "location", "name", default=""),
        "pad_country": _get(pad, "location", "country", "alpha_2_code", default=None)
                       or _get(pad, "country", "alpha_2_code", default=None),
        "lat": lat, "lon": lon, "ll2_url": r.get("url"),
    }


def ll2_parse(body: bytes) -> list[dict]:
    doc = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise ValueError(f"Launch Library 2 reply has no results: {str(doc)[:200]}")
    out = [ll2_row(r) for r in doc["results"] if isinstance(r, dict) and r.get("id")]
    out.sort(key=lambda x: (x["net"] or "", x["name"]))
    return out


def _dt(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def within(rows: list[dict], now: datetime, days: int = HORIZON_DAYS) -> list[dict]:
    """Launches whose window has not closed and whose NET is within `days` days of now (Orbit's rule)."""
    until, keep = now + timedelta(days=days), []
    for x in rows:
        net = _dt(x.get("net"))
        if net is None:
            continue
        end = _dt(x.get("window_end")) or net
        if end >= now and net <= until:
            keep.append(x)
    return keep


# ---------- the multi-source store ----------

def empty() -> dict:
    return {"schema": SCHEMA, "attribution": ATTRIBUTION, "records": [], "aliases": {}, "reads": {},
            "updated_at": None}


def record_id(source: str, ref: str) -> str:
    return f"upcoming:{source}:{ref}"


def _index(store: dict) -> dict[tuple[str, str], dict]:
    return {(s, ref): r for r in store["records"] for s, ref in (r.get("refs") or {}).items()}


def _fields_from(r: dict) -> None:
    """Set a record's shown fields from the first source in PRECEDENCE that holds it."""
    for s in list(PRECEDENCE) + [s for s in r["sources"] if s not in PRECEDENCE]:
        reading = (r.get("by_source") or {}).get(s, {}).get("fields")
        if reading:
            r.update({k: reading.get(k) for k in FIELDS})
            return


def _new(source: str, ref: str, read_at: str, evidence: str) -> dict:
    return {"id": record_id(source, ref), "sources": [source], "refs": {source: ref}, "evidence": [evidence],
            "aliases": [], "first_seen": read_at, "updated": read_at, "by_source": {}, "changes": [],
            **{k: None for k in FIELDS}}


def ingest(store: dict, source: str, rows: list[dict], read_at: str, evidence: str = "listed",
           link_key: str | None = None) -> dict:
    """Apply one source's read (its whole current listing) to the store, in place. rows: dicts with "id" (the
    source's own id) and FIELDS. A record the source no longer lists is kept and marked (listed false,
    unlisted_at). Returns {"read": n, "new": [...ids], "changed": {...}, "unlisted": [...ids]}."""
    idx = _index(store)
    rep = {"read": len(rows), "new": [], "changed": {}, "unlisted": [], "relisted": []}
    seen = set()
    for row in rows:
        ref = row.get("id")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        rec = idx.get((source, ref))
        if rec is None:
            rec = _new(source, ref, read_at, evidence)
            store["records"].append(rec)
            idx[(source, ref)] = rec
            rep["new"].append(rec["id"])
        bs = rec["by_source"].setdefault(source, {"first_seen": read_at})
        old = bs.get("fields") or {}
        fields = {k: row.get(k) for k in FIELDS}
        diff = {k: [old.get(k), fields.get(k)] for k in COMPARED if old and old.get(k) != fields.get(k)}
        if diff:
            rec["changes"].append({"at": read_at, "source": source, "fields": diff})
            rep["changed"][rec["id"]] = diff
        if bs.get("listed") is False:
            rep["relisted"].append(rec["id"])
            bs.pop("unlisted_at", None)
        bs.update({"last_seen": read_at, "listed": True, "fields": fields,
                   "last_updated": row.get("last_updated"), "link": row.get(link_key) if link_key else None})
        if source not in rec["sources"]:
            rec["sources"].append(source)
        if evidence not in rec["evidence"]:
            rec["evidence"].append(evidence)
        rec["updated"] = read_at
        _fields_from(rec)
    for (s, ref), rec in idx.items():
        bs = rec["by_source"].get(s) or {}
        if s == source and ref not in seen and bs.get("listed"):
            bs.update({"listed": False, "unlisted_at": read_at})
            rec["updated"] = read_at
            rep["unlisted"].append(rec["id"])
    store["reads"][source] = read_at
    store["updated_at"] = read_at
    return rep


def join(store: dict, keep_id: str, other_id: str, at: str, basis: str) -> dict:
    """Two records are one launch: the one seen first keeps its id, the other's sources, refs, readings and
    changes move into it, and the other's id becomes an alias. `basis` says why (kept in `joins`)."""
    by_id = {r["id"]: r for r in store["records"]}
    a, b = by_id[keep_id], by_id[other_id]
    if (b.get("first_seen") or "") < (a.get("first_seen") or ""):
        a, b = b, a
    for s in b["sources"]:
        if s not in a["sources"]:
            a["sources"].append(s)
    a["refs"] = {**b["refs"], **a["refs"]}
    a["by_source"] = {**b["by_source"], **a["by_source"]}
    a["evidence"] += [e for e in b["evidence"] if e not in a["evidence"]]
    a["changes"] = sorted(a["changes"] + b["changes"], key=lambda c: c["at"])
    a["aliases"] = sorted(set(a.get("aliases") or []) | set(b.get("aliases") or []) | {b["id"]})
    a.setdefault("joins", []).append({"at": at, "joined": b["id"], "basis": basis})
    a["updated"] = at
    store["records"] = [r for r in store["records"] if r is not b]
    for alias in a["aliases"]:
        store["aliases"][alias] = a["id"]
    for k, v in list(store["aliases"].items()):
        if v == b["id"]:
            store["aliases"][k] = a["id"]
    _fields_from(a)
    return a


def resolve(store: dict, rid: str) -> dict | None:
    """The record for an id or an alias of it."""
    rid = (store.get("aliases") or {}).get(rid, rid)
    return next((r for r in store["records"] if r["id"] == rid), None)


def union(*stores: dict | None) -> dict:
    """Stores from the release, a local copy and older copies, as one: by id the record updated last wins, its
    changes are the union of both; two records that hold the same source id are joined (seen first keeps its id)."""
    out = empty()
    recs: dict[str, dict] = {}
    for st in stores:
        if not st:
            continue
        out["aliases"].update(st.get("aliases") or {})
        for s, t in (st.get("reads") or {}).items():
            out["reads"][s] = max(out["reads"].get(s) or "", t or "")
        out["updated_at"] = max(out["updated_at"] or "", st.get("updated_at") or "") or None
        for r in st.get("records") or []:
            old = recs.get(r["id"])
            if old is None:
                recs[r["id"]] = json.loads(json.dumps(r))
                continue
            new, base = (r, old) if (r.get("updated") or "") >= (old.get("updated") or "") else (old, r)
            seen, changes = set(), []
            for c in (base.get("changes") or []) + (new.get("changes") or []):
                k = json.dumps(c, sort_keys=True)
                if k not in seen:
                    seen.add(k)
                    changes.append(c)
            merged = json.loads(json.dumps(new))
            merged["changes"] = sorted(changes, key=lambda c: c["at"])
            merged["first_seen"] = min(base.get("first_seen") or "~", new.get("first_seen") or "~")
            merged["aliases"] = sorted(set(base.get("aliases") or []) | set(new.get("aliases") or []))
            recs[r["id"]] = merged
    out["records"] = list(recs.values())
    at = out["updated_at"] or ""
    # An id another record has taken as an alias is that record now (one copy predates the join).
    for alias, kept in list(out["aliases"].items()):
        ids = {r["id"] for r in out["records"]}
        if alias != kept and alias in ids and kept in ids:
            join(out, kept, alias, at, "alias")
    # Two records holding one source id are one launch.
    while True:
        seen_ref, pair = {}, None
        for r in sorted(out["records"], key=lambda r: (r.get("first_seen") or "", r["id"])):
            for s, ref in (r.get("refs") or {}).items():
                if (s, ref) in seen_ref:
                    pair = (seen_ref[(s, ref)], r["id"], s)
                    break
                seen_ref[(s, ref)] = r["id"]
            if pair:
                break
        if not pair:
            break
        join(out, pair[0], pair[1], at, f"same {pair[2]} id")
    out["records"].sort(key=lambda r: (r.get("net") or "", r["id"]))
    return out


def active(store: dict, now: datetime, days: int = HORIZON_DAYS) -> list[dict]:
    """The live view: records a source still lists whose window has not closed and whose NET is within `days`."""
    keep = [r for r in store.get("records") or []
            if any(b.get("listed") for b in (r.get("by_source") or {}).values())]
    return [_public(r) for r in within(keep, now, days)]


def _public(r: dict) -> dict:
    """A record as the site and readers get it: shown fields, sources and links, no per-source copies."""
    out = {k: r.get(k) for k in ("id", "sources", "refs", "evidence", "first_seen", "updated", *FIELDS)}
    out["links"] = {s: b.get("link") for s, b in (r.get("by_source") or {}).items() if b.get("link")}
    moves = sorted((c for c in r.get("changes") or [] if len((c.get("fields") or {}).get("net") or []) == 2),
                   key=lambda c: c.get("at") or "")
    out["net_changes"] = len(moves)
    # The latest NET moves, for the Live tab's board ("moved 2 times; last 1 day later").
    out["net_moves"] = [{"at": c.get("at"), "from": c["fields"]["net"][0], "to": c["fields"]["net"][1]}
                        for c in moves[-NET_MOVES_SHOWN:]]
    if r.get("aliases"):
        out["aliases"] = r["aliases"]
    return out


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
