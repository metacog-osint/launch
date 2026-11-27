"""The History tab's launch list: Launch's charted notices, GCAT's launch record and Launch Library 2's schedule, joined.

  ledger   every launch GCAT lists since LEDGER_SINCE: orbital, suborbital (sounding rockets, crewed flights,
           atmospheric tests) and military missiles, tests and combat use alike (programs.GCAT_KIND). Backfilled
           from GCAT's own tables (`python tools/launch.py backfill`), then kept current on every run from the 30
           days of GCAT launches in Orbit's snapshot (orbital only: Orbit publishes no others, so suborbital
           launches join when the backfill is run again), so an orbital launch joins the history without anyone
           touching it. A launch Launch Library 2
           reports as flown (status Success, Failure or Partial Failure) joins as "provisional" until GCAT lists it.
           Closure areas a scheduled launch coincided with in time and place are kept with it.
  index    one record per launch or notice for the page: each charted event, joined to its GCAT launch when
           one matches in time and place; each GCAT launch that is not charted; each scheduled launch. Each
           record carries its vehicle, site, programmes, mission type and orbit as read in programs.py, and an
           estimated flight path with the basis of its azimuth.

Flight paths. Every path is estimated one way (the lines on the charted map are an analyst's guesses, not flight
paths, so none is taken as one). Best basis first: the launch's ascent areas (ascent.py says which of its closure
areas those are), the path running through them in order of distance and on at the orbit's heading, checked
against the record's own inclination (CROSS_DEG), turning onto its heading at the farthest area when the line is
more than TURN_DEG off it; else the path a launch from the same site to the same
inclination took through its own areas (borrow_paths()); else the payloads' inclination (GCAT) or the orbit's usual
one (sun-synchronous, a space station), with the direction (north- or south-going) from the pad's closure history;
GTO, GEO and deep-space launches go east (a deep-space payload's inclination is its final orbit's, so it sets
nothing; not from a site in P.NO_EAST, which takes P.DEEP_SPACE_AZ); else the pad's most-used corridor. cos i = cos(latitude) x sin(az) holds
for a launch without a dog-leg. An estimated path is great circles, not a ground track. A suborbital launch or a missile has no
orbit to infer an azimuth from: its path is the bearing to its farthest closure area (drawn to that area, at any
distance), else none.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import ascent as A
from . import gcat, history, notam, overfly
from . import nfc as NFC
from . import programs as P
from .live import time_match

LEDGER_SINCE = "2012-01-01"
DEFAULT_PATH_NM = 1500
AREA_NM = 2500        # closure areas farther than this from the pad do not set an azimuth
TURN_DEG = 5          # a straight path through its areas this far off its own inclination's heading at the farthest
                      # area turns onto that heading there (Plesetsk to 64.8 deg: a drop zone at 92 deg, then ~68)
CROSS_DEG = 55        # an areas' bearing this far from both azimuths the record's own inclination allows gives way;
                      # nearer, it is a dog-leg (PSLV 39 deg, Jiuquan and Yellow Sea sun-synchronous 21-50, the Cape's
                      # polar corridor 36) and stands
MIN_AREA_NM = 50      # closure areas nearer the pad than this (a TFR round the pad) set no azimuth
COARSE_MIN_NM = 150   # ... or than this from a coarse site point (a sea launch's platform is up to ~100 NM from it)
SPREAD_DEG = 15       # areas within this of each other's bearing are one group (one ascent track)
SITE_NM = 60          # a pad belongs to the nearest GCAT site within this distance
MATCH_HOURS = 3       # A charted event and a GCAT launch are one launch within this many hours ...
MATCH_NM = 200        # ... and this far apart (pad to GCAT site), or of the same country
NOPAD_HOURS = 72      # a charted event with no pad: a GCAT launch of its vehicle this long after its window
NOPAD_EARLY_HOURS = 3  # ... or this long before it opens
REGION_RE = re.compile(r"\?$|\bVarious\b|\bMobile\b|(?<!On-)\bSea\b|\bOcean\b|launch location|Launch Area|Barentsovo",
                       re.I)  # a GCAT site that is a region, not a pad ("Mobile launchers in Iran?")
LL2_FLOWN = {"Success", "Failure", "Partial Failure"}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dash(v: str | None) -> str:
    v = (v or "").strip()
    return "" if v in ("-", "?") else v


# ---------- the ledger ----------

def _owner_labels(names: dict, recs: list[dict]) -> dict[str, str]:
    """The names of the owner codes the records carry; codes that share a name show their code after it."""
    used = {c for r in recs for o in (r.get("payloads") or {}).get("owners") or [] for c in gcat.owner_codes(o)}
    out = {c: names[c] for c in sorted(used) if c in names}
    shared = Counter(out.values())
    return {c: f"{n} ({c})" if shared[n] > 1 else n for c, n in out.items()}


def _inc_of(payloads: list[dict]) -> float | None:
    """Median inclination of the payloads that have one (GCAT writes 0.00 before an object has elements)."""
    incs = sorted(p["inc"] for p in payloads if p.get("inc") is not None)
    return round(incs[len(incs) // 2], 2) if incs else None


def _payload_summary(pls: list[dict]) -> dict:
    names = []
    for p in pls:
        n = p.get("name") or ""
        if n and n not in names:
            names.append(n)
    return {"count": len(pls), "names": names[:6], "more": max(0, len(names) - 6),
            "owners": sorted({p.get("owner") for p in pls if p.get("owner")}),
            "states": sorted({p.get("state") for p in pls if p.get("state")}),
            "op_orbits": sorted({p.get("op_orbit") for p in pls if p.get("op_orbit") and p.get("op_orbit") != "-"})}


def _gcat_record(tag, when, vehicle_raw, flight, mission, agency, country, outcome, kind, category, site_code,
                 site, pad_name, payloads, inc, now, **extra) -> dict:
    return {**extra, "id": "gcat:" + tag, "source": "gcat", "tag": tag, "time": when.get("time"), "date": when.get("date"),
            "time_uncertain": bool(when.get("uncertain")), "vehicle_raw": vehicle_raw, "flight": flight,
            "mission": mission, "agency": agency, "country": country, "outcome": outcome, "kind": kind,
            "category": category, "site_code": site_code, "site": site, "pad_name": pad_name,
            "payloads": _payload_summary(payloads), "inc": inc, "updated": now}


def from_gcat_tables(launch_rows: list[dict], sat_rows: list[dict], sites: dict, orgs: dict, now: str,
                     since: str = LEDGER_SINCE) -> list[dict]:
    """The backfill: GCAT launch.tsv rows of every kind in programs.GCAT_KIND (orbital, deep space, near-orbital,
    suborbital, crewed suborbital, atmospheric, missile, lofted missile) dated since `since`, with each launch's
    payloads from the object catalogs (satcat, satcat100k). The launching country is the first launch agency's
    state (GCAT orgs.tsv), else the site's. A site GCAT gives with a "?" is read as that site and marked uncertain;
    a suborbital launch keeps its apogee and range (km, GCAT) and has no inclination; an orbital one its orbit
    reached, `orbit_km` [perigee, apogee] (km, GCAT), when GCAT gives both."""
    pls: dict[str, list] = {}
    for o in sat_rows:
        if (o.get("Type") or "")[:1] != "P":
            continue
        inc = None
        try:
            i, per = float(o.get("Inc") or "x"), float(o.get("Perigee") or "0")
            inc = i if (i > 0 or per > 0) else None
        except ValueError:
            pass
        pls.setdefault(o.get("Launch_Tag", ""), []).append(
            {"name": o.get("Name", ""), "owner": o.get("Owner", ""), "state": o.get("State", ""),
             "op_orbit": o.get("OpOrbit", ""), "inc": inc, "jcat": o.get("JCAT", "")})
    out = []
    for r in launch_rows:
        code = r.get("LaunchCode", "")
        if not code or code[0] not in P.GCAT_KIND:
            continue
        kind = P.GCAT_KIND[code[0]]
        orbital = kind in P.ORBITAL_KINDS
        when = gcat.vague_date(r.get("Launch_Date", ""))
        if not when["date"] or when["date"] < since:
            continue
        tag = r.get("Launch_Tag", "")
        p = sorted(pls.get(tag, []), key=lambda x: x["jcat"])
        inc = _inc_of(p)
        if not orbital:
            inc = None  # a payload's or a lofted test's inclination says nothing about a suborbital launch
        elif inc is None:
            try:
                inc = float(r.get("Inc") or "x")
            except ValueError:
                inc = None
        raw_site = r.get("Launch_Site", "")
        site_code = raw_site.rstrip("?")
        site = sites.get(site_code)
        variant = _dash(r.get("Variant"))
        extra = {}
        if raw_site.endswith("?"):
            extra["site_uncertain"] = True
        if orbital:
            try:
                extra["orbit_km"] = [float(r.get("Perigee") or "x"), float(r.get("Apogee") or "x")]
            except ValueError:
                pass
        if not orbital:
            for col, key in (("Apogee", "apogee_km"), ("Range", "range_km")):
                try:
                    extra[key] = float(r.get(col) or "x")
                except ValueError:
                    pass
        out.append(_gcat_record(
            tag, when, (r.get("LV_Type", "") + (" " + variant if variant else "")).strip(), _dash(r.get("Flight")),
            _dash(r.get("Mission")), r.get("Agency", ""),
            gcat.agency_country(r.get("Agency", ""), orgs) or (site or {}).get("country"),
            {"S": "success", "F": "failure", "U": "unknown", "E": "pad explosion"}.get(code[1:2], code[1:]),
            kind, r.get("Category", ""), site_code, site, _dash(r.get("Launch_Pad")), p, inc, now, **extra))
    return out


def from_orbit(launches: list[dict], now: str) -> list[dict]:
    """GCAT launches as Orbit publishes them (the last 30 days, with their payloads)."""
    out = []
    for g in launches or []:
        if not g.get("launch_tag") or not g.get("date"):
            continue
        pls = g.get("payloads") or []
        launchers = g.get("launchers") or []
        country = (launchers[0].get("country") if launchers else None) or (g.get("site") or {}).get("country")
        veh = (g.get("vehicle") or "") + (" " + g["variant"] if g.get("variant") else "")
        out.append(_gcat_record(
            g["launch_tag"], {"date": g.get("date"), "time": g.get("time"), "uncertain": g.get("time_uncertain")},
            veh.strip(), g.get("flight") or "", g.get("mission") or "", g.get("agency") or "", country,
            g.get("outcome"), g.get("kind") or "orbital", g.get("category") or "", g.get("site_code") or "",
            g.get("site"), g.get("pad") or "", pls, _inc_of(pls), now))
    return out


def _ll2_record(u: dict, now: str, provisional: bool) -> dict:
    return {"id": "ll2:" + u["id"], "source": "ll2", "provisional": provisional, "ll2": u["id"],
            "time": u.get("net"), "net_precision": u.get("net_precision"), "status": u.get("status"),
            "name": u.get("name"), "vehicle_raw": u.get("vehicle"), "mission": u.get("mission"),
            "mission_type": u.get("mission_type"), "orbit": u.get("orbit"), "provider": u.get("provider"),
            "country": (u.get("provider_countries") or [None])[0] or u.get("pad_country"),
            "pad_name": u.get("pad"), "location": u.get("location"), "lat": u.get("lat"), "lon": u.get("lon"),
            "ll2_url": u.get("ll2_url"), "updated": now}


def flown_from_ll2(upcoming: list[dict], now: str) -> list[dict]:
    """Scheduled launches Launch Library 2 marks as flown: provisional records until GCAT lists the launch."""
    return [_ll2_record(u, now, True) for u in upcoming or []
            if u.get("id") and u.get("status") in LL2_FLOWN and u.get("net")]


def closures_from_matches(matches: list[dict], areas: list[dict], now: str) -> list[dict]:
    """Closure areas a scheduled launch coincided with in time and place (or grouped), or in time with the notice's
    text naming its mission (live.named_in, `named_by` "mission"), kept with that launch. A notice
    with several areas stores each ring the match names (`area_i`). The first ring keeps the id older records have,
    `launch|area`; a later ring is `launch|area#<ring tag>`, since a run's area index is not stable between runs."""
    by_key: dict = {}
    for i, a in enumerate(areas):
        by_key.setdefault(a.get("key") or a.get("id"), []).append(i)
    out = []
    for m in matches or []:
        if m.get("level") not in ("time and place", "grouped") and m.get("named_by") != "mission":
            continue
        rings = by_key.get(m.get("area"))
        if not rings:
            continue
        i = m.get("area_i") if m.get("area_i") in rings else rings[0]
        a = areas[i]
        if not a.get("ring"):
            continue
        cid = f"{m['launch']}|{m['area']}" + ("" if i == rings[0] else f"#{_ring_tag(a['ring'])}")
        out.append({"id": cid, "ll2": m["launch"], "area": m["area"],
                    "source": m.get("area_source"), "level": m["level"], "window": m.get("window"),
                    **({"named": m["named"]} if m.get("named_by") == "mission" else {}),
                    "ring": a["ring"], "azimuth": m.get("azimuth"), "distance_nm": m.get("distance_nm"),
                    "recorded": now})
    return out


def _ring_tag(ring: list) -> str:
    """A short name for one ring that is the same in every run."""
    pts = [[round(x, 4) for x in p[:2]] for p in ring or []]
    return hashlib.sha256(json.dumps(pts, separators=(",", ":")).encode()).hexdigest()[:8]


def _closure_windows(c: dict) -> list:
    """Every window recorded for a stored closure."""
    return c.get("windows") or ([c["window"]] if c.get("window") else [])


def _keep_closure(store: dict, key, c: dict) -> None:
    """The first reading of a closure stands and a later reading adds any window it lacks, so a launch that slips into
    another window of the same notice still finds that window."""
    old = store.get(key)
    if old is None:
        store[key] = c
        return
    seen = _closure_windows(old)
    more = [w for w in _closure_windows(c) if w not in seen]
    if more:
        store[key] = {**old, "windows": sorted(seen + more)}


