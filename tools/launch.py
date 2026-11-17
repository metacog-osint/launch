"""Launch CLI.

    python tools/launch.py history [KML]   # the charted notices -> history/history.json and history/patterns.json
    python tools/launch.py backfill DIR    # GCAT tables in DIR -> history/ledger.json (every launch since 2012)
    python tools/launch.py collect         # live lanes -> data/snapshot.json; new launches -> data/ledger.json
    python tools/launch.py build           # site/ from history/ and data/snapshot.json
    python tools/launch.py check           # registers + feed lint + public gate + privacy check

collect never makes data up. A failed lane keeps its last good copy (from_previous) or stays empty, and the
snapshot's "lanes" block says which.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))

from launch import catalog, feed, fetch, gcat, history, joey, live, nfc, nsf, overfly, patterns, privacy, public, wayback  # noqa: E402
from tic_doctrine import contract, registers  # noqa: E402

DEFAULT_KML = ROOT / "history" / "source" / "launch-map-2026-11-13.kml"
# Not imported: the exercise layer holds scenario text, not public notices.
EXCLUDED_LAYERS = {"Previous Exercise NOTAMs"}
LANE_FIELDS = {"tfr": ["tfr"], "orbit": ["orbit"], "cordon": ["cordon"]}
# The published ledger, read back on each run so a lost Actions cache loses no launch (merge is a union).
LIVE_LEDGER = "https://launch.theintelligence.company/data/ledger.json"
EMPTY = {"tfr": [], "orbit": {}, "cordon": {}}


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


def update_ledger(snap: dict, areas: list[dict], data_dir: Path, root: Path, getter=None) -> dict:
    """Baseline (committed) + last run's ledger (Actions cache) + the published copy + this run's launches."""
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
    orb = snap.get("orbit") or {}
    now = snap["generated_at"]
    fresh = {"launches": catalog.from_orbit(orb.get("launches") or [], now)
             + catalog.flown_from_ll2(orb.get("upcoming") or [], now),
             "closures": catalog.closures_from_matches(snap.get("matches") or [], areas, now),
             "sites": _sites_from_orbit(orb.get("launches") or [])}
    before = len({r["id"] for lg in (base, prev, published) if lg for r in lg.get("launches") or []})
    led = catalog.merge(base, published, prev, fresh)
    led["generated_at"] = now
    (data_dir / "ledger.json").write_text(dump(led, compact=True), encoding="utf-8", newline="\n")
    status.update({"records": len(led["launches"]), "added": len(led["launches"]) - before,
                   "base": len((base or {}).get("launches") or []), "cache": prev is not None,
                   "published": published is not None})
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
    return {"cordon": live.cordon_read(body)}, [rec]


LANES = {"tfr": _lane_tfr, "orbit": _lane_orbit, "cordon": _lane_cordon}


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
            result, recs = fn(raw_dir, prev, getter)
            snap.update(result)
            snap["lanes"][lane] = {"status": "ok", "fetched_at": now, "from_previous": False,
                                   "fetches": [{k: r[k] for k in ("url", "sha256", "bytes")} for r in recs]}
        except Exception as exc:
            had = bool(prev_lane.get("fetched_at"))
            for k in LANE_FIELDS[lane]:
                snap[k] = prev.get(k, EMPTY[k]) if had else EMPTY[k]
            snap["lanes"][lane] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
                                   "failed_at": now, "from_previous": had, "fetched_at": prev_lane.get("fetched_at")}
    snap["lanes"]["nms"] = {"status": "waiting", "note": "FAA NOTAM Management Service API: access requested "
                                                          "13 Nov 2026; nothing is read until it is granted."}
    pat_path = root / "history" / "patterns.json"
    corridors = json.loads(pat_path.read_text(encoding="utf-8"))["corridors"] if pat_path.exists() else []
    orb = snap.get("orbit") or {}
    # NGA warnings come from Cordon (decided 17 Nov 2026). Orbit's copy is used only until Cordon's lane has
    # succeeded once, so a first run with Cordon down still has warnings.
    nav = (snap.get("cordon") or {}).get("areas")
    areas = list(nav if nav is not None else orb.get("areas") or []) + live.tfr_areas(snap.get("tfr") or [], {})
    snap["areas"] = [{k: v for k, v in a.items() if k != "detail"} for a in areas]
    snap["matches"] = live.match(orb.get("upcoming") or [], areas, corridors, orb.get("launches") or [])
    data_dir.mkdir(parents=True, exist_ok=True)
    snap["lanes"]["ledger"] = update_ledger(snap, areas, data_dir, root, getter)
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
    index = catalog.build_index(hist, ledger, (snap.get("orbit") or {}).get("upcoming") or [], pat["corridors"],
                                snap["generated_at"], nfc_doc, joey_doc, wb_doc, world=overfly.World(countries),
                                nsf_doc=nsf_doc)
    files = {"data/snapshot.json": dump(snap), "data/feed.geojson": dump(feed.build_feed(snap)),
             "data/sources.json": dump(sources_doc(root)),
             "data/history.json": dump(hist, compact=True),
             "data/patterns.json": dump(pat, compact=True),
             "data/world.geojson": dump(world_shapes(countries), compact=True),
             "data/launches.json": dump(index, compact=True), "data/ledger.json": dump(ledger, compact=True)}
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
    for n in notes:
        print("  note:", n)
    return errs + perrs


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
              f"{len((snap.get('orbit') or {}).get('upcoming') or [])} scheduled launches; matches "
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
