"""Launch CLI.

    python tools/launch.py history [KML]   # the charted notices -> history/history.json and history/patterns.json
    python tools/launch.py backfill DIR    # GCAT tables in DIR -> history/ledger.json (every launch since 2012)
    python tools/launch.py collect         # live lanes -> data/snapshot.json; new launches -> data/ledger.json;
                                           # schedule, LL2 ledger, comparison -> data/*.json for the release
    python tools/launch.py build           # site/ from history/ and data/snapshot.json
    python tools/launch.py check           # registers + feed lint + public gate + privacy check

collect never makes data up. A failed lane keeps its last good copy (from_previous) or stays empty, and the
snapshot's "lanes" block says which.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from launch import (catalog, compare, feed, fetch, gcat, gnss, history, incbias, joey, live, ll2ledger, news, nfc, nms,  # noqa: E402
                    nsf, overfly, patterns, privacy, public, schedule, timing, unlisted, wayback)
from tic_doctrine import contract, registers  # noqa: E402

DEFAULT_KML = ROOT / "history" / "source" / "launch-map-2026-11-13.kml"
# Not imported: the exercise layer holds scenario text, not public notices.
EXCLUDED_LAYERS = {"Previous Exercise NOTAMs"}
LANE_FIELDS = {"tfr": ["tfr"], "orbit": ["orbit"], "cordon": ["cordon"], "nms": ["nms"], "schedule": ["schedule"],
               "news": ["news"]}
# The published ledger, read back on each run so a lost Actions cache loses no launch (merge is a union).
LIVE_LEDGER = "https://launch.theintelligence.company/data/ledger.json"
EMPTY = {"tfr": [], "orbit": {}, "cordon": {}, "nms": {}, "schedule": {}, "news": {}}
# The Ascent move's stores (19 Nov 2026), kept for good on this repository's public release `ledger`: the workflow
# uploads them after each collect, and collect reads them back from there (a local copy, when there is one, too).
STORE = {"upcoming": "upcoming-store.json", "ll2": ll2ledger.ASSET, "compare": "ascent-compare.json"}
# The launch ledger and the NMS closure ledger are on the release too (ideas#222, 24 Nov 2026): before that they
# lived only on the deployed site and in the Actions cache. The release copy is a third source in their union, so
# a site that answers 404 or an emptied cache restores from it, not from empty. data/ledger.json is uploaded as
# launch-ledger.json beside ll2-ledger.json; dated copies go to release `ledger-YYYY-qN` (kept for good).
RELEASE_COPY = {"ledger": "launch-ledger.json", "closures": "nms-closures.json"}


def dump(obj, compact: bool = False) -> str:
    if compact:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def build_history(kml: Path, root: Path = ROOT) -> dict:
    """history/history.json is published as it is written here, so only what public.py clears goes into it:
    the Launch Sites on history/public_sites.json, without the map's notes on them."""
    history.load_terms(kml.parent / "terms.json")  # private, git-ignored: refuses without it
    doc = history.load(kml.read_bytes())
    events = [e for e in doc["events"] if e["layer"] not in EXCLUDED_LAYERS]
    events.sort(key=lambda e: e["time"] or "0000")
    hdir = root / "history"
    hdir.mkdir(exist_ok=True)
    allow = public.allowlist(hdir / "public_sites.json")
    sites, gate = public.sites(doc["sites"], allow)
    out = {"source": kml.name, "imported_from": "Launch's charted notices (Google My Maps export)",
           "excluded_layers": sorted(EXCLUDED_LAYERS), "sites_rule": public.RULE, "sites": sites, "events": events}
    pat = patterns.build(events, sites)
    errs = public.problems(out, pat, allow)
    if errs:  # nothing is written that the check would refuse
        raise SystemExit("History not written, the public check failed:\n  - " + "\n  - ".join(errs))
    (hdir / "history.json").write_text(dump(out, compact=True), encoding="utf-8", newline="\n")
    (hdir / "patterns.json").write_text(dump(pat, compact=True), encoding="utf-8", newline="\n")
    held = dict(gate["withheld"])
    if doc["withheld"]["sites"]:
        held["the note names a restricted source"] = doc["withheld"]["sites"]
    shapes: dict[str, int] = {}
    for layer, counts in doc["withheld"]["shapes"].items():
        if layer not in EXCLUDED_LAYERS:
            for what, n in counts.items():
                shapes[what] = shapes.get(what, 0) + n
    kept = {layer: n for layer, n in doc["withheld"]["ships"].items() if layer not in EXCLUDED_LAYERS}
    gone = {layer: n for layer, n in doc["withheld"]["empty_events"].items() if layer not in EXCLUDED_LAYERS}
    return {"events": len(events), "areas": sum(len(e["areas"]) for e in events), "sites": len(sites),
            "recurring": len(pat["recurring"]), "pads": len(pat["corridors"]),
            "sites_on_map": len(doc["sites"]) + doc["withheld"]["sites"], "site_kinds": gate["kinds"],
            "site_notes": gate["notes"], "sites_withheld": held, "sites_not_listed": gate["not_listed"],
            "shapes_withheld": shapes,
            "events_withheld": {"named as a ship": sum(kept.values()),
                                "no date, no notice and no shape left": sum(gone.values())}}