def closures_holding(cl: list[dict], time: str | None, precision: str | None = None) -> list[dict]:
    """The stored closures that are still this launch's: a window holds its time by live.match()'s rule, and `window`
    is set to that one. The rest stay in the ledger and are left off the record (a slipped launch's old closures).
    A time known only to the day takes a window within 24 h of it. With a coarser time, no time or an unreadable
    window, nothing can be tested and the closure stays."""
    t = _dt(time)
    if not t or (precision not in LIVE_NET_PRECISE and precision != "Day"):
        return list(cl)
    out = []
    for c in cl:
        wins = _closure_windows(c)
        spans = [(w, _dt(w[0]), _dt(w[1])) for w in wins if len(w) >= 2]
        if not wins or len(spans) < len(wins) or any(s is None or e is None for _, s, e in spans):
            out.append(c)
            continue
        if precision == "Day":
            hit = next((w for w, s, e in spans if s - timedelta(hours=24) <= t <= e + timedelta(hours=24)), None)
        else:
            hit = next((w for w, s, e in spans if time_match(t, [(s, e)])), None)
        if hit:
            out.append({**c, "window": hit})
    return out


def merge(*ledgers: dict | None) -> dict:
    """Union of ledgers by record id; where both hold a record the later `updated` wins. Nothing is dropped. A site
    keeps the first ledger's reading (the committed backfill, from GCAT's sites table with Launch's current names and
    region flags); a later ledger adds sites it lacks and fields its reading lacks."""
    launches, closures, sites, since = {}, {}, {}, LEDGER_SINCE
    for lg in ledgers:
        if not lg:
            continue
        since = min(since, lg.get("since") or since)
        for code, st in (lg.get("sites") or {}).items():
            sites[code] = {**st, **sites[code]} if code in sites else st
        for r in lg.get("launches") or []:
            old = launches.get(r["id"])
            if old is None:
                launches[r["id"]] = r
                continue
            new, base = (r, old) if (r.get("updated") or "") >= (old.get("updated") or "") else (old, r)
            # The newer reading wins field by field; a field it lacks (Orbit's copy has no inclination) is kept.
            launches[r["id"]] = {**base, **{k: v for k, v in new.items() if v not in (None, "", [], {})}}
        for c in lg.get("closures") or []:
            _keep_closure(closures, c["id"], c)
    rows = sorted(launches.values(), key=lambda r: (r.get("time") or r.get("date") or "", r["id"]))
    return {"version": 1, "since": since, "launches": rows, "closures": sorted(closures.values(), key=lambda c: c["id"]),
            "sites": dict(sorted(sites.items()))}


# ---------- sites ----------

def apply_site_fixes(launches: list[dict], sites: dict, fixes: list[dict] | None) -> tuple[list[dict], dict]:
    """history/site_fixes.json: a GCAT launch whose site the launching state's own report contradicts takes the
    reported site. A fix applies only while GCAT still gives the site it names; otherwise it is listed as stale.
    Returns the launches (fixed ones copied, never changed in place) and {"applied": [...], "stale": [...]}."""
    by_tag = {f["tag"]: f for f in fixes or []}
    done: dict = {"applied": [], "stale": []}
    out = []
    for g in launches:
        f = by_tag.get(g.get("tag")) if g.get("source") == "gcat" else None
        if f is None:
            out.append(g)
            continue
        to = sites.get(f["site_code"])
        if g.get("site_code") != f["gcat_site_code"] or not to:
            done["stale"].append(f["tag"])
            out.append(g)
            continue
        was = (sites.get(g.get("site_code") or "") or {}).get("name") or (g.get("site") or {}).get("name")
        out.append(dict(g, site_code=f["site_code"], pad_name="",
                        site={k: to.get(k) for k in ("lat", "lon", "country")} | {"name": to.get("gcat_name") or to["name"]},
                        site_fix={"gcat_site": was, "gcat_pad": f.get("gcat_pad") or g.get("pad_name") or None,
                                  "publisher": f["source"]["publisher"], "url": f["source"]["url"],
                                  "date": f["source"].get("date")}))
        done["applied"].append(f["tag"])
    return out, done


def site_table(gcat_sites: dict, used_codes) -> dict:
    """GCAT sites that launches use, keyed by code: {name (Launch's), gcat_name, lat, lon, country}."""
    out = {}
    for code in sorted(set(used_codes)):
        s = gcat_sites.get(code)
        if s and s.get("lat") is not None:
            out[code] = {"name": P.site_name(s.get("name")) or code, "gcat_name": s.get("full_name") or s.get("name"),
                         "lat": s["lat"], "lon": s["lon"], "country": s.get("country")}
            if REGION_RE.search(s.get("full_name") or ""):
                out[code]["region"] = True
    return out


def nearest_site(lat: float, lon: float, sites: dict, within_nm: float = SITE_NM, place: str | None = None) -> str | None:
    """The nearest site within `within_nm`. GCAT's site positions are coarse, so where a place name is given
    (Launch Library 2's "Cape Canaveral SFS, FL, USA") a site within range that it names wins."""
    near = []
    for s in sites.values():
        d = notam.haversine_nm(lat, lon, s["lat"], s["lon"])
        if d <= within_nm:
            near.append((d, s["name"]))
    if place:
        pl = place.lower()
        named = []
        for d, name in near:
            hits = [a for a in [name.split(" (")[0].lower()] + P.SITE_ALIASES.get(name, []) if a in pl]
            if hits:
                named.append((-max(len(a) for a in hits), d, name))  # the most specific name wins
        if named:
            return min(named)[2]
    return min(near)[1] if near else None


# ---------- azimuths and paths ----------

def branches(lat: float, inc: float) -> tuple[list[float], bool]:
    """The two launch azimuths (degrees from north) that reach inclination `inc` from latitude `lat`, and whether
    the inclination is reachable directly (inc >= |lat| for prograde). Unreachable: due east (or west)."""
    c = math.cos(math.radians(inc)) / max(1e-9, math.cos(math.radians(lat)))
    if c > 1:
        return [90.0], False
    if c < -1:
        return [270.0], False
    a = math.degrees(math.asin(c))
    return sorted({round(a % 360, 1), round((180 - a) % 360, 1)}), True


def _adiff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _band_support(az: float, bands: list[dict]) -> float:
    return sum(b["events"] * math.exp(-(_adiff(az, (b["from"] + b["to"]) / 2) / 10) ** 2) for b in bands or [])


def choose(options: list[float], bands: list[dict], site: str | None, polar: bool = False) -> tuple[float, str]:
    """Pick the azimuth the pad's closure history supports; else, for a polar or sun-synchronous orbit, the
    site's usual direction; else north-going (assumed, and said so)."""
    if len(options) == 1:
        return options[0], "the only direction"
    scored = sorted(((_band_support(o, bands), o) for o in options), reverse=True)
    if scored[0][0] >= 0.5 and scored[0][0] > scored[1][0] * 1.5:
        return scored[0][1], "direction from the site's closure history"
    want, why = P.SITE_DIRECTION.get(site or ""), "as launches from this site go"
    if not want and polar:
        want, why = P.POLAR_DIRECTION.get(site or ""), "as polar launches from this site go"
    if want in ("N", "S"):
        pick = min(options, key=lambda o: _adiff(o, 0 if want == "N" else 180))
        return pick, ("south" if want == "S" else "north") + "-going, " + why
    return min(options, key=lambda o: _adiff(o, 0)), "north-going assumed (no closure history to choose by)"


def site_bands(corridors: list[dict], sites: dict) -> dict[str, list[dict]]:
    """Closure-history azimuth bands from patterns.json, summed per launch site."""
    out: dict[str, dict] = {}
    for c in corridors or []:
        name = nearest_site(c["pad"][1], c["pad"][0], sites)
        if not name:
            continue
        acc = out.setdefault(name, {})
        for b in c["bands"]:
            x = acc.setdefault(b["from"], {"from": b["from"], "to": b["to"], "events": 0,
                                           "downrange_nm": list(b["downrange_nm"])})
            x["events"] += b["events"]
            x["downrange_nm"] = [min(x["downrange_nm"][0], b["downrange_nm"][0]),
                                 max(x["downrange_nm"][1], b["downrange_nm"][1])]
    return {k: sorted(v.values(), key=lambda b: b["from"]) for k, v in out.items()}


def farthest_nm(pad, areas: list[dict] | None) -> int | None:
    """Distance from the pad to the record's farthest closure area (its centroid), NM; None without both."""
    d = [a["downrange_nm"] for a in (areas or []) if a.get("downrange_nm") is not None]
    return round(max(d)) if pad and d else None


def orient_paths(e: dict, sites: dict) -> dict:
    """A charted event with its lines running from the pad outward. The lines are an analyst's guesses, not flight
    paths, and are never drawn; but the import takes the first point of the first line as the event's pad, and some
    were drawn from the far end back to the pad: a line whose last point is a launch site (within SITE_NM) and whose
    first is not is turned round, and a pad at no site becomes the first line's start that is. The pad sets where a
    charted event joins by place and a notice set's distances. Lines starting at no site (air and sea launches,
    drop-zone legs) are left as drawn."""
    paths = e.get("paths") or []
    if not paths or not sites:
        return e
    at_site = lambda q: nearest_site(q[1], q[0], sites) is not None
    out = [list(reversed(ln)) if (not at_site(ln[0]) and at_site(ln[-1])) else ln for ln in paths]
    pad = e.get("pad") if (e.get("pad") and at_site(e["pad"])) else next((ln[0] for ln in out if at_site(ln[0])), e.get("pad"))
    if out == paths and pad == e.get("pad"):
        return e
    return dict(e, paths=out, pad=pad)


def coarse_site(r: dict) -> bool:
    """A record whose GCAT site is a coarse point: a region, a sea launch, an air launch (GCAT gives the airfield)."""
    return r.get("pad_basis") in ("region", "chart") or "(sea launch)" in (r.get("site") or "") or P.air_launch(r.get("vehicle"))


def main_area(near: list[dict]) -> dict:
    """The area that sets an azimuth: the farthest of the largest group of areas within SPREAD_DEG of one bearing (a
    tie goes to the group reaching farther). A launch's ascent areas lie along one track; a notice joined by its
    window alone (Joey0609's, an archived NGA warning) can be another event's and bear anywhere (LM-3B ChinaSat-6E,
    9 Nov 2023: four areas at 98-99 deg, an NGA warning at 237)."""
    def group(x):
        return [y for y in near if _adiff(x["azimuth"], y["azimuth"]) <= SPREAD_DEG]
    best = max(near, key=lambda x: (len(group(x)), max(y["downrange_nm"] for y in group(x))))
    return max(group(best), key=lambda y: y["downrange_nm"])


BORROW_INC_DEG = 1.0   # a path from the inclination alone takes the path of a launch from the same site within this


def borrow_paths(recs: list[dict], world=None) -> int:
    """A path set by the inclination alone (no closure areas, or its own set aside) takes the path of the launch
    from the same site to the same inclination (within BORROW_INC_DEG, the same direction) whose own closure areas
    (two or more) set its path, nearest in time, drawn to at least DEFAULT_PATH_NM: that site's practice, dog-legs included, rather than the textbook azimuth
    (Starlink at 53 deg from Vandenberg runs south-east along the coast, not across Baja). Pops the internal keys.
    Returns how many paths were borrowed."""
    donors: dict[str, list[dict]] = {}
    for r in recs:
        p = r.get("path")
        if (p and p.get("_by") == "areas" and p.get("_n", 0) >= 2 and r.get("status") == "launched" and p.get("_inc")
                and r.get("site")):
            donors.setdefault(r["site"], []).append(r)
    n = 0
    for r in recs:
        p = r.get("path")
        if not (p and p.get("_by") == "inc" and p.get("_inc") and r.get("site") and r.get("pad")):
            continue
        cands = []
        for d in donors.get(r["site"], []):
            dp = d["path"]
            if d is r or abs(dp["_inc"] - p["_inc"]) > BORROW_INC_DEG or not d.get("pad"):
                continue
            first = (history.bearing(d["pad"][1], d["pad"][0], dp["via"][0][1], dp["via"][0][0])
                     if dp.get("via") else dp["az"])
            if _adiff(first, p["az"]) > 60 or notam.haversine_nm(r["pad"][1], r["pad"][0], d["pad"][1], d["pad"][0]) > 30:
                continue
            h = _hours_apart(r.get("time"), d.get("time"))
            cands.append((h if h is not None else 1e9, d))
        if not cands:
            continue
        d = min(cands, key=lambda c: c[0])[1]
        dp = d["path"]
        i = p["basis"].find("; its closure areas")
        why = p["basis"][i + 2:] if i >= 0 else ""
        own = "its own closure areas set aside" if why else "no closure areas of its own"
        r["path"] = {k: v for k, v in dp.items() if k in ("kind", "az", "nm", "via")}
        r["path"]["nm"] = max(dp["nm"], DEFAULT_PATH_NM)
        r["path"]["basis"] = (f"the path of the {d.get('vehicle') or 'launch'} of {(d.get('time') or '')[:10]} "
                              f"({d['id']}) from this site to {dp['_inc']:g}°, set by its closure areas ({own})"
                              + (f": {why}" if why else ""))
        r["path"]["borrowed"] = d["id"]
        if world is not None:
            over = overfly.overflight(world, r)
            if over is not None:
                r["over"] = over
            else:
                r.pop("over", None)
        n += 1
    for r in recs:
        for k in ("_by", "_inc", "_n"):
            (r.get("path") or {}).pop(k, None)
    return n


def kept_first_az(pad, pts: list[list[float]]) -> float:
    """The bearing from the pad to the nearest ascent point."""
    return round(history.bearing(pad[1], pad[0], pts[0][1], pts[0][0]), 1)


def _target_inc(inc, inc_note, orbit_code, orbit) -> tuple[float | None, str | None, bool]:
    """The inclination a path is aimed at, what it is, and whether it is the record's own (its payloads', its
    station's or its orbit class's; not one borrowed from an earlier launch)."""
    if inc is not None and inc > 0:
        return inc, inc_note or f"payload inclination {inc:g}° (GCAT)", inc_note is None
    if orbit_code in P.STATION_INC:
        return P.STATION_INC[orbit_code], f"space station inclination {P.STATION_INC[orbit_code]:g}°", True
    if orbit in P.CLASS_INC:
        return P.CLASS_INC[orbit], f"sun-synchronous inclination, about {P.CLASS_INC[orbit]:g}°", True
    return None, None, False


def _going_north(pad, az: float, inc: float, site: str | None) -> bool | None:
    """Whether a launch leaving the pad on bearing `az` is on the north-going branch of an orbit of inclination `inc`:
    the branch whose azimuth from the pad is nearer, or, when the two are within 10 deg of each other, the way the
    site's launches go (P.SITE_DIRECTION). None when the inclination has one branch from there."""
    opts, direct = branches(pad[1], inc)
    if not direct or len(opts) < 2:
        return None
    d = [_adiff(o, az) for o in opts]
    way = P.SITE_DIRECTION.get(site or "")
    if abs(d[0] - d[1]) < 10 and way:
        return way == "N"
    return math.cos(math.radians(opts[0] if d[0] <= d[1] else opts[1])) > 0


def infer_path(pad, site: str | None, bands: list[dict], *, areas=None, inc=None, inc_note=None,
               orbit_code=None, orbit=None, suborbital=False, coarse=False, time=None, others=None,
               used: list | None = None, orbit_km=None) -> dict | None:
    """{kind, az, nm, basis} for a record, or None; kind is always "estimated". `areas`: [{azimuth, downrange_nm}],
    optionally with centroid, tie, notice, windows and schedule (`ascent.select()`). A path through its closure
    areas that bends (`ascent.bends()`) has `via` ([[lon, lat]], the ascent areas in order of distance) and runs on
    from the last of them on `az`, `nm` in all; so does an estimated south-going path from a site in
    P.POLAR_CORRIDOR (its turn point). `time`: the launch time (UTC), for the areas' windows; None for a launch known
    only to the day. `inc_note` says where an inclination came from when it is not the record's own payloads. A
    suborbital launch (`suborbital`) takes the bearing to its farthest closure area at any distance (its impact or
    recovery area), drawn to that area, and nothing else: no orbit sets its azimuth and the site's corridors are its
    orbital ones. The areas' overall bearing is checked against the record's own inclination: when it is more than
    CROSS_DEG from both azimuths that inclination allows, the areas give way (Shenzhou-20 from Jiuquan: 162 deg to an
    area, ~97 for the station). `coarse`: the pad is a coarse site point (a region, a sea launch), so nearer areas
    than COARSE_MIN_NM count for nothing. `others`: a list that gains the areas set aside as another event's
    (ascent.select()). `used`: a list that gains the areas a path was drawn through (live_paths()). An internal `_by`
    key ("areas", "inc", ...) is popped by build_index. `orbit_km`: GCAT's [perigee, apogee] for the launch, for the
    later-pass test (ascent.Orbit)."""
    if not pad:
        return None
    ar = [x for x in (areas or []) if x.get("azimuth") is not None and x.get("downrange_nm")]
    if suborbital:
        if not ar:
            return None
        far = max(ar, key=lambda x: x["downrange_nm"])
        if used is not None:
            used.append(far)
        return {"kind": "estimated", "az": far["azimuth"], "nm": round(far["downrange_nm"]),
                "basis": "bearing from the pad to its farthest closure area, drawn to it (a suborbital flight)"}
    target, what, own = _target_inc(inc, inc_note, orbit_code, orbit)
    lo_nm = COARSE_MIN_NM if coarse else MIN_AREA_NM
    near = [x for x in ar if lo_nm <= x["downrange_nm"] <= AREA_NM]
    beyond = [x for x in ar if x["downrange_nm"] > AREA_NM]
    opts, direct = branches(pad[1], target) if target is not None else (None, False)
    kept, aside = A.select(pad, near, beyond, time=time, inc=target, own=own, area_nm=AREA_NM, spread=SPREAD_DEG,
                           branch_az=opts if (own and direct) else None, others=others, orbit_km=orbit_km)
    set_aside = "; set aside: " + ", ".join(f"{n} {A.WHY[k]}" for k, n in aside.items()) if aside else ""
    gave_way = None
    if kept:
        far = max(kept, key=lambda x: x["downrange_nm"])
        az = far["azimuth"]
        if own and direct and min(_adiff(o, az) for o in opts) > CROSS_DEG:
            gave_way = (f"; its closure areas' bearing ({az:g}°) is {min(_adiff(o, az) for o in opts):.0f}° off both "
                        "azimuths that inclination allows: more than a dog-leg, so taken as areas off the ascent track")
        else:
            if used is not None:
                used.extend(kept)
            pts, off_line = A.route(pad, A.points(pad, kept))
            n_areas = len(kept)
            if off_line:
                set_aside += (f"; {off_line} area point{'' if off_line == 1 else 's'} not drawn through (the path "
                              f"would turn more than {A.MAX_TURN_DEG}° there: areas side by side, not a dog-leg)")
            if A.bends(pad, pts) and A.zigzag(pad, pts):
                set_aside += (f"; {len(pts) - 1} nearer area points drawn as one line to the farthest (they lie "
                              f"both sides of it, more than {A.ZIGZAG_NM} NM each: drop zones side by side, not a "
                              "dog-leg)")
                pts = pts[-1:]
            if A.bends(pad, pts):
                done = A.legs_nm(pad, pts)
                tail = max(100.0, 0.15 * far["downrange_nm"])
                leg = A.final_bearing(([pad] + pts)[-2], pts[-1])
                head, how = leg, "the last leg's heading"
                if own and target is not None:
                    t_opts, t_direct = branches(pts[-1][1], target)
                    best = min(t_opts, key=lambda o: _adiff(o, leg))
                    if t_direct and _adiff(best, leg) <= 45:
                        head, how = best, f"the heading of {what} there"
                dists = sorted(round(x["downrange_nm"]) for x in kept)
                return {"kind": "estimated", "az": round(head, 1), "nm": round(done + tail), "via": pts, "_by": "areas",
                        "_n": n_areas,
                        "basis": f"through its closure areas in order of distance ({n_areas} area"
                                 f"{'' if n_areas == 1 else 's'}, {dists[0]:,}-{dists[-1]:,} NM out; the bearing from the pad "
                                 f"goes from {kept_first_az(pad, pts):g}° to {az:g}°, so the path bends: a dog-leg), "
                                 f"then on {how}"
                                 + set_aside}
            many = len({round(x["azimuth"]) for x in kept}) > 1
            basis = ("bearing from the pad to its farthest closure area"
                     + (f" ({n_areas} areas on one line)" if many else ""))
            if own and target is not None and pts:
                leg = A.final_bearing(pad, pts[-1])
                t_opts, t_direct = branches(pts[-1][1], target)
                best = min(t_opts, key=lambda o: _adiff(o, leg))
                north = _going_north(pad, history.bearing(pad[1], pad[0], pts[-1][1], pts[-1][0]), target, site)
                if north is not None and len(t_opts) == 2:
                    # the launch stays on the branch it left the pad on (north- or south-going on its orbit)
                    best = next((o for o in t_opts if (math.cos(math.radians(o)) > 0) == north), best)
                if t_direct and TURN_DEG < _adiff(best, leg) <= 45:
                    return {"kind": "estimated", "az": round(best, 1),
                            "nm": round(A.legs_nm(pad, pts[-1:]) + max(100.0, 0.15 * far["downrange_nm"])),
                            "via": pts[-1:], "_by": "areas", "_n": n_areas,
                            "basis": basis + f", then on the heading of {what} there ({_adiff(best, leg):.0f}° off the "
                                             "areas' line: a dog-leg)" + set_aside}
            return {"kind": "estimated", "az": az, "nm": round(max(200, far["downrange_nm"] * 1.15)),
                    "basis": basis + set_aside, "_by": "areas", "_n": n_areas}
    elif aside:
        gave_way = "; its closure areas set aside: " + ", ".join(f"{n} {A.WHY[k]}" for k, n in aside.items())
    if gave_way and own and direct:
        if kept:
            best = min(opts, key=lambda o: _adiff(o, max(kept, key=lambda x: x["downrange_nm"])["azimuth"]))
            return {"kind": "estimated", "az": best, "nm": DEFAULT_PATH_NM, "_by": "inc",
                    "basis": f"{what} from the pad's latitude, the azimuth nearer its closure areas" + gave_way + set_aside}
    note_aside = gave_way or ""
    if target is not None:
        opts, direct = branches(pad[1], target)
        az, how = choose(opts, bands, site, polar=target >= 80)
        note = "" if direct else "; not reachable directly from this latitude, so due east (a dog-leg or plane change follows)"
        turn = P.POLAR_CORRIDOR.get(site or "")
        if turn and direct and _adiff(az, 180) <= 45:
            t_opts, _ = branches(turn[1], target)
            t_az = min(t_opts, key=lambda o: _adiff(o, az))
            return {"kind": "estimated", "az": t_az, "nm": DEFAULT_PATH_NM, "via": [list(turn)], "_by": "inc",
                    "basis": f"{what} from the turn point's latitude; {how}; {P.CORRIDOR_NOTE}{note_aside}"}
        return {"kind": "estimated", "az": az, "nm": DEFAULT_PATH_NM, "_by": "inc",
                "basis": f"{what} from the pad's latitude; {how}{note}{note_aside}"}
    if orbit == "GTO / GEO" or (orbit == "Deep space / lunar" and site not in P.NO_EAST):
        bound = "geostationary-bound" if orbit == "GTO / GEO" else "bound for deep space or the Moon"
        near = [b for b in bands or [] if _adiff((b["from"] + b["to"]) / 2, 90) <= 30 and b["events"] >= 2]
        if near:
            b = max(near, key=lambda b: b["events"])
            return {"kind": "estimated", "az": b["from"] + 2.5, "nm": DEFAULT_PATH_NM,
                    "basis": f"{bound}: the site's most-used easterly corridor ({b['events']} events)"}
        return {"kind": "estimated", "az": 90.0, "nm": DEFAULT_PATH_NM, "basis": f"{bound}: due east"}
    if orbit == "Deep space / lunar" and site in P.DEEP_SPACE_AZ:
        az, why = P.DEEP_SPACE_AZ[site]
        return {"kind": "estimated", "az": az, "nm": DEFAULT_PATH_NM,
                "basis": f"bound for deep space or the Moon from a site that launches nothing east: {why}"}
    good = [b for b in bands or [] if b["events"] >= 3]
    if good:
        b = max(good, key=lambda b: b["events"])
        return {"kind": "estimated", "az": b["from"] + 2.5, "nm": DEFAULT_PATH_NM,
                "basis": f"the site's most-used corridor ({b['events']} charted events)"}
    return None


# ---------- Live tab: scheduled launches through their coinciding closure areas ----------
# A scheduled launch's NET falling in an area's window (live.match) is a coincidence, and one window can hold launches
# on different continents: on 21 Nov 2026 NAVAREA XII 811/26, off Vandenberg, also "matched" an Ariane 6 at Kourou,
# 4,000 NM away. So a time-only match counts only on the bearing the launch was already expected to take.

LIVE_TIME_DEG = SPREAD_DEG      # a time-only match this near the launch's expected first bearing can set its path
LIVE_NET_PRECISE = {None, "Second", "Minute", "Hour"}   # a NET known only to the day or coarser ties nothing


def _expected_az(r: dict) -> float | None:
    """The first bearing of the record's estimate before any live area is read."""
    p, pad = r.get("path"), r.get("pad")
    if not p or not pad:
        return None
    if p.get("via"):
        return history.bearing(pad[1], pad[0], p["via"][0][1], p["via"][0][0])
    return p.get("az")


def live_paths(recs: list[dict], matches: list[dict], areas: list[dict], bands_by_site: dict, world=None) -> int:
    """Each upcoming record with live.match() rows gains `live.closures`: every coinciding area with its role, `path`
    (the estimate runs through it), `pad` (nearer the pad than MIN_AREA_NM) or `coincidence` (with `why`). When any
    area sets a path, it replaces the record's estimate, so History and Live draw one line. Without one, the record
    keeps its estimate and the Live tab draws no line. Roles describe geometry: none says an area is for the launch.
    Returns how many paths run through live areas."""
    by: dict[str, list[dict]] = {}
    for m in matches or []:
        by.setdefault(m.get("launch"), []).append(m)
    n = 0
    for r in recs:
        if r.get("status") != "upcoming" or not r.get("pad") or r.get("ll2") not in by:
            continue
        pad = r["pad"]
        expected = _expected_az(r)
        precise = r.get("net_precision") in LIVE_NET_PRECISE
        rows, cands = [], []
        for m in by[r["ll2"]]:
            i = m.get("area_i")
            a = areas[i] if isinstance(i, int) and 0 <= i < len(areas) else None
            if not a or not a.get("ring"):
                continue
            la, lo = notam.centroid(a["ring"])
            az, nm = history.bearing(pad[1], pad[0], la, lo), notam.haversine_nm(pad[1], pad[0], la, lo)
            row = {"i": i, "area": m.get("area"), "source": m.get("area_source"), "level": m.get("level"),
                   "window": m.get("window"), "azimuth": round(az, 1), "nm": round(nm), "role": "coincidence"}
            rows.append(row)
            if not precise:
                row["why"] = "the launch's time is known only to the day or coarser"
            elif nm < MIN_AREA_NM:
                row["role"] = "pad"
            elif nm > AREA_NM:
                row["why"] = f"{nm:,.0f} NM from the pad, farther than an ascent's closure areas are read"
            elif m.get("level") == "time" and m.get("named_by") != "mission" and expected is None:
                row["why"] = "the time fits, and no expected bearing to test the place against"
            elif m.get("level") == "time" and m.get("named_by") != "mission" and _adiff(az, expected) > LIVE_TIME_DEG:
                row["why"] = f"the time fits, but it lies {_adiff(az, expected):.0f}\u00b0 off the launch's expected bearing"
            else:
                cands.append({"ring": a["ring"], "centroid": [round(lo, 4), round(la, 4)], "azimuth": round(az, 1),
                              "downrange_nm": round(nm, 1), "tie": A.TIE_WINDOW, "notice": m.get("area"),
                              "windows": [[w["start"], w["end"]] for w in a.get("windows") or []
                                          if w.get("start") and w.get("end")], "_row": row})
        if not rows:
            continue
        used: list[dict] = []
        sub = r.get("kind") not in (P.ORBITAL, P.NOT_KNOWN)
        p = infer_path(pad, r.get("site"), bands_by_site.get(r.get("site") or "", []), areas=cands,
                       orbit=None if sub else r.get("orbit"), suborbital=sub, time=r.get("time"),
                       used=used) if cands else None
        if p and used:
            for c in used:
                c["_row"]["role"] = "path"
            for k in ("_by", "_n", "_inc"):
                p.pop(k, None)
            r["path"] = p
            if world is not None:
                over = overfly.overflight(world, r)
                if over is not None:
                    r["over"] = over
                else:
                    r.pop("over", None)
            n += 1
        for c in cands:
            if c["_row"]["role"] == "coincidence":
                c["_row"]["why"] = "the time and place fit, but it is off the line of this launch's other areas"
        r["live"] = {"closures": sorted(rows, key=lambda x: (x["nm"], x["i"]))}
    return n