def build_backfill(gdir: Path, root: Path = ROOT) -> dict:
    """Every launch GCAT lists since catalog.LEDGER_SINCE (orbital, suborbital and missiles: programs.GCAT_KIND),
    from GCAT's own tables -> history/ledger.json."""
    t = gcat.read_dir(gdir)
    rows = {k: gcat.parse_tsv(v) for k, v in t.items()}
    sites = gcat.sites_table(rows["sites"])
    orgs = gcat.orgs_table(rows["orgs"])
    now = fetch.now_utc()
    stamp = {k: next((ln[len("# Updated"):].strip() for ln in v[:2000].decode("utf-8", "replace").splitlines()[1:3]
                      if ln.startswith("# Updated")), None) for k, v in t.items()}
    # Each record is as of the satellite catalog's date, not today's run, so a later reading in Orbit's snapshot
    # (more payloads catalogued since) wins the merge field by field.
    as_of = min((x for x in (gcat.vague_date(stamp.get(k) or "")["time"] for k in ("launch", "satcat")) if x),
                default=now)
    launches = catalog.from_gcat_tables(rows["launch"], rows["satcat"] + rows["satcat100k"], sites, orgs, as_of)
    # Sites: every site with a launch of any kind since the ledger starts or 2015, whichever is earlier (missile
    # ranges too, for the charted notices' tests).
    floor = min(catalog.LEDGER_SINCE, "2015")
    used = {(r.get("Launch_Site") or "").rstrip("?") for r in rows["launch"]
            if (gcat.vague_date(r.get("Launch_Date", ""))["date"] or "") >= floor}
    doc = {"version": 1, "since": catalog.LEDGER_SINCE, "built_from": "GCAT tables " + ", ".join(gcat.TABLES),
           "gcat_updated": stamp, "citation": gcat.CITATION, "generated_at": now, "launches": launches, "closures": [],
           "sites": catalog.site_table(sites, used)}
    (root / "history" / "ledger.json").write_text(dump(doc, compact=True), encoding="utf-8", newline="\n")
    return {"launches": len(launches), "sites": len(doc["sites"]), "gcat_updated": stamp.get("launch")}


def _sites_from_orbit(launches: list[dict]) -> dict:
    out = {}
    for g in launches or []:
        s, code = g.get("site") or {}, g.get("site_code")
        if code and s.get("lat") is not None:
            out[code] = {"name": catalog.P.site_name(s.get("name")) or code,
                         "gcat_name": s.get("full_name") or s.get("name"),
                         "lat": s["lat"], "lon": s["lon"], "country": s.get("country")}
    return out


def update_ledger(snap: dict, areas: list[dict], data_dir: Path, root: Path, getter=None,
                  ll2_led: dict | None = None) -> dict:
    """Baseline (committed) + last run's ledger (Actions cache) + the published copy + this run's launches. The LL2
    ledger's launches since GCAT's newest launch go in as provisional records (catalog.flown_from_ll2), which a GCAT
    launch joins once GCAT lists it."""
    def read(p: Path):
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None
    base, prev = read(root / "history" / "ledger.json"), read(data_dir / "ledger.json")
    status = {"status": "ok", "fetched_at": snap["generated_at"]}
    published = None
    try:
        body, _ = fetch.fetch("launch-ledger", LIVE_LEDGER, data_dir / "raw", "json", getter=getter)
        published = json.loads(body)
    except Exception as exc:  # the published copy is a safety net; the cache and the baseline still hold
        status = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:200], "failed_at": snap["generated_at"]}
    released, _ = release_copy(RELEASE_COPY["ledger"], data_dir, getter)   # the durable copy (ideas#222)
    orb = snap.get("orbit") or {}
    now = snap["generated_at"]
    gcat_now = catalog.from_orbit(orb.get("launches") or [], now)
    gcat_last = max((r.get("date") or "" for lg in (base, prev, published, {"launches": gcat_now}) if lg
                     for r in lg.get("launches") or [] if r.get("source") == "gcat"), default="")
    since_gcat = ll2ledger.after(ll2_led, gcat_last) if ll2_led and gcat_last else []
    fresh = {"launches": gcat_now + catalog.flown_from_ll2(orb.get("upcoming") or [], now)
             + catalog.flown_from_ll2(since_gcat, now),
             "closures": catalog.closures_from_matches(snap.get("matches") or [], areas, now),
             "sites": _sites_from_orbit(orb.get("launches") or [])}
    before = len({r["id"] for lg in (base, prev, published, released) if lg for r in lg.get("launches") or []})
    led = catalog.merge(base, published, released, prev, fresh)
    led["generated_at"] = now
    (data_dir / "ledger.json").write_text(dump(led, compact=True), encoding="utf-8", newline="\n")
    status.update({"records": len(led["launches"]), "added": len(led["launches"]) - before,
                   "base": len((base or {}).get("launches") or []), "cache": prev is not None,
                   "published": published is not None, "release": released is not None,
                   "gcat_last": gcat_last or None,
                   "ll2_since_gcat": len(since_gcat)})
    return status


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        return None


def load_store(name: str, data_dir: Path, getter=None, must: bool = True) -> tuple[dict | None, dict | None]:
    """(local copy, release copy) of one of the Ascent stores. The release copy is the durable one. With no local
    copy and the release unreadable (anything but a 404, which is a first run) a `must` store stops the run, so a
    smaller store is never written over the release's."""
    local = _read_json(data_dir / name)
    try:
        body, _ = fetch.fetch("launch-release", ll2ledger.RELEASE + name, data_dir / "raw", "json", getter=getter,
                              gz=True)
        return local, json.loads(body)
    except Exception as exc:  # noqa: BLE001
        if must and local is None and getattr(exc, "code", None) != 404:
            raise RuntimeError(f"{name}: no local copy and the release copy is unreadable "
                               f"({type(exc).__name__}: {exc}); not writing a smaller store") from exc
        return local, None


def release_copy(name: str, data_dir: Path, getter=None) -> tuple[dict | None, Exception | None]:
    """(the release copy of `name`, or None; the error when it could not be read). A 404 is no copy yet."""
    try:
        body, _ = fetch.fetch("launch-release", ll2ledger.RELEASE + name, data_dir / "raw", "json", getter=getter,
                              gz=True)
        doc = gnss.published_json(body)
        return doc, None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def _write(p: Path, doc) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump(doc, compact=True), encoding="utf-8", newline="\n")


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def update_schedule(snap: dict, data_dir: Path, now: datetime, getter=None) -> dict:
    """The multi-source upcoming store (launch/schedule.py): this run's LL2 read, when the schedule lane read it,
    applied to the store; the live view and each record's headlines go into the snapshot."""
    local, rel = load_store(STORE["upcoming"], data_dir, getter)
    store = schedule.union(rel, local)
    sch, lane = snap.get("schedule") or {}, snap["lanes"].get("schedule") or {}
    if lane.get("status") == "ok" and isinstance(sch.get("rows"), list):
        rep = schedule.ingest(store, "ll2", sch["rows"], sch["read_at"], link_key="ll2_url")
        lane["ingest"] = {k: len(v) if isinstance(v, (list, dict)) else v for k, v in rep.items()}
    _write(data_dir / STORE["upcoming"], store)
    _schedule_view(snap, store, now)
    return store