# ---------- NotamForChina ----------
# history/nfc.json (nfc.py): Chinese launches 2012-2026 with the NOTAMs that closed their drop zones, from the sheet
# (FIR, number, window) and the drop-zone maps (the charted area). Each launch joins its GCAT record by the tag nfc.py
# gave it; a launch with none joins one here (same vehicle within NFC_HOURS at any Chinese site, else within
# NFC_SLIP_HOURS at the same site, as a map named by the planned time would); the rest stand as records of their own.

NFC_HOURS = 3
NFC_SLIP_HOURS = 72
NFC_AGREE_NM = 5      # a charted area within this of the charted area for the same NOTAM agrees with it
NFC_LICENCE_FILE = "data/NOTAMFORCHINA-LICENSE.txt"   # the site's copy of history/NOTAMFORCHINA-LICENSE.txt
NFC_SITE_CODE = {"Jiuquan": "JQ", "Xichang": "XSC", "Taiyuan": "TYSC", "Wenchang": "WEN", "Hainan commercial": "HCSLS"}


def _veh_key(v: str | None) -> str:
    """A vehicle name for comparing: GCAT lists LM-11S as LM-11 and Zhuque-2E as Zhuque-2."""
    return re.sub(r"(?<=\d)[SE]$", "", v or P.NOT_KNOWN)


def _other_vehicle(a: str | None, b: str | None) -> bool:
    """True when both vehicles are read and neither name starts with the other ("Pegasus" is "Pegasus XL"); a charted
    name starting "Unknown" is not read."""
    if not a or not b or P.NOT_KNOWN in (a, b) or a.upper().startswith("UNKNOWN"):
        return False
    x, y = _veh_key(a).upper(), _veh_key(b).upper()
    return not (x.startswith(y) or y.startswith(x))


def same_vehicle(a: str | None, b: str | None) -> bool | None:
    """True or False when both names are read; None when either is not known ("LM-6A or 4B" is not read)."""
    if not a or not b or P.NOT_KNOWN in (a, b) or " OR " in a.upper() or " OR " in b.upper():
        return None
    return _veh_key(a) == _veh_key(b)


def nfc_vehicle(x: dict) -> str:
    """Launch's name for a NotamForChina launch's vehicle, read again from the Chinese name (nfc.json written before
    nfc.vehicle read 长征二号F has LM-2 for it)."""
    raw = NFC.vehicle(x.get("vehicle_zh")) or x.get("vehicle")
    return P.vehicle(raw) if raw else P.NOT_KNOWN


def ring_gap_nm(a: list, b: list) -> float:
    """The farthest any corner of either ring lies from the nearest corner of the other, NM."""
    return round(max(history._ring_distance_nm(a, b), history._ring_distance_nm(b, a)), 1)


def fold_windows(notices: list[dict]) -> list[dict]:
    """A launch's notices with each sheet row (FIR, window; a number from late 2023) folded into the area charted for
    it on the map, where that FIR has exactly one charted area and one sheet row (older maps name the FIR only, and
    one area may span two FIRs, "ZHWH/ZPKM"). Anything less certain stays a notice of its own."""
    out = [dict(n) for n in notices if n.get("ring")]
    rows = [n for n in notices if not n.get("ring")]
    charted: dict[str, list[int]] = {}
    for i, n in enumerate(out):
        for f in (n.get("fir") or "").split("/"):
            if f:
                charted.setdefault(f, []).append(i)
    per_fir: dict[str, int] = {}
    for n in rows:
        per_fir[n.get("fir") or ""] = per_fir.get(n.get("fir") or "", 0) + 1
    rest = []
    for n in rows:
        hits = charted.get(n.get("fir") or "", [])
        c = out[hits[0]] if len(hits) == 1 and per_fir[n.get("fir") or ""] == 1 else None
        if c is None or (c.get("number") and n.get("number") and c["number"] != n["number"]):
            rest.append(dict(n))
            continue
        c["number"] = c.get("number") or n.get("number")
        if n.get("start"):
            c["start"] = min(x for x in (c.get("start"), n["start"]) if x)
            c["end"] = max(x for x in (c.get("end"), n.get("end")) if x) if (c.get("end") or n.get("end")) else None
        c["folded"] = True
    return out + rest


def nfc_notices(launches: list[dict], chart_events: list[dict]) -> list[dict]:
    """One list of notices for a record from its NotamForChina launches (a launch can be in it twice: three map files
    for one flight), each notice once. A notice that is charted under the same NOTAM number stays here
    only as a check (`chart`, and `gap_nm` from the charted area), without a ring to draw unless none is charted."""
    chart_idx: dict[str, dict] = {}
    for num, firs in chart_notice_keys(chart_events):
        chart_idx.setdefault(num, {}).setdefault(firs, set()).add(num)
    chart_rings: dict[str, list] = {}
    for e in chart_events:
        for a in e.get("areas") or []:
            if a.get("notam") and a.get("ring"):
                chart_rings.setdefault(a["notam"], []).append(a["ring"])
    out, by_key = [], {}
    for x in launches:
        for n in fold_windows(x.get("notices") or []):
            key = ((n["number"], n.get("fir")) if n.get("number") else
                   (n.get("fir"), n.get("label"), tuple((n.get("ring") or [[None]])[0]), n.get("start")))
            if key in by_key:
                old = by_key[key]
                for k in ("ring", "start", "end", "fir", "label"):
                    if not old.get(k) and n.get(k):
                        old[k] = n[k]
                continue
            rec = {k: n.get(k) for k in ("fir", "number", "label", "start", "end", "ring")}
            if n.get("folded"):
                rec["folded"] = True
            by_key[key] = rec
            out.append(rec)
    for n in out:
        if n["number"] and _key_hits((n["number"], _firs(n.get("fir"))), chart_idx):
            n["chart"] = True
            if n["ring"] and chart_rings.get(n["number"]):
                n["gap_nm"] = min(ring_gap_nm(n["ring"], t) for t in chart_rings[n["number"]])
                n["ring"] = None
        if not n["ring"]:
            n.pop("ring")
    return out


def _firs(*vals) -> frozenset:
    return frozenset(f for v in vals for f in re.split(r"[/\s,]+", v or "") if f)


def chart_notice_keys(evs: list[dict]) -> set[tuple]:
    """(number, FIRs) of every numbered notice on the charted events (the Q-line's FIR and the A) locations)."""
    return {(n["number"], _firs((n.get("q") or {}).get("fir"), *(n.get("locations") or [])))
            for e in evs for n in e.get("notams") or [] if n.get("number")}


def nfc_notice_keys(x: dict) -> set[tuple]:
    return {(n["number"], _firs(n.get("fir"))) for n in x.get("notices") or [] if n.get("number")}


def _key_hits(k: tuple, idx: dict[str, dict]) -> set:
    """What `idx` ({number: {FIRs: values}}) holds under the same number and a shared FIR. A number is unique only
    within a FIR's series, so it matches across FIRs only where one side names none."""
    out = set()
    for firs, vals in (idx.get(k[0]) or {}).items():
        if not firs or not k[1] or firs & k[1]:
            out |= vals
    return out


def _nfc_join(doc: dict | None, gcat_recs: list[dict], g_info: dict) -> tuple[dict, list, dict]:
    """{GCAT tag: [NotamForChina launches]}, the launches that join none, and counts. A launch with no time has no
    place in a list by time and is left out (counted)."""
    counts = {"launches": 0, "undated": 0, "by_tag": 0, "tag_refused": 0, "by_vehicle": 0, "by_slip": 0}
    if not doc:
        return {}, [], counts
    cn = [g for g in gcat_recs if g.get("country") == "CN" or (g.get("site") or {}).get("country") == "CN"]
    by_tag = {g["tag"]: g for g in gcat_recs}
    joined: dict[str, list] = {}
    pending = []
    for x in doc.get("launches") or []:
        counts["launches"] += 1
        if not x.get("time"):
            counts["undated"] += 1
            continue
        x = {**x, "veh": nfc_vehicle(x)}
        g = by_tag.get(x.get("gcat") or "")
        if g and same_vehicle(x["veh"], g_info[g["id"]]["vehicle"]) is False:
            counts["tag_refused"] += 1  # two of the sheet's blocks a few minutes apart, one with another vehicle
            g = None
        if g:
            counts["by_tag"] += 1
            joined.setdefault(g["tag"], []).append({**x, "join": {"by": "tag"}})
        else:
            pending.append(x)
    loose = []
    for x in pending:
        best = None
        codes = NFC.GCAT_SITES.get(x.get("site") or "", set())
        for g in cn:
            h = _hours_apart(x["time"], g_info[g["id"]]["time"])
            if h is None or not same_vehicle(x["veh"], g_info[g["id"]]["vehicle"]):
                continue
            if h <= NFC_HOURS:
                cand = (0, h, g)
            elif h <= NFC_SLIP_HOURS and g.get("site_code") in codes and g["tag"] not in joined:
                cand = (1, h, g)
            else:
                continue
            if best is None or cand[:2] < best[:2]:
                best = cand
        if best:
            slip, h, g = best
            counts["by_slip" if slip else "by_vehicle"] += 1
            joined.setdefault(g["tag"], []).append({**x, "join": {"by": "slip" if slip else "vehicle", "hours": round(h, 1)}})
        else:
            loose.append(x)
    return joined, loose, counts


# ---------- Joey0609/notams ----------
# history/joey.json (joey.py): launch-related NOTAMs, mostly China's and its downrange FIRs', Dec 2020 onward, with
# their text and areas. Each notice goes to one record:
#   1. by NOTAM: a notice that the charted notices or NotamForChina hold (same number and a shared FIR; a number is
#      unique only within a FIR's series) goes to the record that holds it;
#   2. by window and place: else to the GCAT launch whose time lies inside the notice's window, within JOEY_TOL_HOURS
#      either side, whose country is the notice's (the state its text names, else the issuing FIR's state when GCAT
#      lists launches by that state; else any), and whose pad lies within JOEY_NM of the notice's area. Of several,
#      the nearest pad, then the nearest in time; a window over JOEY_LONG_HOURS (a launch period weeks long) joins
#      only when one launch qualifies. A notice with no area joins only when one launch qualifies.
#   3. else it joins nothing and is counted (`joey_unjoined`); no record is made for it.
# On a record the charted text comes first: a Joey notice that is also charted is a check under it (`chart`, and
# `gap_nm` from the charted area) and its area is not drawn. NotamForChina's notice that Joey also holds becomes the
# check (`joey`, `gap_nm`) and Joey's area is drawn, since Joey's comes with the notice's text.

JOEY_TOL_HOURS = 2     # replaced notices for a slip of an hour or two stay with the launch
JOEY_NM = 5000         # Jiuquan to the Australian FIR's drop zones for Chinese launches is 4,300-4,900 NM
JOEY_LONG_HOURS = 7 * 24
JOEY_LICENCE_FILE = "data/JOEY-NOTAMS-LICENSE.txt"   # the site's copy of history/JOEY-NOTAMS-LICENSE.txt


def joey_firs(n: dict) -> frozenset:
    return _firs(n.get("fir") if n.get("fir") != "ZXXX" else None, *(n.get("locations") or []))


def joey_actor(n: dict, launching: set) -> str | None:
    """The state a notice is for: the one its text names, else the issuing FIR's state if it launches."""
    if n.get("named_states"):
        return n["named_states"][0]
    return n.get("issuing_state") if n.get("issuing_state") in launching else None


def _ring_centres(n: dict) -> list[tuple[float, float]]:
    return [notam.centroid(r) for r in n.get("rings") or [] if len(r) >= 3]


def joey_window_join(n: dict, gcat_recs: list[dict], g_info: dict, launching: set):
    """(GCAT tag, join) for a notice by window and place (rule 2 above), or (None, reason)."""
    start, end = _dt(n.get("start")), _dt(n.get("end"))
    if not (start and end):
        return None, "no window"
    lo, hi = start - timedelta(hours=JOEY_TOL_HOURS), end + timedelta(hours=JOEY_TOL_HOURS)
    actor = joey_actor(n, launching)
    centres = _ring_centres(n)
    cands = []
    for g in gcat_recs:
        gi = g_info[g["id"]]
        t = _dt(gi["time"])
        if not t or not (lo <= t <= hi) or not g.get("time"):
            continue
        if actor and g.get("country") != actor:
            continue
        d = None
        if centres and gi["pad"]:
            d = min(notam.haversine_nm(la, lo_, gi["pad"][1], gi["pad"][0]) for la, lo_ in centres)
            if d > JOEY_NM:
                continue
        cands.append((d if d is not None else 0, abs((t - start).total_seconds()) / 3600, g, d))
    if not cands:
        return None, "no launch in the window"
    long = (end - start).total_seconds() / 3600 > JOEY_LONG_HOURS
    if len(cands) > 1 and (long or not centres):
        return None, "several launches in the window"
    best = min(cands, key=lambda c: (c[0], c[1]))
    t = _dt(g_info[best[2]["id"]]["time"])
    return best[2]["tag"], {"by": "window", "nm": None if best[3] is None else round(best[3]),
                            "after_start_h": round((t - start).total_seconds() / 3600, 2),
                            "candidates": len(cands)}


def joey_notices(xs: list[dict], chart_events: list[dict]) -> list[dict]:
    """A record's Joey notices for the page, each once; one that is charted is a check (`chart`, `gap_nm`)."""
    chart_idx: dict[str, dict] = {}
    for num, firs in chart_notice_keys(chart_events):
        chart_idx.setdefault(num, {}).setdefault(firs, set()).add(num)
    chart_rings: dict[str, list] = {}
    for e in chart_events:
        for a in e.get("areas") or []:
            if a.get("notam") and a.get("ring"):
                chart_rings.setdefault(a["notam"], []).append(a["ring"])
    out, seen = [], set()
    for n in xs:
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        rec = {k: n.get(k) for k in ("id", "number", "part", "fir", "locations", "q_code", "start", "end", "schedule",
                                     "lower", "upper", "issuing_state", "named_states", "created", "text", "rings")}
        rec["join"] = n.get("join")
        if _key_hits((n["number"], joey_firs(n)), chart_idx):
            rec["chart"] = True
            if rec["rings"] and chart_rings.get(n["number"]):
                rec["gap_nm"] = min(ring_gap_nm(a, t) for a in rec["rings"] for t in chart_rings[n["number"]])
            rec["rings"] = []
            rec.pop("text")  # the charted copy carries it
        if not rec["rings"]:
            rec.pop("rings")
        out.append(rec)
    return out


def joey_over_nfc(nfc_nn: list[dict], joey_nn: list[dict]) -> int:
    """NotamForChina's notices that a Joey notice on the same record also holds become a check under it."""
    idx: dict[str, dict] = {}
    for j in joey_nn:
        if not j.get("chart"):
            idx.setdefault(j["number"], {}).setdefault(joey_firs(j), []).append(j)
    n_over = 0
    for x in nfc_nn:
        if not x.get("number") or x.get("chart"):
            continue
        hits = [j for firs, js in (idx.get(x["number"]) or {}).items()
                if not firs or not _firs(x.get("fir")) or firs & _firs(x.get("fir")) for j in js]
        if not hits:
            continue
        x["joey"] = True
        n_over += 1
        rings = [r for j in hits for r in j.get("rings") or []]
        if x.get("ring") and rings:
            x["gap_nm"] = min(ring_gap_nm(x["ring"], r) for r in rings)
            x.pop("ring")
    return n_over


# ---------- Internet Archive copies (FAA space-operations TFRs, NGA warnings) ----------
# history/wayback.json (wayback.py). Each notice goes to at most one GCAT launch; none makes a record of its own.
#   FAA TFR: a window of at most WB_TFR_MAX_DAYS (a standing months-long area is not one launch's) holding the launch
#   time, WB_TOL_HOURS either side, with the launch's pad within WB_TFR_NM of one of the TFR's areas; nearest in time.
#   A TFR with no area read joins nothing.
#   NGA warning: one of its windows holding the launch time, WB_TOL_HOURS either side, with the pad within JOEY_NM of
#   one of its areas; nearest pad. A warning whose windows span more than WB_LONG_HOURS joins only when one launch
#   qualifies. A charted text naming the same warning ("HYDROPAC 1234/23") marks it `chart`.

WB_TOL_HOURS = 2
WB_TFR_NM = 100
WB_TFR_MAX_DAYS = 7
WB_LONG_HOURS = 7 * 24


def _centre_of(coords: list) -> tuple[float, float] | None:
    return notam.centroid(coords) if len(coords) >= 3 else ((coords[0][1], coords[0][0]) if coords else None)


def _timed(gcat_recs: list[dict], g_info: dict) -> tuple[list, list]:
    """GCAT launches with a time, sorted by it, and their times (for bisect)."""
    rows = sorted(((_dt(g_info[g["id"]]["time"]), g) for g in gcat_recs if g.get("time") and _dt(g_info[g["id"]]["time"])),
                  key=lambda x: x[0])
    return [t for t, _ in rows], [g for _, g in rows]


def _in_windows(timed: tuple[list, list], windows: list[tuple]) -> list[dict]:
    """The launches whose time lies in any window, WB_TOL_HOURS either side, each once."""
    times, recs = timed
    out, seen = [], set()
    for s, e in windows:
        lo = bisect.bisect_left(times, s - timedelta(hours=WB_TOL_HOURS))
        hi = bisect.bisect_right(times, e + timedelta(hours=WB_TOL_HOURS))
        for g in recs[lo:hi]:
            if g["id"] not in seen:
                seen.add(g["id"])
                out.append(g)
    return out


def wayback_join(windows: list[tuple], centres: list, max_nm: float, timed: tuple[list, list], g_info: dict,
                 by_time: bool):
    """(GCAT tag, join) or (None, reason). windows: [(start, end) datetimes]; centres: [(lat, lon)]."""
    if not windows:
        return None, "no window"
    if not centres:
        return None, "no area"
    cands = []
    for g in _in_windows(timed, windows):
        gi = g_info[g["id"]]
        t = _dt(gi["time"])
        if not gi["pad"]:
            continue
        w = next(((s, e) for s, e in windows if s - timedelta(hours=WB_TOL_HOURS) <= t <= e + timedelta(hours=WB_TOL_HOURS)), None)
        if not w:
            continue
        d = min(notam.haversine_nm(la, lo, gi["pad"][1], gi["pad"][0]) for la, lo in centres)
        if d > max_nm:
            continue
        cands.append((abs((t - w[0]).total_seconds()) / 3600, d, g, t - w[0]))
    if not cands:
        return None, "no launch in the window"
    span = (max(e for _, e in windows) - min(s for s, _ in windows)).total_seconds() / 3600
    if len(cands) > 1 and span > WB_LONG_HOURS:
        return None, "several launches in the window"
    best = min(cands, key=lambda c: (c[0], c[1]) if by_time else (c[1], c[0]))
    return best[2]["tag"], {"by": "window", "nm": round(best[1]), "after_start_h": round(best[3].total_seconds() / 3600, 2),
                            "candidates": len(cands)}


def wayback_targets(doc: dict | None, gcat_recs: list[dict], g_info: dict, chart_texts: str) -> tuple[dict, dict]:
    """{GCAT tag: [notices for the page]} and counts."""
    counts = {"tfrs": 0, "tfr_joined": 0, "nga": 0, "nga_joined": 0, "nga_chart": 0,
              "unjoined_why": {}, "joined_by_year": {}, "unjoined_by_year": {}}
    out: dict[str, list] = {}
    if not doc:
        return out, counts

    def tally(kind, when, tag, why):
        y = (when or "????")[:4]
        k = "joined_by_year" if tag else "unjoined_by_year"
        counts[k].setdefault(kind, {})
        counts[k][kind][y] = counts[k][kind].get(y, 0) + 1
        if not tag:
            counts["unjoined_why"][f"{kind}: {why}"] = counts["unjoined_why"].get(f"{kind}: {why}", 0) + 1

    timed = _timed(gcat_recs, g_info)
    # NGA warnings join by the nearest pad within JOEY_NM, too loose to tell a missile or a sounding rocket from an
    # orbital launch in the same window: they join orbital launches only. A TFR (WB_TFR_NM, nearest in time) joins any.
    timed_orbital = _timed([g for g in gcat_recs if g_info[g["id"]].get("kind", P.ORBITAL) == P.ORBITAL], g_info)
    for t in doc.get("tfrs") or []:
        counts["tfrs"] += 1
        s, e = _dt(t.get("start")), _dt(t.get("end"))
        windows = [(s, e)] if s and e and (e - s) <= timedelta(days=WB_TFR_MAX_DAYS) else []
        centres = [c for a in t.get("areas") or [] if (c := _centre_of(a["ring"]))]
        tag, j = wayback_join(windows, centres, WB_TFR_NM, timed, g_info, by_time=True)
        if s and e and not windows:
            tag, j = None, f"window over {WB_TFR_MAX_DAYS} days"
        tally("tfr", t.get("start") or t.get("list_date"), tag, j)
        if tag:
            counts["tfr_joined"] += 1
            out.setdefault(tag, []).append({"kind": "faa-tfr", "id": t["id"], "number": t.get("number"),
                                            "start": t.get("start"), "end": t.get("end"), "location": t.get("location"),
                                            "reason": t.get("reason"), "rings": [a["ring"] for a in t.get("areas") or []],
                                            "source": t.get("source"), "join": j})
    for w in doc.get("nga") or []:
        counts["nga"] += 1
        windows = [(_dt(x["start"]), _dt(x["end"])) for x in w.get("windows") or [] if _dt(x["start"]) and _dt(x["end"])]
        centres = [c for a in w.get("areas") or [] if (c := _centre_of(a["coords"]))]
        tag, j = wayback_join(windows, centres, JOEY_NM, timed_orbital, g_info, by_time=False)
        tally("nga", w.get("issued"), tag, j)
        if tag:
            counts["nga_joined"] += 1
            rec = {"kind": "nga", "id": w["id"], "issued": w.get("issued"), "hazard": w.get("hazard"),
                   "windows": w.get("windows"), "rings": [a["coords"] for a in w.get("areas") or [] if len(a["coords"]) >= 3],
                   "text": w.get("text"), "source": w.get("source"), "join": j}
            if w["id"] in chart_texts:
                rec["chart"] = True
                rec["rings"] = []
                rec.pop("text")
                counts["nga_chart"] += 1
            out.setdefault(tag, []).append(rec)
    return out, counts


# ---------- the index ----------

def _hours_apart(a: str | None, b: str | None) -> float | None:
    x, y = _dt(a), _dt(b)
    return abs((x - y).total_seconds()) / 3600 if x and y else None


def chart_window(e: dict) -> tuple[datetime, datetime] | None:
    """A charted event's window from its name: the time to the end day ("21-30 Apr", to the day's end) or the end time
    ("0900-1700", the next day when it is earlier); a single time is a window of no length."""
    t = _dt(e.get("time"))
    if not t or e.get("time_basis") in (None, "none"):
        return None
    hhmm = e.get("window_end_hhmm")
    hh, mm = (int(hhmm[:2]), int(hhmm[2:])) if hhmm and len(hhmm) == 4 and hhmm.isdigit() else (None, None)
    if hh is not None and (hh > 23 or mm > 59):
        hh = mm = None
    end = t
    if e.get("day_end"):
        y, m = t.year, t.month
        if e["day_end"] < t.day:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        try:
            end = t.replace(year=y, month=m, day=e["day_end"], hour=23 if hh is None else hh, minute=59 if hh is None else mm)
        except ValueError:
            return t, t
    elif hh is not None:
        end = t.replace(hour=hh, minute=mm)
        if end < t:
            end += timedelta(days=1)
    return t, max(t, end)