def _schedule_view(snap: dict, store: dict, now: datetime) -> None:
    records = schedule.active(store, now)
    heads = news.for_records(snap.get("news") or {}, records)
    for r in records:
        r["news"] = heads.get(r["id"], [])
    snap["schedule"] = {"read_at": (store.get("reads") or {}).get("ll2"), "attribution": schedule.ATTRIBUTION,
                        "held": len(store["records"]), "records": records}


def update_closure_records(snap: dict, store: dict, sites: dict, data_dir: Path, now: datetime) -> None:
    """Ascent step 1b: this run's closures with no listing as `closure` records in the upcoming store, joined to a
    listed launch once one is listed in the window (launch/unlisted.py apply()). Never fails the run."""
    lane = snap["lanes"].setdefault("schedule", {})
    try:
        rep = unlisted.apply(store, snap.get("unlisted") or [], sites, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    except Exception as exc:  # noqa: BLE001
        lane["closure_records"] = {"status": "failed", "error": _err(exc)}
        return
    lane["closure_records"] = {k: len(v) if isinstance(v, (list, dict)) else v for k, v in rep.items()}
    _write(data_dir / STORE["upcoming"], store)
    _schedule_view(snap, store, now)


def update_ll2_ledger(data_dir: Path, getter=None) -> tuple[dict | None, dict | None, dict]:
    """One verify-and-extend pull of the LL2 ledger (launch/ll2ledger.py): one request and at most one by-id
    lookup. Begun from Orbit's published ledger when Launch holds none. A failed pull changes nothing and is not
    retried. Returns (ledger, Orbit's ledger for the comparison, lane status)."""
    import copy
    import urllib.error
    get = getter or fetch.get
    raw = data_dir / "raw"
    local, rel = load_store(STORE["ll2"], data_dir, getter)
    led = ll2ledger.union(rel, local)
    status = {"status": "ok", "from_release": rel is not None, "local": local is not None}
    orbit_doc, orbit_sha = None, None
    try:
        body, rec = fetch.fetch("orbit-ledger", ll2ledger.ORBIT_LEDGER, raw, "json", getter=getter, gz=True)
        orbit_doc, orbit_sha = json.loads(body), rec["sha256"]
    except Exception as exc:  # noqa: BLE001  (only the seed and the comparison need it)
        status["orbit_ledger_error"] = _err(exc)
    if led is None:
        if orbit_doc is None:
            status.update({"status": "failed", "error": "no ledger held and Orbit's unreadable: not starting over "
                                                          "from 1 Jan 2024; the next run tries again"})
            return None, None, status
        led = ll2ledger.seed(orbit_doc, orbit_sha, fetch.now_utc())
        status["seeded"] = led["seeded_from"]

    def lookup(launch_id):
        try:
            return get(ll2ledger.id_url(launch_id), 120)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    work = copy.deepcopy(led)
    try:
        body, _ = fetch.fetch("ll2-previous", ll2ledger.next_url(work), raw, "json", getter=get, gz=True)
        status["check"] = ll2ledger.step(work, body, fetch.now_utc(), lookup)
        led = work
    except Exception as exc:  # noqa: BLE001  a 429 included: nothing changes, the next run tries again
        status.update({"status": "failed", "error": "Launch Library 2 pull: " + _err(exc) + "; ledger unchanged"})
    _write(data_dir / STORE["ll2"], led)
    status["summary"] = ll2ledger.summary(led)
    return led, orbit_doc, status


def update_compare(snap: dict, store: dict, led: dict | None, orbit_doc: dict | None, data_dir: Path,
                   getter=None) -> dict:
    """One row of the side-by-side check with Orbit (launch/compare.py), kept with the earlier rows."""
    local, rel = load_store(STORE["compare"], data_dir, getter, must=False)
    doc = compare.union(rel, local)
    orb = snap.get("orbit") or {}
    mine = [{**(r["by_source"]["ll2"].get("fields") or {}), "id": r["refs"]["ll2"],
             "last_updated": r["by_source"]["ll2"].get("last_updated")}
            for r in store.get("records") or [] if (r.get("refs") or {}).get("ll2")
            and (r.get("by_source") or {}).get("ll2", {}).get("listed")]
    up = compare.upcoming(orb.get("upcoming") or [], orb.get("upcoming_read_at"), mine,
                          (store.get("reads") or {}).get("ll2"))
    row = compare.row(snap["generated_at"], up, compare.ledger(orbit_doc, led))
    doc = compare.union(doc, {"runs": [row]})
    _write(data_dir / STORE["compare"], doc)
    return {"status": "ok", "verdict": row["verdict"], "runs": len(doc["runs"]), "started_at": doc["started_at"]}


def update_nms_ledger(snap: dict, data_dir: Path, getter=None) -> dict:
    """Every NMS closure notice ever kept (launch/nms.py ledger()): the cache's copy, the published copy and this
    run's notices (only when the nms lane succeeded), a union. With no cached copy and the published one unreadable
    (anything but a 404, which is a first run), the run stops: publishing now would publish less than the site
    holds, and a later run tries again."""
    path = data_dir / "nms-closures.json"
    try:
        prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except ValueError:
        prev = None
    published, status, pub_exc = None, {"status": "ok"}, None
    try:
        body, _ = fetch.fetch("launch-nms-closures", nms.LEDGER_URL, data_dir / "raw", "json", getter=getter)
        published = gnss.published_json(body)   # Pages' 200 HTML fallback for an undeployed path = not published
    except Exception as exc:  # noqa: BLE001
        pub_exc = exc
    released, rel_exc = release_copy(RELEASE_COPY["closures"], data_dir, getter)   # the durable copy (ideas#222)
    unreadable = [e for e in (pub_exc, rel_exc) if e is not None and getattr(e, "code", None) != 404]
    if prev is None and published is None and released is None and unreadable:
        e = unreadable[0]
        raise RuntimeError(f"NMS closure ledger: no cached copy, and neither the published nor the release copy "
                           f"is readable ({type(e).__name__}: {e}); not publishing a smaller ledger") from e
    if pub_exc is not None:
        status = {"status": "ok" if getattr(pub_exc, "code", None) == 404 or released is not None else "failed",
                  "error": f"{type(pub_exc).__name__}: {pub_exc}"[:200]}
    # This run's notices, or the copy a failed lane carries from its last good read, stamped with the time they
    # were read (the lane's fetched_at), so the closures Launch read itself before Cordon's first bulk stay too.
    lane = (snap.get("lanes") or {}).get("nms") or {}
    fresh = (snap.get("nms") or {}).get("notices") or []
    seen_at = lane.get("fetched_at") or snap["generated_at"]
    before = len({nms.ledger_key(e) for d in (prev, published, released) if d for e in d.get("notices") or []})
    led = nms.ledger([published, released, prev], fresh, seen_at)
    led["generated_at"] = snap["generated_at"]
    path.write_text(dump(led, compact=True), encoding="utf-8", newline="\n")
    status.update({"records": led["n"], "added": led["n"] - before, "cache": prev is not None,
                   "published": published is not None, "release": released is not None})
    return status


def _lane_tfr(raw_dir: Path, prev: dict, getter):
    lst, r1 = fetch.fetch("faa-tfr-list", live.TFR_LIST, raw_dir, "json", getter=getter)
    shp, r2 = fetch.fetch("faa-tfr-shapes", live.TFR_SHAPES, raw_dir, "json", getter=getter)
    recs = [r1, r2]
    tfrs = live.tfr_space_ops(lst, shp)
    for t in tfrs:
        url = live.tfr_xml_url(t["id"])
        t["page"] = live.TFR_PAGE.format(a=t["id"][0], b=t["id"][2:]) if url else None
        if url:
            try:
                body, rec = fetch.fetch("faa-tfr-xml", url, raw_dir, "xml", getter=getter)
                recs.append(rec)
                t["detail"] = live.tfr_detail(body)
            except Exception as exc:  # one TFR's XML failing leaves its shape
                t["detail_error"] = f"{type(exc).__name__}: {exc}"[:160]
    return {"tfr": tfrs}, recs


def _lane_orbit(raw_dir: Path, prev: dict, getter):
    body, rec = fetch.fetch("orbit-snapshot", live.ORBIT_SNAPSHOT, raw_dir, "json", getter=getter)
    return {"orbit": live.orbit_read(body)}, [rec]


def _lane_cordon(raw_dir: Path, prev: dict, getter):
    body, rec = fetch.fetch("cordon-feed", live.CORDON_FEED, raw_dir, "json", getter=getter)
    doc = live.cordon_read(body)
    if doc.get("nga_state") in live.NGA_UNREAD:
        # Cordon withholds its NGA set when its reader is stale or has never read: that is no reading, not zero
        # warnings, so the lane fails and keeps its last good copy (ideas#222).
        raise RuntimeError(f"Cordon's NGA warnings are withheld (its reader's state: {doc['nga_state']})")
    return {"cordon": doc}, [rec]


def _lane_nms(raw_dir: Path, prev: dict, getter):
    """FAA NMS-API NOTAMs through Cordon, the suite's one NMS reader (launch/nms.py): its index, then the
    launch-areas and gnss subsets, the active set at Cordon's last pull. No FAA request. Until Cordon has published
    its subsets the lane fails, so the last good NMS areas stay (collect keeps a failed lane's previous copy)."""
    now = datetime.now(timezone.utc)
    body, rec = fetch.fetch("cordon-notams", nms.CORDON_NOTAMS + "index.json", raw_dir, "json", getter=getter)
    index = json.loads(body)
    files = {s["name"]: s for s in index.get("subsets") or []}
    if nms.SUBSET not in files:
        raise RuntimeError(f"Cordon's NOTAM index lists no {nms.SUBSET} subset (lane {index.get('lane_status')})")
    recs, feats = [rec], {}
    for name in (nms.SUBSET, "gnss"):
        if name not in files:
            continue
        b, r = fetch.fetch("cordon-notams", nms.CORDON_NOTAMS + files[name]["file"], raw_dir, "json",
                           getter=getter, gz=True)
        feats[name] = nms.features(json.loads(b))
        recs.append(r)
    state = nms.from_set(feats[nms.SUBSET], index, nms.past_areas(ROOT), now)
    if "gnss" in feats:  # GPS/GNSS NOTAMs for Noisefloor (launch/gnss.py): Cordon's set is the whole active set
        gpath = raw_dir.parent / "gnss" / "store.json"
        gnss.restore(gpath.parent, getter or fetch.get)   # the published store and days first: nothing lost
        g = gnss.update(gnss.load(gpath), feats["gnss"], "bulk", now, index.get("env"))
        g["bulk_at"], g["pulled_to"] = index.get("bulk_at"), index.get("pulled_to") or g.get("pulled_to")
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text(json.dumps(g, ensure_ascii=False, separators=(",", ":")) + "\n",
                         encoding="utf-8", newline="\n")
    return {"nms": state}, recs


def _lane_schedule(raw_dir: Path, prev: dict, getter, snap=None):
    """Launch Library 2 upcoming launches (launch/schedule.py): one request. Applied to the upcoming store after the
    lanes (update_schedule)."""
    now = datetime.now(timezone.utc)
    body, rec = fetch.fetch("ll2-upcoming", schedule.ll2_url(now), raw_dir, "json", getter=getter, gz=True)
    rows = [{k: v for k, v in r.items() if k != "mission_description"}
            for r in schedule.within(schedule.ll2_parse(body), now)]
    return {"schedule": {"read_at": rec["fetched_at"], "rows": rows}}, [rec]


def _lane_news(raw_dir: Path, prev: dict, getter, snap=None):
    """Spaceflight News API headlines for the scheduled launches (launch/news.py), links only: one request, none
    when nothing is scheduled. The LL2 ids are this run's read, else the last live view's."""
    sch = (snap or {}).get("schedule") or {}
    ids = [r["id"] for r in sch.get("rows") or [] if r.get("id")] or [
        (r.get("refs") or {}).get("ll2") for r in ((prev.get("schedule") or {}).get("records") or [])
        if (r.get("refs") or {}).get("ll2")]
    if not ids:
        return {"news": {"read_at": fetch.now_utc(), "articles": [], "by_launch": {},
                         "note": "no scheduled launches"}}, []
    body, rec = fetch.fetch("snapi-articles", news.url(ids), raw_dir, "json", getter=getter)
    return {"news": {"read_at": rec["fetched_at"], "source": news.SITE, **news.parse(body, ids)}}, [rec]


LANES = {"tfr": _lane_tfr, "orbit": _lane_orbit, "cordon": _lane_cordon, "nms": _lane_nms,
         "schedule": _lane_schedule, "news": _lane_news}


def collect(root: Path = ROOT, getter=None, only=None) -> dict:
    data_dir = root / "data"
    raw_dir = data_dir / "raw"
    snap_path = data_dir / "snapshot.json"
    prev = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else {}
    now = fetch.now_utc()
    snap = {"generated_at": now, "method_version": feed.METHOD, "lanes": {}}
    for lane, fn in LANES.items():
        prev_lane = (prev.get("lanes") or {}).get(lane) or {}
        if only and lane not in only:
            for k in LANE_FIELDS[lane]:
                snap[k] = prev.get(k, EMPTY[k])
            snap["lanes"][lane] = {**prev_lane, "from_previous": True} if prev_lane else {"status": "not run"}
            continue
        try:
            result, recs = fn(raw_dir, prev, getter, snap) if lane == "news" else fn(raw_dir, prev, getter)
            snap.update(result)
            snap["lanes"][lane] = {"status": "ok", "fetched_at": now, "from_previous": False,
                                   "fetches": [{k: r[k] for k in ("url", "sha256", "bytes")} for r in recs]}
        except nms.Waiting as exc:
            snap["nms"] = {}
            snap["lanes"][lane] = {"status": "waiting", "note": f"FAA NMS-API via Cordon: {exc}; nothing is read."}
        except Exception as exc:
            had = bool(prev_lane.get("fetched_at"))
            for k in LANE_FIELDS[lane]:
                snap[k] = prev.get(k, EMPTY[k]) if had else EMPTY[k]
            snap["lanes"][lane] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
                                   "failed_at": now, "from_previous": had, "fetched_at": prev_lane.get("fetched_at")}
    pat_path = root / "history" / "patterns.json"
    corridors = json.loads(pat_path.read_text(encoding="utf-8"))["corridors"] if pat_path.exists() else []
    orb = snap.get("orbit") or {}
    # NGA warnings come from Cordon (decided 17 Nov 2026). Orbit's copy is used only until Cordon's lane has
    # succeeded once, so a first run with Cordon down still has warnings.
    nav = (snap.get("cordon") or {}).get("areas")
    tim_path = root / "history" / "timing.json"
    tim = json.loads(tim_path.read_text(encoding="utf-8"))["sites"] if tim_path.exists() else {}
    areas = (list(nav if nav is not None else orb.get("areas") or []) + live.tfr_areas(snap.get("tfr") or [], {})
             + nms.areas(snap.get("nms") or {}, {t["id"] for t in snap.get("tfr") or []}, tim))
    # An area's text is read for live.match (named_in) and left out of the snapshot: each notice links its source.
    snap["areas"] = [{k: v for k, v in a.items() if k not in ("detail", "text")} for a in areas]
    led_path = root / "history" / "ledger.json"
    led_rows = json.loads(led_path.read_text(encoding="utf-8")).get("launches") or [] if led_path.exists() else []
    flown = [{"lat": x["site"]["lat"], "lon": x["site"]["lon"], "inc": x["inc"]} for x in led_rows
             if x.get("kind") == "orbital" and x.get("inc") is not None and (x.get("site") or {}).get("lat") is not None]
    bias_path = root / "history" / "inc_bias.json"
    bias = json.loads(bias_path.read_text(encoding="utf-8"))["samples"] if bias_path.exists() else None
    snap["matches"] = live.match(orb.get("upcoming") or [], areas, corridors, orb.get("launches") or [], flown, bias)
    data_dir.mkdir(parents=True, exist_ok=True)
    # The Ascent move (19 Nov 2026): Launch's own schedule, LL2 ledger and the side-by-side check with Orbit's.
    ll2_led, store = None, None
    if not only or "schedule" in only:
        store = update_schedule(snap, data_dir, datetime.now(timezone.utc), getter)
        ll2_led, orbit_doc, snap["lanes"]["ll2_ledger"] = update_ll2_ledger(data_dir, getter)
        try:
            snap["lanes"]["compare"] = update_compare(snap, store, ll2_led, orbit_doc, data_dir, getter)
        except Exception as exc:  # noqa: BLE001  the check never fails the run
            snap["lanes"]["compare"] = {"status": "failed", "error": _err(exc)}
    # Closure with no listing (Ascent step 1b): only against a schedule read in this run or carried from a good one.
    sched_lane = snap["lanes"].get("schedule") or {}
    sched_ok = bool((snap.get("schedule") or {}).get("read_at")) and sched_lane.get("status") != "failed"
    snap["unlisted"] = unlisted.closures(areas, (snap.get("schedule") or {}).get("records") or [], tim,
                                         datetime.now(timezone.utc), schedule_ok=sched_ok, matches=snap["matches"])
    if store is not None and sched_ok and tim:
        update_closure_records(snap, store, tim, data_dir, datetime.now(timezone.utc))
    snap["lanes"]["ledger"] = update_ledger(snap, areas, data_dir, root, getter, ll2_led)
    if not only or "nms" in only:
        snap["lanes"]["nms_ledger"] = update_nms_ledger(snap, data_dir, getter)
    # GPS/GNSS NOTAMs from the nms lane's pulls, for Noisefloor: data/gnss/ -> site/data/gnss-notams/.
    if not only or "nms" in only:
        try:
            snap["lanes"]["nms"]["gnss"] = gnss.publish(data_dir / "gnss", datetime.now(timezone.utc),
                                                        snap["lanes"]["nms"], nms.SOURCE_NOTE,
                                                        getter or fetch.get)
        except gnss.Unreachable:  # no local copy and the site unreadable: stop, never publish a smaller set
            raise
        except Exception as exc:  # otherwise the subset never fails the run
            snap["lanes"]["nms"]["gnss"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:200]}
    snap_path.write_text(dump(snap), encoding="utf-8", newline="\n")
    return snap