def _site_reps(points: list[tuple[str, list[float]]]) -> dict[str, list[float]]:
    """Each site's representative pad: the median of the pads seen there (the charted notices, then Launch Library 2)."""
    by: dict[str, list] = {}
    for name, p in points:
        if name and p:
            by.setdefault(name, []).append(p)
    out = {}
    for name, ps in by.items():
        lons = sorted(p[0] for p in ps)
        lats = sorted(p[1] for p in ps)
        out[name] = [round(lons[len(lons) // 2], 4), round(lats[len(lats) // 2], 4)]
    return out


def chart_events(hist: dict) -> list[dict]:
    """The charted events with one record per id: the source holds a few events twice under names that differ only in
    case or spacing ("Arktika-M n°2" and "N°2"); their shapes are joined."""
    out, by = [], {}
    for e in hist.get("events") or []:
        if e["id"] not in by:
            by[e["id"]] = dict(e, areas=list(e.get("areas") or []), paths=list(e.get("paths") or []), copies=1)
            out.append(by[e["id"]])
            continue
        x = by[e["id"]]
        x["areas"] += e.get("areas") or []
        x["paths"] += e.get("paths") or []
        x["pad"] = x.get("pad") or e.get("pad")
        x["copies"] += 1
    return out


def _place(u: dict) -> str:
    """Launch Library 2's pad and location text, for naming the site ("Commercial LC-1" is Hainan commercial)."""
    return f"{u.get('pad') or u.get('pad_name') or ''} {u.get('location') or ''}"


def _closure_list(cl: list[dict]) -> list[dict]:
    return [{"ring": c["ring"], "area": c["area"], "level": c["level"], "window": c.get("window")} for c in cl]


def _closure_areas(pad, cl: list[dict]) -> list[dict]:
    """Stored closures as infer_path() areas, measured from the record's pad and tied by their window."""
    out = []
    for c in cl:
        la, lo = notam.centroid(c["ring"])
        out.append({"ring": c["ring"], "centroid": [round(lo, 4), round(la, 4)], "tie": A.TIE_WINDOW,
                    "notice": c["area"], "windows": [c["window"]] if c.get("window") else []})
    return _bear(pad, out)


def _bear(pad, areas: list[dict]) -> list[dict]:
    """Bearing and distance from the record's pad to each area that has a centroid. Always from the record's pad: a
    charted area carries the bearing the import took from the event's first point, which is stale when the pad was
    moved (`orient_paths`, or GCAT's pad for a pad at no site): the LM-6A of 13 Jan 2026 read its Taiyuan drop zone
    as 11 NM away at 74 deg, from a line start inside it, instead of 190 NM at 255 deg."""
    if not pad:
        return areas
    return [a if not a.get("centroid") else
            {**a, "azimuth": round(history.bearing(pad[1], pad[0], a["centroid"][1], a["centroid"][0]), 1),
             "downrange_nm": round(notam.haversine_nm(pad[1], pad[0], a["centroid"][1], a["centroid"][0]), 1)}
            for a in areas]


def _new_closure_areas(pad, cl: list[dict], listed: list[dict], time: str | None) -> list[dict]:
    """_closure_areas() less those another source already has at that place (within NFC_AGREE_NM) in a window that
    holds the launch: one notice from two sources is one area. An area there whose window misses the launch is
    another event's and does not count."""
    t = _dt(time)
    known = [a["centroid"] for a in listed if a.get("centroid") and A.time_holds(a, t)]
    return [a for a in _closure_areas(pad, cl)
            if not any(notam.haversine_nm(a["centroid"][1], a["centroid"][0], c[1], c[0]) <= NFC_AGREE_NM for c in known)]


# ---------- NASASpaceflight forum threads (nsf.py: NotamForChina's link list; the forum is never read) ----------
# A thread whose title gives a date joins a Chinese launch (record actor CN, launched): with a UTC time, the nearest
# launch within NSF_HOURS of it whose vehicle does not differ (LM-11H is LM-11); without one, the only launch that
# day (UTC, a day either side for the title's local date) of that vehicle that also shares a payload word with the
# title (an untimed title often carries a planned date that slipped: "Zhongxing-26 - CZ-7A - January 9, 2023" is not
# Shijian-23 on CZ-7A that night). A thread already linked from the launch's charted notices is not repeated.
# Undated threads (rumours, plans, general discussion) join nothing.
NSF_HOURS = 3
_NSF_GENERIC = {"and", "others", "other", "launch", "sat", "sats", "satellite", "satellites", "the", "with", "test",
                "long", "march", "maiden", "flight", "live", "failure", "mission", "net", "rideshare"}


def _words(*texts) -> set:
    return {w for t in texts for w in re.findall(r"[a-z]{3,}", (t or "").lower())} - _NSF_GENERIC


def _payload_words(r: dict) -> set:
    return _words(r.get("payload"), r.get("label"), *((r.get("payloads") or {}).get("names") or []))


def nsf_join(recs: list[dict], doc: dict | None, chart_topics: dict[str, set]) -> dict:
    if not doc:
        return {}
    cn = [(r, _dt(r["time"])) for r in recs if r.get("actor") == "CN" and r.get("status") == "launched" and r.get("time")]
    cn = [(r, t) for r, t in cn if t]
    counts = {"links": len(doc.get("links") or []), "dated": 0, "joined": 0, "already_charted": 0}
    for x in doc.get("links") or []:
        if not x.get("date"):
            continue
        counts["dated"] += 1
        day = datetime.fromisoformat(x["date"]).replace(tzinfo=timezone.utc)
        best = None
        if x.get("time"):
            at = day + timedelta(hours=int(x["time"][:2]), minutes=int(x["time"][3:]))
            c = [(abs((t - at).total_seconds()) / 3600, r) for r, t in cn
                 if not _other_vehicle(x.get("vehicle"), P.vehicle(r.get("vehicle")))]
            c = sorted((h, r["id"], r) for h, r in c if h <= NSF_HOURS)
            best = c[0][2] if c else None
        elif x.get("vehicle"):
            words = _words(re.split(r"\s+-\s+|,", x["title"])[0])
            c = [r for r, t in cn if abs((t.date() - day.date()).days) <= 1 and r.get("vehicle")
                 and not _other_vehicle(x["vehicle"], P.vehicle(r.get("vehicle"))) and words & _payload_words(r)]
            same_day = [r for r in c if _dt(r["time"]).date() == day.date()]
            best = same_day[0] if len(same_day) == 1 else c[0] if len(c) == 1 else None
        if not best:
            continue
        if x["topic"] in chart_topics.get(best["id"], set()):
            counts["already_charted"] += 1
            continue
        best.setdefault("forum", []).append({"url": x["url"], "title": x["title"]})
        counts["joined"] += 1
    counts["records"] = sum(1 for r in recs if r.get("forum"))
    return counts


def build_index(hist: dict, ledger: dict, upcoming: list[dict], corridors: list[dict], now: str,
                nfc_doc: dict | None = None, joey_doc: dict | None = None, wayback_doc: dict | None = None,
                world: "overfly.World | None" = None, nsf_doc: dict | None = None,
                site_fixes: list[dict] | None = None, published: list[dict] | None = None,
                live: dict | None = None, owner_names: dict | None = None) -> dict:
    """The History tab's list (data/launches.json). `world` (overfly.World): when given, each record with a flight
    path gets `over`, the countries its ground track crosses (overfly.py). `site_fixes`: history/site_fixes.json's
    list (apply_site_fixes()). `published`: history/published_notices.json's list, closure areas no other source
    carries, each checked against a published copy of its notice and given to its GCAT launch by tag
    (`published_notices`; their areas are the launch's own, `ascent.TIE_NOTAM`). `live`: {matches, areas} of this
    run's snapshot, for the scheduled launches' paths through their live closure areas (live_paths())."""
    pub_by: dict[str, list] = {}
    for x in published or []:
        pub_by.setdefault(x["tag"], []).append(x)
    sites = ledger.get("sites") or {}
    nowdt = _dt(now)
    events = [orient_paths(e, sites) for e in chart_events(hist)]
    all_copies: dict[str, list] = {}
    for e in hist.get("events") or []:
        all_copies.setdefault(e["id"], []).append(e)
    bands_by_site = site_bands(corridors, sites)
    stored: dict = {}   # one per ring: a ring stored under both id forms, should a notice's order change, is one area
    for c in ledger.get("closures") or []:
        _keep_closure(stored, (c["ll2"], c["area"], _ring_tag(c.get("ring"))), c)
    closures_by_ll2: dict[str, list] = {}
    for c in stored.values():
        closures_by_ll2.setdefault(c["ll2"], []).append(c)
    gcat, fixed = apply_site_fixes([r for r in ledger.get("launches") or [] if r.get("source") == "gcat"], sites,
                                   site_fixes)
    flown = [r for r in ledger.get("launches") or [] if r.get("source") == "ll2"]
    ll2_all = [u for u in upcoming or [] if u.get("id")]

    chart_site = {e["id"]: nearest_site(e["pad"][1], e["pad"][0], sites) for e in events if e.get("pad")}
    reps = _site_reps([(chart_site.get(e["id"]), e.get("pad")) for e in events] +
                      [(nearest_site(u["lat"], u["lon"], sites, place=_place(u)), [u["lon"], u["lat"]])
                       for u in ll2_all if u.get("lat") is not None])

    def g_site(g: dict) -> str | None:
        return (sites.get(g.get("site_code") or "") or {}).get("name") or P.site_name((g.get("site") or {}).get("name"))

    def g_pad(g: dict):
        name = g_site(g)
        if name in reps:
            return reps[name]
        s = g.get("site") or sites.get(g.get("site_code") or "")
        return [s["lon"], s["lat"]] if s and s.get("lat") is not None else None

    g_info = {}
    for g in gcat:
        progs, mtype = P.programmes(g.get("flight"), g.get("mission"), *g["payloads"]["names"],
                                    owners=g["payloads"].get("owners"))
        kind = P.launch_kind(g.get("kind"), g.get("category"))
        g_info[g["id"]] = {"site": g_site(g), "pad": g_pad(g), "progs": progs, "kind": kind,
                           "mtype": mtype if kind == P.ORBITAL else P.kind_mtype(kind, mtype, g.get("category")),
                           "vehicle": P.vehicle(g.get("vehicle_raw")),
                           "time": g.get("time") or (g["date"] + "T12:00:00Z")}

    # Charted events <-> GCAT launches. Pass 1: within MATCH_HOURS (a day when either has no time), near in place or
    # of the same country; a same-country launch farther than MATCH_NM only when the vehicles do not differ
    # (`_other_vehicle`; an ICBM charted at Wenchang joined Jiuquan's Lijian-1 before). Pass 2, for the rest: within
    # 72 hours, near in place and of the same vehicle or programme (a charted name often carries the scheduled time: a day early, or before a slip). A missile fired in combat
    # joins no charted event; any other suborbital launch joins in pass 1 only when near in place (a country's
    # missile firings are too many for "same country" to tell them apart). A charted event whose pad is at no
    # launch site (its path drawn from a point downrange, as Starship Flight 6 of 19 Nov 2024 from 219 NM out in
    # the Gulf) has no place to measure from: in pass 1 the same vehicle or programme stands in for "near", and the
    # record takes GCAT's pad. A sea or air launch that joins as before keeps its charted point.
    def candidates(e, second: bool):
        e_progs = set(P.programmes(e.get("payload"), e.get("label"))[0])
        e_veh = P.vehicle(e.get("vehicle"))
        no_site = bool(e.get("pad")) and chart_site.get(e["id"]) is None
        for g in gcat:
            gi = g_info[g["id"]]
            if gi["kind"] == P.COMBAT_LAUNCH:
                continue
            h = _hours_apart(e["time"], gi["time"])
            if h is None:
                continue
            sub = gi["kind"] != P.ORBITAL
            d = notam.haversine_nm(e["pad"][1], e["pad"][0], gi["pad"][1], gi["pad"][0]) if (e.get("pad") and gi["pad"]) else None
            same = (e_veh != P.NOT_KNOWN and e_veh == gi["vehicle"]) or bool(e_progs & set(gi["progs"]))
            if not second:
                tol = MATCH_HOURS if (e["time_basis"] == "time" and g.get("time")) else 30
                country = bool(not sub and e.get("actor") and e["actor"] == g.get("country"))
                near = (d is not None and d <= MATCH_NM) or (country and (d is None or same or not _other_vehicle(e_veh, gi["vehicle"])))
                by_vehicle = not near and no_site and same
                if h > tol or not (near or by_vehicle):
                    continue
            elif h > 72 or d is None or d > MATCH_NM or not same:
                continue
            info = {"hours": round(h, 1), "nm": None if d is None else round(d), "same": same, "pass": 2 if second else 1}
            if not second and by_vehicle:
                info["pad_at_no_site"] = True
            yield h + (0 if same else 1.5) + (d or 0) / 400, g["id"], info

    # The charted map is a notice source: its events never make a launch of their own. Each takes its best GCAT
    # launch, and several placemarks of one launch (one per notice, say) all join it. First within 3 h and near in
    # place (pass 1). Then by NOTAM (pass 0): an event holding a notice (same number, a shared FIR) that NotamForChina
    # lists for one GCAT launch joins it (the charted name or NotamForChina's sheet is a year or a month out now and
    # then, and the charted vehicle is a guess made before the launch); else one that Joey0609/notams' window join
    # puts on one GCAT launch, unless the vehicles differ. Then within 72 h, near and of the same vehicle (pass 2),
    # then by time and vehicle when the event has no pad (pass 4). An event no launch joins is a notice set.
    nfc_by_tag, nfc_loose, nfc_counts = _nfc_join(nfc_doc, gcat, g_info)
    chart_keys = {e["id"]: chart_notice_keys(all_copies.get(e["id"], [e])) for e in events}
    launching = {g.get("country") for g in gcat if g.get("country") and g_info[g["id"]]["kind"] == P.ORBITAL}
    # A missile fired in combat is announced by no notice: the archived TFRs and warnings join only the other GCAT
    # launches. Joey's notices are launch NOTAMs joined by window and a pad within JOEY_NM, too loose to tell a
    # missile or a sounding rocket from an orbital launch in the same window: by window they join orbital launches.
    gcat_noticed = [g for g in gcat if g_info[g["id"]]["kind"] != P.COMBAT_LAUNCH]
    gcat_orbital = [g for g in gcat if g_info[g["id"]]["kind"] == P.ORBITAL]
    joey_list = (joey_doc or {}).get("notices") or []
    joey_win = [joey_window_join(n, gcat_orbital, g_info, launching) for n in joey_list]
    nfc_tags: dict[str, dict] = {}
    for tag, xs in nfc_by_tag.items():
        for x in xs:
            for k in nfc_notice_keys(x):
                nfc_tags.setdefault(k[0], {}).setdefault(k[1], set()).add(tag)
    joey_tags: dict[str, dict] = {}
    for n, (tag, _) in zip(joey_list, joey_win):
        if tag:
            joey_tags.setdefault(n["number"], {}).setdefault(joey_firs(n), set()).add(tag)
    chart_to_g, join = {}, {}
    usable = [e for e in events if e["kind"] in ("launch", "upcoming") and e.get("time") and e["time_basis"] != "none"]

    def by_place(second: bool):
        for e in usable:
            if e["id"] in chart_to_g:
                continue
            best = min(candidates(e, second), default=None, key=lambda c: c[0])
            if best:
                chart_to_g[e["id"]], join[e["id"]] = best[1], best[2]

    by_place(False)
    by_notam_counts = {"nfc": 0, "joey": 0, "vehicle_refused": 0, "several": 0}
    for e in events:
        if e["id"] in chart_to_g or not chart_keys[e["id"]]:
            continue
        hits, via = set(), None
        for via, idx in (("nfc", nfc_tags), ("joey", joey_tags)):
            hits = {t for k in chart_keys[e["id"]] for t in _key_hits(k, idx)}
            if hits:
                break
        if len(hits) != 1:
            by_notam_counts["several"] += len(hits) > 1
            continue
        gid = "gcat:" + next(iter(hits))
        sv = same_vehicle(P.vehicle(e.get("vehicle")), g_info[gid]["vehicle"])
        if sv is False and via == "joey":
            by_notam_counts["vehicle_refused"] += 1
            continue
        h = _hours_apart(e.get("time"), g_info[gid]["time"])
        chart_to_g[e["id"]] = gid
        join[e["id"]] = {"hours": None if h is None else round(h, 1), "nm": None, "pass": 0, "by": "notam", "via": via,
                         "same": bool(sv)}
        by_notam_counts[via] += 1
    nfc_counts["chart_by_notam"] = by_notam_counts["nfc"]
    by_place(True)
    gby = {g["id"]: g for g in gcat}

    # Pass 4: a charted event with no pad (no line was charted for it, and the pad is a line's first point) has no
    # place for passes 1-3 to measure from. It joins the GCAT launch of the same vehicle (else, where neither vehicle
    # differs, the same programme) and the same country, nearest in time, from NOPAD_EARLY_HOURS before its window
    # opens to NOPAD_HOURS after it closes (a charted name often carries a planned time a launch slipped from; a
    # launch before the window's notices is not theirs). A return or reentry joins nothing.
    nopad = 0
    for e in events:
        if e["id"] in chart_to_g or e.get("pad") or e["kind"] not in ("launch", "upcoming", "unknown"):
            continue
        win = chart_window(e)
        e_veh = P.vehicle(e.get("vehicle"))
        e_progs, e_mtype = P.programmes(e.get("payload"), e.get("label"))
        if not win or e_mtype == P.REENTRY or e.get("cancelled"):
            continue
        best = None
        for g in gcat:
            gi = g_info[g["id"]]
            t = _dt(gi["time"])
            if gi["kind"] == P.COMBAT_LAUNCH or not t or (e.get("actor") and g.get("country") and e["actor"] != g["country"]):
                continue
            sv = same_vehicle(e_veh, gi["vehicle"])
            if not (sv or (sv is None and set(e_progs) & set(gi["progs"]))):
                continue
            lo, hi = win
            h = (lo - t).total_seconds() / 3600 if t < lo else (t - hi).total_seconds() / 3600 if t > hi else 0.0
            if (t < lo and h > NOPAD_EARLY_HOURS) or (t > hi and h > NOPAD_HOURS):
                continue
            if best is None or h < best[0]:
                best = (h, g["id"], bool(sv))
        if best:
            chart_to_g[e["id"]] = best[1]
            join[e["id"]] = {"hours": round(best[0], 1), "nm": None, "pass": 4, "same": True, "no_pad": True,
                             "by": "vehicle" if best[2] else "programme"}
            nopad += 1
    g_to_chart: dict[str, list] = {}
    for e in events:
        if e["id"] in chart_to_g:
            g_to_chart.setdefault(chart_to_g[e["id"]], []).append(e)

    chart_by_key: dict[str, dict] = {}
    for eid, ks in chart_keys.items():
        for k in ks:
            chart_by_key.setdefault(k[0], {}).setdefault(k[1], set()).add(eid)
    # A NotamForChina launch that joined no GCAT launch joins the charted event holding one of its notices (its
    # notices go to the record that event's launch makes, or to the event's notice set). Else, before ledger_since
    # (where GCAT's list here does not reach), one unjoined charted event within NFC_HOURS, not of another vehicle,
    # at the same site when the vehicle is not read. Else a record of its own.
    nfc_by_chart: dict[str, list] = {}
    chart_free = [e for e in usable if e["id"] not in chart_to_g and (e.get("actor") or "CN") == "CN"]
    left, by_notam = [], 0
    for x in nfc_loose:
        hits = {eid for k in nfc_notice_keys(x) for eid in _key_hits(k, chart_by_key)}
        if len(hits) == 1:
            nfc_by_chart.setdefault(hits.pop(), []).append({**x, "join": {"by": "notam"}})
            by_notam += 1
            continue
        best = None
        if x["time"][:10] < (ledger.get("since") or LEDGER_SINCE):
            for e in chart_free:
                h = _hours_apart(x["time"], e["time"])
                sv = same_vehicle(x["veh"], P.vehicle(e.get("vehicle")))
                if h is None or h > NFC_HOURS or sv is False:
                    continue
                if sv is None and chart_site.get(e["id"]) != (sites.get(NFC_SITE_CODE.get(x.get("site") or "", "")) or {}).get("name"):
                    continue
                if best is None or h < best[0]:
                    best = (h, e)
        if best:
            nfc_by_chart.setdefault(best[1]["id"], []).append({**x, "join": {"by": "chart", "hours": round(best[0], 1)}})
        else:
            left.append(x)
    nfc_counts["by_notam"] = by_notam
    nfc_counts["by_chart"] = len(nfc_loose) - len(left) - by_notam
    nfc_loose = left

    # Joey0609/notams (see the Joey section above): each notice to a target, "chart:<event id>", "gcat:<tag>" or
    # "nfc:<NotamForChina launch id>", which the record loops below collect.
    nfc_key_target: dict[str, dict] = {}
    for tag, xs in nfc_by_tag.items():
        for x in xs:
            for k in nfc_notice_keys(x):
                nfc_key_target.setdefault(k[0], {}).setdefault(k[1], set()).add("gcat:" + tag)
    for eid, xs in nfc_by_chart.items():
        for x in xs:
            for k in nfc_notice_keys(x):
                nfc_key_target.setdefault(k[0], {}).setdefault(k[1], set()).add("chart:" + eid)
    for x in nfc_loose:
        for k in nfc_notice_keys(x):
            nfc_key_target.setdefault(k[0], {}).setdefault(k[1], set()).add("nfc:" + x["id"])
    joey_by: dict[str, list] = {}
    joey_counts = {"notices": 0, "by_notam_chart": 0, "by_notam_nfc": 0, "by_window": 0, "window_several": 0,
                   "unjoined": 0, "unjoined_by_year": {}, "unjoined_why": {}}
    for n, (tag, j) in zip(joey_list, joey_win):
        joey_counts["notices"] += 1
        key = (n["number"], joey_firs(n))
        hits = {"chart:" + eid for eid in _key_hits(key, chart_by_key)}
        how = "by_notam_chart"
        if not hits:
            hits, how = _key_hits(key, nfc_key_target), "by_notam_nfc"
        if hits:
            joey_by.setdefault(sorted(hits)[0], []).append({**n, "join": {"by": "notam"}})
            joey_counts[how] += 1
            continue
        if tag:
            joey_by.setdefault("gcat:" + tag, []).append({**n, "join": j})
            joey_counts["by_window"] += 1
            joey_counts["window_several"] += j["candidates"] > 1
            continue
        joey_counts["unjoined"] += 1
        y = (n.get("start") or "????")[:4]
        joey_counts["unjoined_by_year"][y] = joey_counts["unjoined_by_year"].get(y, 0) + 1
        joey_counts["unjoined_why"][j] = joey_counts["unjoined_why"].get(j, 0) + 1

    # Internet Archive copies (see that section above): FAA space-operations TFRs and NGA warnings, by GCAT tag.
    chart_texts = " ".join(t for e in hist.get("events") or [] for t in e.get("texts") or [])
    wb_by, wb_counts = wayback_targets(wayback_doc, gcat_noticed, g_info, chart_texts)

    # The inclination of the last launch of the same programme (else the same vehicle, when its recent launches
    # agree) from the same site: for a launch whose own payloads have none yet, and for scheduled launches.
    inc_hist: dict[tuple, list] = {}
    for g in gcat:
        gi = g_info[g["id"]]
        if g.get("inc") and gi["site"] and gi["kind"] == P.ORBITAL:
            for p in gi["progs"]:
                inc_hist.setdefault(("p", gi["site"], p), []).append((gi["time"], g["inc"]))
            inc_hist.setdefault(("v", gi["site"], gi["vehicle"]), []).append((gi["time"], g["inc"]))

    def borrowed_inc(site, progs, veh, before):
        for p in progs or []:
            prior = sorted(x for s in (site, P.SITE_SIBLINGS.get(site)) for x in inc_hist.get(("p", s, p), []) if x[0] < before)
            if prior:
                t, inc = prior[-1]
                return inc, f"inclination {inc:g}° of the last {p} launch from {site} ({t[:10]}, GCAT)"
        prior = sorted(x for x in inc_hist.get(("v", site, veh), []) if x[0] < before)[-5:]
        if len(prior) >= 3 and max(i for _, i in prior) - min(i for _, i in prior) <= 3:
            inc = prior[-1][1]
            return inc, f"inclination {inc:g}° of the last {len(prior)} {veh} launches from {site}, which agree (GCAT)"
        return None, None

    def ll2_link(time: str | None, pad) -> dict | None:
        best = None
        for u in ll2_all + [{**f, "id": f["ll2"], "net": f["time"]} for f in flown]:
            h = _hours_apart(time, u.get("net"))
            if h is None or h > MATCH_HOURS or u.get("lat") is None or not pad:
                continue
            if notam.haversine_nm(pad[1], pad[0], u["lat"], u["lon"]) > MATCH_NM:
                continue
            if best is None or h < best[0]:
                best = (h, u)
        return best[1] if best else None

    recs, used_ll2 = [], set()

    def gcat_extra(r: dict, g: dict):
        """What GCAT says of a launch: a suborbital one's category, apogee and range, an orbital one's orbit
        reached, and a site given with a "?"."""
        if r["kind"] != P.ORBITAL:
            r["gcat_category"] = _dash(g.get("category")) or None
            for k in ("apogee_km", "range_km"):
                if g.get(k) is not None:
                    r[k] = g[k]
        elif g.get("orbit_km"):
            r["orbit_km"] = g["orbit_km"]
        if g.get("site_uncertain"):
            r["site_uncertain"] = True
        if g.get("site_fix"):
            r["site_fix"] = g["site_fix"]

    def ll2_kind(u: dict) -> str:
        """A Launch Library 2 launch's kind: suborbital by its orbit, crewed by its mission type."""
        if P.orbit_class(None, u.get("orbit")) == "Suborbital":
            return P.CREWED_SUB if u.get("mission_type") in ("Tourism", "Human Exploration") else P.SUBORBITAL
        return P.ORBITAL

    def add_nfc(r: dict, xs: list[dict], evs: list[dict]) -> list[dict]:
        """NotamForChina's notices on the record; returns its charted areas to draw (for the path estimate)."""
        if not xs:
            return []
        nn = nfc_notices(xs, evs)
        r["nfc"] = [x["id"] for x in xs]
        r["nfc_join"] = xs[0].get("join")
        r["nfc_notices"] = nn
        r["sources"].append("nfc")
        out = []
        for n in nn:
            if n.get("ring"):
                la, lo = notam.centroid(n["ring"])
                out.append({"ring": n["ring"], "centroid": [round(lo, 4), round(la, 4)], "tie": A.TIE_NOTAM,
                            "notice": "nfc:" + (n.get("number") or str(len(out))),
                            "windows": [[n.get("start"), n.get("end")]] if n.get("start") and n.get("end") else []})
        return out

    def add_wayback(r: dict, tag: str | None) -> list[dict]:
        """The archive copies' notices on the record; returns their areas (for the path estimate)."""
        xs = wb_by.get(tag or "", [])
        if not xs:
            return []
        r["archive_notices"] = [{k: v for k, v in x.items() if not (k == "rings" and not v)} for x in xs]
        r["sources"].append("wayback")
        out = []
        for x in xs:
            ws = ([[w["start"], w["end"]] for w in x.get("windows") or []] if x.get("windows")
                  else [[x.get("start"), x.get("end")]] if x.get("start") and x.get("end") else [])
            for ring in x.get("rings") or []:
                la, lo = notam.centroid(ring)
                out.append({"ring": ring, "centroid": [round(lo, 4), round(la, 4)], "tie": A.TIE_WINDOW,
                            "notice": f"{x['kind']}:{x['id']}", "windows": ws})
        return out

    def add_published(r: dict, tag: str | None) -> list[dict]:
        """history/published_notices.json's notices for the launch; returns their areas (for the path estimate)."""
        xs = pub_by.get(tag or "", [])
        if not xs:
            return []
        r["published_notices"] = [{k: x[k] for k in ("kind", "issuer", "number", "stage", "hazard", "windows", "schedule",
                                                     "note", "ring", "source", "reviewed") if x.get(k)} for x in xs]
        r["sources"].append("published")
        out = []
        for x in xs:
            la, lo = notam.centroid(x["ring"])
            out.append({"ring": x["ring"], "centroid": [round(lo, 4), round(la, 4)], "tie": A.TIE_NOTAM,
                        "notice": "published:" + x["number"], "windows": x.get("windows") or [],
                        "schedule": x.get("schedule")})
        return out

    def add_joey(r: dict, targets: list[str], evs: list[dict]) -> list[dict]:
        """Joey0609/notams' notices on the record; returns its areas to draw (for the path estimate)."""
        xs = [n for t in targets for n in joey_by.get(t, [])]
        if not xs:
            return []
        jn = joey_notices(xs, evs)
        r["joey_notices"] = jn
        r["sources"].append("joey")
        joey_over_nfc(r.get("nfc_notices") or [], jn)
        out = []
        for n in jn:
            for ring in n.get("rings") or []:
                la, lo = notam.centroid(ring)
                out.append({"ring": ring, "centroid": [round(lo, 4), round(la, 4)],
                            "tie": A.TIE_NOTAM if (n.get("join") or {}).get("by") == "notam" else A.TIE_WINDOW,
                            "notice": "joey:" + n["id"], "windows": [[n.get("start"), n.get("end")]],
                            "schedule": n.get("schedule")})
        return out

    def finish(r: dict, *, areas=None, orbit_code=None, path=True):
        if (r["mtype"] == P.MTYPES[-1] and P.payload_unknown(r.get("payload"))
                and all(P.payload_unknown(n) for n in (r.get("payloads") or {}).get("names") or [])):
            r["mtype"] = P.NO_PAYLOAD  # nothing to read, as opposed to a name the table does not know
        site, inc, note = r.get("site"), r.get("inc"), None
        r.setdefault("kind", P.NOT_KNOWN)
        if not path:  # a notice set: no launch to draw
            far = farthest_nm(r.get("pad"), areas)
            if far is not None:
                r["far_nm"] = far
            recs.append(r)
            return
        sub = r["kind"] not in (P.ORBITAL, P.NOT_KNOWN)
        if sub:
            r["orbit"] = "Suborbital"
            path = infer_path(r.get("pad"), site, [], areas=areas, suborbital=True)
            if path:
                r["path"] = path
            recs.append(r)
            return
        if r.get("orbit") in ("GTO / GEO", "Deep space / lunar"):
            inc = None  # a payload's inclination there is its final orbit's, not the launch's
        known_class = (r.get("orbit") in P.CLASS_INC or r.get("orbit") in ("GTO / GEO", "Deep space / lunar")
                       or orbit_code in P.STATION_INC)
        if not inc and r["status"] != "notice" and not known_class:
            inc, note = borrowed_inc(site, r.get("programmes"), r.get("vehicle"), r.get("time") or "9999")
        others: list[dict] = []
        path = infer_path(r.get("pad"), site, bands_by_site.get(site or "", []), areas=areas, inc=inc,
                          inc_note=note, orbit_code=orbit_code, orbit=r.get("orbit"),
                          coarse=coarse_site(r) and r.get("pad_basis") != "chart",
                          time=r.get("time") if r.get("time_basis") == "time" else None, others=others,
                          orbit_km=r.get("orbit_km"))
        if path:
            path["_inc"] = _target_inc(inc, note, orbit_code, r.get("orbit"))[0]
            r["path"] = path
            if world is not None:
                over = overfly.overflight(world, r)
                if over is not None:
                    r["over"] = over
        # Not an area set aside as another event's (its window does not hold the launch, or joined by window alone
        # off the launch's bearing); a later pass, a far splashdown and a TFR round the pad still count.
        far = farthest_nm(r.get("pad"), [a for a in areas or [] if not any(a is x for x in others)])
        if far is not None:
            r["far_nm"] = far
        recs.append(r)

    def attach_ll2(r: dict, link: dict | None):
        if not link:
            return []
        used_ll2.add(link["id"])
        r["ll2"], r["ll2_url"] = link["id"], link.get("ll2_url")
        r["sources"].append("ll2")
        if r["mtype"] == P.MTYPES[-1] and link.get("mission_type") in P.LL2_MTYPE:
            r["mtype"] = P.LL2_MTYPE[link["mission_type"]]
        if r.get("orbit") == P.NOT_KNOWN:
            r["orbit"] = P.orbit_class(None, link.get("orbit"))
        if r.get("kind") == P.NOT_KNOWN:
            r["kind"] = ll2_kind(link)
        cl = closures_holding(closures_by_ll2.get(link["id"], []), r.get("time"))
        if cl:
            r["closures"] = _closure_list(cl)
        return cl

    def chart_parts(grp: list[dict]) -> tuple[list, list]:
        """(areas, every copy of each event) of the charted events in `grp`."""
        return ([dict(a, tie=A.TIE_NOTAM, notice="chart:" + (a.get("notam") or f"{m['id']}#{i}"))
                 for m in grp for i, a in enumerate(m.get("areas") or [])],
                [c for m in grp for c in all_copies.get(m["id"], [m])])

    def attach_chart(r: dict, grp: list[dict]):
        """The charted events joined to a launch record: their ids (the page reads their notices, areas and texts from
        data/history.json), names, how they joined and the time in the charted name."""
        e = max(grp, key=lambda x: (len(x.get("areas") or []), bool(x.get("pad")), -grp.index(x)))
        # GCAT's point for a region, a sea launch or an air launch is coarse (Yangjiang, the Yellow Sea, Kwajalein for
        # a Pegasus): the charted launch point stands when it is within MATCH_NM of GCAT's point, or, for a region, lies
        # nearer the charted areas than GCAT's point does (Gravity-1 of 11 Jan 2024, charted off Haiyang beside its
        # areas, GCAT's Yangjiang point 1,000 NM away). Farther out it is a charted line's far end, drawn back to the pad
        # (the Ceres-1S of 29 May 2024, 488 NM out, its areas round GCAT's Yellow Sea point), and GCAT's point stands.
        if coarse_site(r):
            cents = [a["centroid"] for m in grp for a in (m.get("areas") or []) if a.get("centroid")]
            to_area = lambda q: min((notam.haversine_nm(q[1], q[0], c[1], c[0]) for c in cents), default=None) if q else None
            pt = next((m["pad"] for m in [e] + grp if m.get("pad")), None)
            dc, dg = to_area(pt), to_area(r.get("pad"))
            close = pt and r.get("pad") and notam.haversine_nm(pt[1], pt[0], r["pad"][1], r["pad"][0]) <= MATCH_NM
            region = r.get("pad_basis") == "region" and dc is not None and (dg is None or dc < dg)
            if pt and (close or region):
                r["pad"], r["pad_basis"] = pt, "chart"
        r["chart"] = [m["id"] for m in grp]
        r["chart_labels"] = [m["label"] for m in grp]
        r["sources"].append("chart")
        r["areas"] = sum(len(m.get("areas") or []) for m in grp)
        if join.get(e["id"]):
            r["join"] = join[e["id"]]
        if len(grp) > 1:
            r["chart_joins"] = [join.get(m["id"]) for m in grp]  # in the order of `chart`
        if r["mtype"] in (P.MTYPES[-1], P.NO_PAYLOAD) and r.get("kind") == P.ORBITAL:
            progs, mtype = P.programmes(*[x for m in grp for x in (m.get("payload"), m.get("label"), m.get("extra"))])
            if mtype not in (P.MTYPES[-1], P.NO_PAYLOAD):  # GCAT's names classify nothing; the charted name does
                r["programmes"], r["mtype"], r["mtype_from"] = progs, mtype, "chart"
        h = _hours_apart(e.get("time"), r.get("time"))
        if h is not None and h > 1:
            r["chart_time"] = e.get("time")

    # A charted event no launch joins: a notice set, not a launch. Its name, vehicle and payload are the charted
    # ones; it has no flight path, and the page lists it under "Notices with no identified launch".
    notice_sets = 0
    for e in events:
        if e["id"] in chart_to_g:
            continue
        progs, mtype = P.programmes(e.get("payload"), e.get("label"), e.get("extra"))
        future = bool(nowdt and _dt(e.get("time")) and _dt(e["time"]) > nowdt)
        r = {"id": e["id"], "status": "notice", "notice_set": "later" if future else "none", "time": e.get("time"),
             "time_basis": e.get("time_basis"), "actor": e.get("actor"), "label": e.get("label"),
             "vehicle": P.vehicle(e.get("vehicle")), "payload": e.get("payload"), "programmes": progs, "mtype": mtype,
             "pad": e.get("pad"), "site": chart_site.get(e["id"]), "orbit": P.NOT_KNOWN, "kind": P.NOT_KNOWN,
             "cancelled": e.get("cancelled"), "sources": [], "areas": 0}
        attach_chart(r, [e])
        del r["chart_labels"]
        areas, copies = chart_parts([e])
        extra = add_nfc(r, nfc_by_chart.get(e["id"], []), copies)
        extra += add_joey(r, ["chart:" + e["id"]], copies)
        finish(r, areas=_bear(r.get("pad"), areas + extra), path=False)
        notice_sets += 1

    for g in gcat:
        gi = g_info[g["id"]]
        r = {"id": g["id"], "status": "launched", "time": g.get("time") or (g["date"] + "T00:00:00Z"),
             "time_basis": "time" if g.get("time") else "date", "actor": g.get("country"),
             "label": " · ".join(x for x in (g.get("vehicle_raw"), g.get("flight") or g.get("mission")) if x),
             "vehicle": gi["vehicle"], "gcat_vehicle": g.get("vehicle_raw"), "payload": g.get("mission") or g.get("flight"),
             "flight": g.get("flight"), "programmes": gi["progs"], "mtype": gi["mtype"], "pad": gi["pad"],
             "pad_basis": "region" if (sites.get(g.get("site_code") or "") or {}).get("region") else "site",
             "site": gi["site"], "orbit": P.orbit_class(g.get("category")), "kind": gi["kind"],
             "outcome": g.get("outcome"), "inc": g.get("inc"), "payloads": g.get("payloads"), "sources": ["gcat"],
             "gcat": g["tag"], "areas": 0}
        gcat_extra(r, g)
        link = ll2_link(g.get("time"), gi["pad"]) if g.get("time") else None
        cl = attach_ll2(r, link)
        if link and link.get("lat") is not None:
            r["pad"], r["pad_basis"] = [link["lon"], link["lat"]], "ll2"
        grp = g_to_chart.get(g["id"], [])
        areas, copies = chart_parts(grp)
        if grp:
            attach_chart(r, grp)
        extra = add_nfc(r, nfc_by_tag.get(g["tag"], []) + [x for m in grp for x in nfc_by_chart.get(m["id"], [])], copies)
        extra += add_joey(r, ["gcat:" + g["tag"]] + ["chart:" + m["id"] for m in grp], copies)
        extra += add_wayback(r, g["tag"])
        extra += add_published(r, g["tag"])
        listed = _bear(r["pad"], areas + extra)
        finish(r, areas=_new_closure_areas(r["pad"], cl, listed, r.get("time")) + listed,
               orbit_code=P.gcat_orbit_code(g.get("category")))

    # NotamForChina's launches that joined nothing. Before ledger_since GCAT's list here does not reach, so the
    # launch stands on NotamForChina's word; from then on GCAT lists every orbital launch, so one it does not list
    # is a set of notices with no identified launch (a scrub, a slip past NFC_SLIP_HOURS, or a sheet entry made
    # ahead of a launch).
    since = ledger.get("since") or LEDGER_SINCE
    for x in nfc_loose:
        s = sites.get(NFC_SITE_CODE.get(x.get("site") or "", ""))
        name = s["name"] if s else None
        pad = reps.get(name) or ([s["lon"], s["lat"]] if s else None)
        status = "notice" if x["time"][:10] >= since else "launched"
        where = name or ("a sea launch" if x.get("site") == "sea" else "a site not named")
        r = {"id": x["id"], "status": status, "time": x["time"], "time_basis": "time", "actor": "CN",
             "label": f"{x['veh'] if x['veh'] != P.NOT_KNOWN else 'Launch'} from {where}", "vehicle": x["veh"],
             "payload": None, "programmes": [], "mtype": P.MTYPES[-1], "pad": pad, "pad_basis": "site", "site": name,
             "orbit": P.NOT_KNOWN, "kind": P.NOT_KNOWN if status == "notice" else P.ORBITAL, "sources": [], "areas": 0}
        if status == "notice":
            r["nfc_unmatched"] = True
        extra = add_nfc(r, [x], [])
        extra += add_joey(r, ["nfc:" + x["id"]], [])
        finish(r, areas=_bear(pad, extra))

    def ll2_rec(u: dict, status: str, provisional: bool):
        pad = [u["lon"], u["lat"]] if u.get("lat") is not None else None
        site = nearest_site(u["lat"], u["lon"], sites, place=_place(u)) if pad else None
        progs, mtype = P.programmes(u.get("mission"), u.get("name"))
        if mtype == P.MTYPES[-1] and u.get("mission_type") in P.LL2_MTYPE:
            mtype = P.LL2_MTYPE[u["mission_type"]]
        r = {"id": "ll2:" + u["id"], "status": status, "time": u.get("net"), "time_basis": "net",
             "net_precision": u.get("net_precision"),
             "actor": (u.get("provider_countries") or [None])[0] or u.get("country") or u.get("pad_country"),
             "label": u.get("name"), "vehicle": P.vehicle(u.get("vehicle") or u.get("vehicle_raw")),
             "ll2_vehicle": u.get("vehicle") or u.get("vehicle_raw"), "payload": u.get("mission"), "programmes": progs,
             "mtype": mtype, "pad": pad, "pad_name": u.get("pad") or u.get("pad_name"),
             "site": site or (u.get("location") or "").split(",")[0] or None, "orbit": P.orbit_class(None, u.get("orbit")),
             "ll2_status": u.get("status"), "provider": u.get("provider"), "kind": ll2_kind(u), "sources": ["ll2"], "ll2": u["id"],
             "ll2_url": u.get("ll2_url"), "areas": 0}
        if provisional:
            r["provisional"] = True
        cl = closures_holding(closures_by_ll2.get(u["id"], []), u.get("net"), u.get("net_precision"))
        if cl:
            r["closures"] = _closure_list(cl)
        if status == "upcoming" and nowdt and _dt(u.get("net")) and _dt(u["net"]) < nowdt:
            r["net_passed"] = True
        return r, cl

    for f in flown:
        if f["ll2"] in used_ll2:
            continue
        used_ll2.add(f["ll2"])
        r, cl = ll2_rec({**f, "id": f["ll2"], "net": f["time"]}, "launched", True)
        finish(r, areas=_closure_areas(r.get("pad"), cl))
    for u in ll2_all:
        if u["id"] in used_ll2 or u.get("status") in LL2_FLOWN:
            continue
        r, cl = ll2_rec(u, "upcoming", False)
        finish(r, areas=cl)

    borrow_paths(recs, world)
    live_n = live_paths(recs, (live or {}).get("matches") or [], (live or {}).get("areas") or [], bands_by_site, world)
    recs.sort(key=lambda r: (r.get("time") or "0000", r["id"]))
    kinds = {k: sum(1 for r in recs if r.get("kind") == k) for k in P.KINDS}
    gcat_kinds = {k: sum(1 for gi in g_info.values() if gi["kind"] == k) for k in P.KINDS if k != P.NOT_KNOWN}
    counts = {"chart": len(events), "gcat": len(gcat), "gcat_kinds": gcat_kinds, "kinds": kinds,
              "chart_joined": len(chart_to_g), "chart_by_notam": by_notam_counts, "chart_no_pad": nopad,
              "chart_notice_sets": notice_sets, "gcat_joined": len(g_to_chart),
              "provisional": sum(1 for r in recs if r.get("provisional")),
              "upcoming": sum(1 for r in recs if r["status"] == "upcoming"),
              "paths": {"estimated": sum(1 for r in recs if r.get("path")), "live": live_n}}
    if nfc_doc:
        nn = [n for r in recs for n in r.get("nfc_notices") or []]
        counts["nfc"] = {**nfc_counts, "own_records": len(nfc_loose),
                         "own_launched": sum(1 for x in nfc_loose if x["time"][:10] < since),
                         "records": sum(1 for r in recs if r.get("nfc")), "notices": len(nn),
                         "charted": sum(1 for n in nn if n.get("ring")), "chart_held": sum(1 for n in nn if n.get("chart")),
                         "chart_disagree": sum(1 for n in nn if (n.get("gap_nm") or 0) > NFC_AGREE_NM),
                         "folded": sum(1 for n in nn if n.get("folded"))}
    if joey_doc:
        jn = [n for r in recs for n in r.get("joey_notices") or []]
        counts["joey"] = {**joey_counts, "records": sum(1 for r in recs if r.get("joey_notices")),
                          "on_records": len(jn), "drawn": sum(1 for n in jn if n.get("rings")),
                          "chart_held": sum(1 for n in jn if n.get("chart")),
                          "chart_disagree": sum(1 for n in jn if (n.get("gap_nm") or 0) > NFC_AGREE_NM),
                          "nfc_held": sum(1 for r in recs for x in r.get("nfc_notices") or [] if x.get("joey"))}
    if wayback_doc:
        counts["wayback"] = {**wb_counts, "records": sum(1 for r in recs if r.get("archive_notices"))}
    if nsf_doc:
        topics = {r["id"]: {m.group(1) for eid in r.get("chart") or [] for e in all_copies.get(eid, [])
                            for u in e.get("links") or [] for m in [re.search(r"[?&;]topic=(\d+)", u)] if m}
                  for r in recs if r.get("chart")}
        counts["nsf"] = nsf_join(recs, nsf_doc, topics)
    used_sites = {r["site"] for r in recs if r.get("site")}
    site_list, seen = [], set()
    for s in sites.values():
        if s["name"] in used_sites and s["name"] not in seen:
            seen.add(s["name"])
            p = reps.get(s["name"]) or [s["lon"], s["lat"]]
            site_list.append({"name": s["name"], "lon": p[0], "lat": p[1], "country": s.get("country")}
                             | ({"region": True} if s.get("region") else {}))
    for r in recs:  # Launch Library 2 sites GCAT does not list
        if r.get("site") and r["site"] not in seen and r.get("pad") and "ll2" in r["sources"]:
            seen.add(r["site"])
            site_list.append({"name": r["site"], "lon": r["pad"][0], "lat": r["pad"][1], "country": r.get("actor")})
    out = {"generated_at": now, "ledger_since": ledger.get("since"), "counts": counts, "sites": site_list,
           "mtypes": P.MTYPES, "orbits": P.ORBITS, "kinds": P.KINDS, "kind_notes": P.KIND_NOTES,
           "programme_notes": P.NOTES, "default_path_nm": DEFAULT_PATH_NM,
           "records": recs}
    if owner_names:
        out["owners"] = _owner_labels(owner_names, recs)
    if site_fixes:
        out["site_fixes"] = fixed
    if nfc_doc:
        out["nfc"] = {k: nfc_doc.get(k) for k in ("source", "commit", "licence", "attribution")}
        out["nfc"].update(licence_file=NFC_LICENCE_FILE, agree_nm=NFC_AGREE_NM)
    if joey_doc:
        out["joey"] = {k: joey_doc.get(k) for k in ("source", "commit", "licence", "attribution", "rule")}
        out["joey"].update(licence_file=JOEY_LICENCE_FILE, agree_nm=NFC_AGREE_NM, tol_hours=JOEY_TOL_HOURS,
                           nm=JOEY_NM)
    if wayback_doc:
        out["wayback"] = {"source": wayback_doc.get("source"), "rule": wayback_doc.get("rule"),
                          "tol_hours": WB_TOL_HOURS, "tfr_nm": WB_TFR_NM, "tfr_max_days": WB_TFR_MAX_DAYS}
    return out