def sources_doc(root: Path = ROOT) -> dict:
    reg = json.loads((root / "doctrine" / "sources.json").read_text(encoding="utf-8"))
    adm = json.loads((root / "doctrine" / "kit" / "vocab" / "grading.json").read_text(encoding="utf-8"))["admiralty"]
    out = []
    for s in reg["sources"]:
        g = s.get("grade") or ""
        out.append({"id": s["id"], "name": s["name"], "url": s["url"], "licence": s.get("licence", ""),
                    "use": s.get("use"), "grade": g, "reliability": adm["reliability"].get(g[:1], ""),
                    "credibility": adm["credibility"].get(g[1:], "")})
    return {"basis": adm["basis"], "sources": out}


def world_shapes(countries: dict, step: float = 0.1) -> dict:
    """Country outlines from the kit's Natural Earth file (public domain) for the map's base at world zoom."""
    feats = []
    for c in countries["countries"]:
        polys = []
        for ring in c["rings"]:
            out = []
            for x, y in ring:
                pt = [round(round(x / step) * step, 2), round(round(y / step) * step, 2)]
                if not out or out[-1] != pt:
                    out.append(pt)
            if len(out) >= 4:
                if out[0] != out[-1]:
                    out.append(out[0])
                polys.append([out])
        if polys:
            feats.append({"type": "Feature", "properties": {"cc": c["cc"]},
                          "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    return {"type": "FeatureCollection", "source": countries["source"], "features": feats}


def build_site(root: Path = ROOT) -> dict[str, str]:
    snap_path = root / "data" / "snapshot.json"
    if not snap_path.exists():
        raise SystemExit("No data/snapshot.json. Run `python tools/launch.py collect` first.")
    hist_path = root / "history" / "history.json"
    if not hist_path.exists():
        raise SystemExit("No history/history.json. Run `python tools/launch.py history` first.")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    # The committed files go through the public gate again here, so a history file written by older code
    # cannot publish a site or a note the allow-list does not clear.
    allow = public.allowlist(root / "history" / "public_sites.json")
    hist = public.history(json.loads(hist_path.read_text(encoding="utf-8")), allow)
    pat = public.patterns(json.loads((root / "history" / "patterns.json").read_text(encoding="utf-8")), hist)
    led_path = root / "data" / "ledger.json"
    if not led_path.exists():
        led_path = root / "history" / "ledger.json"
    ledger = json.loads(led_path.read_text(encoding="utf-8")) if led_path.exists() else {"launches": [], "sites": {}}
    # NotamForChina (history/nfc.json, `launch.py nfc build`): Chinese launches and their notices, with its licence.
    nfc_path, lic_path = root / "history" / "nfc.json", root / "history" / "NOTAMFORCHINA-LICENSE.txt"
    nfc_doc = json.loads(nfc_path.read_text(encoding="utf-8")) if nfc_path.exists() else None
    if nfc_doc and not lic_path.exists():
        raise SystemExit("history/nfc.json is here without history/NOTAMFORCHINA-LICENSE.txt: its licence goes with it.")
    # Joey0609/notams (history/joey.json, `launch.py joey build`): launch-related NOTAMs with text, with its licence.
    joey_path, jlic_path = root / "history" / "joey.json", root / "history" / "JOEY-NOTAMS-LICENSE.txt"
    joey_doc = json.loads(joey_path.read_text(encoding="utf-8")) if joey_path.exists() else None
    if joey_doc and not jlic_path.exists():
        raise SystemExit("history/joey.json is here without history/JOEY-NOTAMS-LICENSE.txt: its licence goes with it.")
    # Internet Archive copies of FAA space-operations TFRs and NGA warnings (history/wayback.json, `launch.py wayback build`).
    wb_path = root / "history" / "wayback.json"
    wb_doc = json.loads(wb_path.read_text(encoding="utf-8")) if wb_path.exists() else None
    # Forum thread links from NotamForChina's list (history/nsf_links.json, `launch.py nfc links`; same licence).
    nsf_path = root / "history" / "nsf_links.json"
    nsf_doc = json.loads(nsf_path.read_text(encoding="utf-8")) if nsf_path.exists() and nfc_doc else None
    countries = json.loads((root / "doctrine" / "kit" / "geo" / "countries.json").read_text(encoding="utf-8"))
    # Sites where GCAT's row is contradicted by the launching state's own report (history/site_fixes.json, reviewed).
    fix_path = root / "history" / "site_fixes.json"
    fixes = json.loads(fix_path.read_text(encoding="utf-8"))["fixes"] if fix_path.exists() else None
    # Closure areas no other source carries, each checked against a published copy (history/published_notices.json).
    pub_path = root / "history" / "published_notices.json"
    published = json.loads(pub_path.read_text(encoding="utf-8"))["notices"] if pub_path.exists() else None
    index = catalog.build_index(hist, ledger, (snap.get("orbit") or {}).get("upcoming") or [], pat["corridors"],
                                snap["generated_at"], nfc_doc, joey_doc, wb_doc, world=overfly.World(countries),
                                nsf_doc=nsf_doc, site_fixes=fixes, published=published,
                                live={"matches": snap.get("matches") or [], "areas": snap.get("areas") or []})
    for tag in (index.get("site_fixes") or {}).get("stale") or []:
        print(f"site_fixes.json: {tag} no longer has the site its fix names in GCAT; review and drop the fix")
    files = {"data/snapshot.json": dump(snap), "data/feed.geojson": dump(feed.build_feed(snap)),
             "data/sources.json": dump(sources_doc(root)),
             # The charted map's lines are an analyst's guesses, not flight paths: not published.
             "data/history.json": dump(dict(hist, events=[{k: v for k, v in e.items() if k != "paths"}
                                                          for e in hist.get("events") or []]), compact=True),
             "data/patterns.json": dump(pat, compact=True),
             "data/world.geojson": dump(world_shapes(countries), compact=True),
             "data/launches.json": dump(index, compact=True), "data/ledger.json": dump(ledger, compact=True)}
    # Every NMS closure notice ever kept (launch/nms.py ledger()), kept for good.
    nl_path = root / "data" / "nms-closures.json"
    if nl_path.exists():
        files["data/nms-closures.json"] = nl_path.read_text(encoding="utf-8")
    files.update(gnss.site_files(root / "data" / "gnss"))
    # Scheduled launches, Launch's own multi-source record (launch/schedule.py), each with its headlines (links only),
    # and the side-by-side check with Orbit's lanes while both run (launch/compare.py). The stores themselves are on
    # the release `ledger`.
    sch = snap.get("schedule") or {}
    files["data/upcoming.json"] = dump({
        "schema": schedule.SCHEMA, "generated_at": snap["generated_at"], "read_at": sch.get("read_at"),
        "attribution": [schedule.ATTRIBUTION, "Headlines: Spaceflight News API (spaceflightnewsapi.net), links only"],
        "store": ll2ledger.RELEASE + STORE["upcoming"], "ledger": ll2ledger.PUBLIC_URL,
        "records": sch.get("records") or []})
    cmp_path = root / "data" / STORE["compare"]
    if cmp_path.exists():
        files["data/ascent-compare.json"] = cmp_path.read_text(encoding="utf-8")
    if nfc_doc:
        files[catalog.NFC_LICENCE_FILE] = lic_path.read_text(encoding="utf-8")
    if joey_doc:
        files[catalog.JOEY_LICENCE_FILE] = jlic_path.read_text(encoding="utf-8")
    for p in sorted((root / "site_src").rglob("*")):
        if p.is_file():
            rel = p.relative_to(root / "site_src").as_posix()
            files[rel] = p.read_bytes() if p.suffix in (".png", ".ico", ".woff2") else p.read_text(encoding="utf-8")
    out = root / "site"
    for rel, body in files.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            dest.write_bytes(body)
        else:
            dest.write_text(body, encoding="utf-8", newline="\n")
    # Nothing private on the site: a listed term in site/ fails the build (launch/privacy.py).
    perrs, _ = privacy.problems(root, include_tracked=False)
    if perrs:
        raise SystemExit("Build failed, the privacy check found listed terms in site/:\n  - " + "\n  - ".join(perrs))
    return files


# Cloudflare Pages, Free plan (developers.cloudflare.com/pages/platform/limits, read 19 Nov 2026): 25 MiB per file,
# 20,000 files per site. The files kept for good (data/nms-closures.json, data/gnss-notams/all.json) grow without
# end, so check warns well ahead and fails before a deploy would be refused; the fix is splitting a file by year.
PAGES_FILE_LIMIT = 25 * 1024 * 1024
SIZE_WARN, SIZE_FAIL = 20 * 1024 * 1024, 24 * 1024 * 1024
PAGES_FILES_LIMIT, FILES_WARN = 20_000, 18_000


def site_size_problems(site: Path) -> tuple[list[str], list[str]]:
    """(problems, notes) for site/: a file over SIZE_FAIL or over FILES_WARN files fails; over SIZE_WARN is noted."""
    errs, notes = [], []
    files = [f for f in site.rglob("*") if f.is_file()] if site.exists() else []
    for f in sorted(files):
        n = f.stat().st_size
        rel = f.relative_to(site).as_posix()
        mib = f"{n / 1048576:.1f} MiB"
        if n > SIZE_FAIL:
            errs.append(f"site/{rel}: {mib}, near Cloudflare Pages' 25 MiB per-file limit: split it (by year)")
        elif n > SIZE_WARN:
            notes.append(f"site/{rel}: {mib} of Cloudflare Pages' 25 MiB per-file limit: plan a split (by year)")
    if len(files) > FILES_WARN:
        errs.append(f"site/: {len(files)} files, near Cloudflare Pages' {PAGES_FILES_LIMIT} files per site")
    return errs, notes


def check_all(root: Path = ROOT) -> list[str]:
    errs = registers.check(root / "doctrine")
    regs = registers.ids(root / "doctrine")
    fp = root / "site" / "data" / "feed.geojson"
    if not fp.exists():
        return errs + ["site/data/feed.geojson is missing: run collect and build first"]
    for feat in json.loads(fp.read_text(encoding="utf-8")).get("features", []):
        fid = (feat.get("properties") or {}).get("id", "?")
        for std, sev, msg in contract.check(feat, regs):
            if sev == "error":
                errs.append(f"{fid}: {std}: {msg}")
    # The history file as built, the one a deploy would publish: no ship, no dated position, no unlisted site,
    # no note that is not on the allow-list.
    hp, pp = root / "site" / "data" / "history.json", root / "site" / "data" / "patterns.json"
    if not hp.exists() or not pp.exists():
        return errs + ["site/data/history.json or patterns.json is missing: run build first"]
    errs += ["data/history.json: " + e for e in public.problems(
        json.loads(hp.read_text(encoding="utf-8")), json.loads(pp.read_text(encoding="utf-8")),
        public.allowlist(root / "history" / "public_sites.json"))]
    # Nothing private in site/ or in any tracked file (launch/privacy.py); shared copies are noted, not failed.
    perrs, notes = privacy.problems(root)
    serrs, snotes = site_size_problems(root / "site")
    for n in notes + snotes:
        print("  note:", n)
    return errs + perrs + serrs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Launch: launch and reentry closure areas, history and matching.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("history")
    h.add_argument("kml", nargs="?", default=str(DEFAULT_KML))
    b = sub.add_parser("backfill")
    b.add_argument("gcat_dir", help="folder of GCAT tables (launch, satcat, satcat100k, sites, orgs), or Orbit's data/raw")
    c = sub.add_parser("collect")
    c.add_argument("--only", nargs="*", choices=sorted(LANES))
    sub.add_parser("build")
    sub.add_parser("check")
    sub.add_parser("timing", help="closure opening to launch, by site, from the built site/data/launches.json "
                                  "-> history/timing.json")
    sub.add_parser("incbias", help="implied-inclination calibration samples, from the built site/data/launches.json "
                                   "-> history/inc_bias.json")
    n = sub.add_parser("nfc", help="NotamForChina: fetch its files at the pinned commit, or build history/nfc.json")
    n.add_argument("step", choices=["fetch", "build", "links"],
                   help="links: its list of forum thread links -> history/nsf_links.json")
    j = sub.add_parser("joey", help="Joey0609/notams: fetch its month files at the pinned commit, or build history/joey.json")
    j.add_argument("step", choices=["fetch", "build"])
    w = sub.add_parser("wayback", help="Internet Archive copies of FAA space-operations TFRs and NGA warnings")
    w.add_argument("step", choices=["fetch", "build"])
    w.add_argument("--since", help="fetch TFR detail pages listed from this date (YYYY-MM-DD) only; newest first")
    a = ap.parse_args(argv)
    if a.cmd == "wayback":
        src = ROOT / "history" / "wayback_source"
        if a.step == "fetch":
            print("Wayback fetch:", wayback.fetch(src, log=lambda m: print(m, flush=True), since=a.since))
            return 0
        doc = wayback.build(src)
        print("Wayback build:", wayback.summary(doc))
        (ROOT / "history" / "wayback.json").write_text(dump(doc, compact=True), encoding="utf-8", newline="\n")
        return 0
    if a.cmd == "timing":
        recs = json.loads((ROOT / "site" / "data" / "launches.json").read_text(encoding="utf-8"))["records"]
        doc = {"rule": " ".join(timing.__doc__.split()), "sites": timing.by_site(recs)}
        print("Timing:", {k: (v["launches"], v["median_min"]) for k, v in doc["sites"].items()})
        (ROOT / "history" / "timing.json").write_text(dump(doc), encoding="utf-8", newline="\n")
        return 0
    if a.cmd == "incbias":
        recs = json.loads((ROOT / "site" / "data" / "launches.json").read_text(encoding="utf-8"))["records"]
        doc = {"rule": " ".join(incbias.__doc__.split()), "fields": ["lon", "lat", "bearing", "inc"],
               "samples": incbias.samples(recs)}
        print("Inclination calibration:", len(doc["samples"]), "samples")
        (ROOT / "history" / "inc_bias.json").write_text(dump(doc, compact=True), encoding="utf-8", newline="\n")
        return 0
    if a.cmd == "joey":
        src = ROOT / "history" / "joey_source"
        if a.step == "fetch":
            print("Joey0609/notams fetch:", joey.fetch(src))
            return 0
        doc = joey.build(src)
        print("Joey0609/notams build:", joey.summary(doc))
        (ROOT / "history" / "joey.json").write_text(dump(doc, compact=True), encoding="utf-8", newline="\n")
        lic = src / "LICENSE"
        if lic.exists():
            (ROOT / "history" / "JOEY-NOTAMS-LICENSE.txt").write_bytes(lic.read_bytes())
        return 0
    if a.cmd == "nfc":
        src = ROOT / "history" / "nfc_source"
        if a.step == "links":
            nsf.fetch(src)
            doc = nsf.build(src)
            print("NotamForChina forum links:", nsf.summary(doc))
            (ROOT / "history" / "nsf_links.json").write_text(dump(doc), encoding="utf-8", newline="\n")
            return 0
        if a.step == "fetch":
            print("NotamForChina fetch:", nfc.fetch(src))
            return 0
        doc = nfc.build(src)
        led = json.loads((ROOT / "history" / "ledger.json").read_text(encoding="utf-8"))
        led = led if isinstance(led, list) else led.get("launches", [])
        print("NotamForChina build:", nfc.join(doc, led), nfc.summary(doc))
        (ROOT / "history" / "nfc.json").write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False) + "\n",
                                                  encoding="utf-8")
        return 0
    if a.cmd == "history":
        r = build_history(Path(a.kml))
        print("History:", {k: r[k] for k in ("events", "areas", "sites", "recurring", "pads")})
        print(f"Sites: {r['sites_on_map']} on the map, {r['sites']} published {r['site_kinds']}, "
              f"{r['site_notes']} with a note (notes come from history/public_sites.json only).")
        print(f"Sites withheld: {sum(r['sites_withheld'].values())} {r['sites_withheld']}")
        if r["sites_not_listed"]:
            print("  Not on the allow-list, so not published (list each under its kind, or under 'held'):")
            for n in r["sites_not_listed"]:
                print("   -", n)
        if r["shapes_withheld"]:
            print(f"Event shapes withheld: {r['shapes_withheld']}")
        if any(r["events_withheld"].values()):
            print(f"Events withheld: {r['events_withheld']}")
        return 0
    if a.cmd == "backfill":
        print("Backfill:", build_backfill(Path(a.gcat_dir)))
        return 0
    if a.cmd == "collect":
        snap = collect(only=a.only)
        for lane, st in snap["lanes"].items():
            print(f"  {lane:6s} {st.get('status')}{' [last good copy]' if st.get('from_previous') else ''}"
                  f"{' (' + st['error'] + ')' if st.get('error') else ''}")
        from collections import Counter
        print(f"{len(snap.get('tfr') or [])} space-operations TFRs; {len(snap['areas'])} live areas; "
              f"{len((snap.get('orbit') or {}).get('upcoming') or [])} scheduled launches (Orbit), "
              f"{len((snap.get('schedule') or {}).get('records') or [])} (Launch); matches "
              f"{dict(Counter(m['level'] for m in snap['matches']))}")
        return 0 if any(s.get("status") == "ok" for s in snap["lanes"].values()) else 1
    if a.cmd == "build":
        print(f"Built site/ ({len(build_site())} files).")
        return 0
    if a.cmd == "check":
        errs = check_all()
        for e in errs:
            print("  -", e)
        print(f"Launch check: {'PASS' if not errs else f'FAIL ({len(errs)} problems)'}")
        return 1 if errs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
