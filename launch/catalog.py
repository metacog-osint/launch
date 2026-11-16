"""The History tab's launch list: Launch's charted notices, GCAT's launch record and Launch Library 2's schedule, joined.

  ledger   every orbital launch GCAT lists since LEDGER_SINCE. Backfilled once from GCAT's own tables
           (`python tools/launch.py backfill`), then kept current on every run from the 30 days of GCAT launches
           in Orbit's snapshot, so a launch joins the history without anyone touching it. A launch Launch Library 2
           reports as flown (status Success, Failure or Partial Failure) joins as "provisional" until GCAT lists it.
           Closure areas a scheduled launch coincided with in time and place are kept with it.
  index    one record per launch or notice for the page: each charted event, joined to its GCAT launch when
           one matches in time and place; each GCAT launch that is not charted; each scheduled launch. Each
           record carries its vehicle, site, programmes, mission type and orbit as read in programs.py, and an
           estimated flight path with the basis of its azimuth.

Flight paths. A charted path is shown as drawn. Otherwise the azimuth is inferred, best basis first:
the bearing from the pad to the event's closure areas; the payloads' inclination (GCAT) or the orbit's usual
inclination (sun-synchronous, a space station), with the direction (north- or south-going) taken from the pad's
closure history; GTO and GEO launches go east; else the pad's most-used corridor. cos i = cos(latitude) x sin(az)
holds for a launch without a dog-leg. An estimated path is a great circle from the pad on that azimuth, drawn to
the farthest closure area or to DEFAULT_PATH_NM; it is not a ground track.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from . import gcat, history, notam
from . import nfc as NFC
from . import programs as P

LEDGER_SINCE = "2023-01-01"
DEFAULT_PATH_NM = 1500
AREA_NM = 2500        # closure areas farther than this from the pad do not set an azimuth
SITE_NM = 60          # a pad belongs to the nearest GCAT site within this distance
MATCH_HOURS = 3       # A charted event and a GCAT launch are one launch within this many hours ...
MATCH_NM = 200        # ... and this far apart (pad to GCAT site), or of the same country
ORBITAL = ("O", "D", "N")
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
                 site, pad_name, payloads, inc, now) -> dict:
    return {"id": "gcat:" + tag, "source": "gcat", "tag": tag, "time": when.get("time"), "date": when.get("date"),
            "time_uncertain": bool(when.get("uncertain")), "vehicle_raw": vehicle_raw, "flight": flight,
            "mission": mission, "agency": agency, "country": country, "outcome": outcome, "kind": kind,
            "category": category, "site_code": site_code, "site": site, "pad_name": pad_name,
            "payloads": _payload_summary(payloads), "inc": inc, "updated": now}


def from_gcat_tables(launch_rows: list[dict], sat_rows: list[dict], sites: dict, orgs: dict, now: str,
                     since: str = LEDGER_SINCE) -> list[dict]:
    """The backfill: GCAT launch.tsv rows (orbital, deep space, near-orbital) dated since `since`, with each
    launch's payloads from the object catalogs (satcat, satcat100k). The launching country is the first launch
    agency's state (GCAT orgs.tsv), else the site's."""
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
        if not code or code[0] not in ORBITAL:
            continue
        when = gcat.vague_date(r.get("Launch_Date", ""))
        if not when["date"] or when["date"] < since:
            continue
        tag = r.get("Launch_Tag", "")
        p = sorted(pls.get(tag, []), key=lambda x: x["jcat"])
        inc = _inc_of(p)
        if inc is None:
            try:
                inc = float(r.get("Inc") or "x")
            except ValueError:
                inc = None
        site = sites.get(r.get("Launch_Site", ""))
        variant = _dash(r.get("Variant"))
        out.append(_gcat_record(
            tag, when, (r.get("LV_Type", "") + (" " + variant if variant else "")).strip(), _dash(r.get("Flight")),
            _dash(r.get("Mission")), r.get("Agency", ""),
            gcat.agency_country(r.get("Agency", ""), orgs) or (site or {}).get("country"),
            {"S": "success", "F": "failure", "U": "unknown", "E": "pad explosion"}.get(code[1:2], code[1:]),
            {"O": "orbital", "D": "deep space", "N": "near-orbital"}[code[0]], r.get("Category", ""),
            r.get("Launch_Site", ""), site, _dash(r.get("Launch_Pad")), p, inc, now))
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
    """Closure areas a scheduled launch coincided with in time and place (or grouped), kept with that launch."""
    by_key = {}
    for a in areas:
        by_key.setdefault(a.get("key") or a.get("id"), a)
    out = []
    for m in matches or []:
        if m.get("level") not in ("time and place", "grouped"):
            continue
        a = by_key.get(m.get("area"))
        if not a or not a.get("ring"):
            continue
        out.append({"id": f"{m['launch']}|{m['area']}", "ll2": m["launch"], "area": m["area"],
                    "source": m.get("area_source"), "level": m["level"], "window": m.get("window"),
                    "ring": a["ring"], "azimuth": m.get("azimuth"), "distance_nm": m.get("distance_nm"),
                    "recorded": now})
    return out


def merge(*ledgers: dict | None) -> dict:
    """Union of ledgers by record id; where both hold a record the later `updated` wins. Nothing is dropped."""
    launches, closures, sites, since = {}, {}, {}, LEDGER_SINCE
    for lg in ledgers:
        if not lg:
            continue
        since = min(since, lg.get("since") or since)
        sites.update(lg.get("sites") or {})
        for r in lg.get("launches") or []:
            old = launches.get(r["id"])
            if old is None:
                launches[r["id"]] = r
                continue
            new, base = (r, old) if (r.get("updated") or "") >= (old.get("updated") or "") else (old, r)
            # The newer reading wins field by field; a field it lacks (Orbit's copy has no inclination) is kept.
            launches[r["id"]] = {**base, **{k: v for k, v in new.items() if v not in (None, "", [], {})}}
        for c in lg.get("closures") or []:
            closures.setdefault(c["id"], c)
    rows = sorted(launches.values(), key=lambda r: (r.get("time") or r.get("date") or "", r["id"]))
    return {"version": 1, "since": since, "launches": rows, "closures": sorted(closures.values(), key=lambda c: c["id"]),
            "sites": dict(sorted(sites.items()))}


# ---------- sites ----------

def site_table(gcat_sites: dict, used_codes) -> dict:
    """GCAT sites that launches use, keyed by code: {name (Launch's), gcat_name, lat, lon, country}."""
    out = {}
    for code in sorted(set(used_codes)):
        s = gcat_sites.get(code)
        if s and s.get("lat") is not None:
            out[code] = {"name": P.site_name(s.get("name")) or code, "gcat_name": s.get("full_name") or s.get("name"),
                         "lat": s["lat"], "lon": s["lon"], "country": s.get("country")}
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


def infer_path(pad, site: str | None, bands: list[dict], *, drawn=None, areas=None, inc=None, inc_note=None,
               orbit_code=None, orbit=None) -> dict | None:
    """{kind, az, nm, basis} for a record, or None. `drawn`: the charted path lines; `areas`: [{azimuth, downrange_nm}];
    `inc_note` says where an inclination came from when it is not the record's own payloads."""
    if drawn:
        line = max(drawn, key=len)
        a, b = line[0], line[-1]
        return {"kind": "drawn", "az": round(history.bearing(a[1], a[0], b[1], b[0]), 1), "nm": None,
                "basis": "path as charted"}
    if not pad:
        return None
    ar = [x for x in (areas or []) if x.get("azimuth") is not None and x.get("downrange_nm")]
    # Ascent areas (booster and fairing drops, second stage) lie within AREA_NM; a farther area (a splashdown
    # half a world away, a reentry box) can bear the other way round the globe, so it sets no azimuth.
    near = [x for x in ar if x["downrange_nm"] <= AREA_NM]
    if near:
        far = max(near, key=lambda x: x["downrange_nm"])
        return {"kind": "estimated", "az": far["azimuth"], "nm": round(max(200, far["downrange_nm"] * 1.15)),
                "basis": "bearing from the pad to its farthest closure area"}
    target, what = None, None
    if inc is not None and inc > 0:
        target, what = inc, inc_note or f"payload inclination {inc:g}° (GCAT)"
    elif orbit_code in P.STATION_INC:
        target, what = P.STATION_INC[orbit_code], f"space station inclination {P.STATION_INC[orbit_code]:g}°"
    elif orbit in P.CLASS_INC:
        target, what = P.CLASS_INC[orbit], f"sun-synchronous inclination, about {P.CLASS_INC[orbit]:g}°"
    if target is not None:
        opts, direct = branches(pad[1], target)
        az, how = choose(opts, bands, site, polar=target >= 80)
        note = "" if direct else "; not reachable directly from this latitude, so due east (a dog-leg or plane change follows)"
        return {"kind": "estimated", "az": az, "nm": DEFAULT_PATH_NM,
                "basis": f"{what} from the pad's latitude; {how}{note}"}
    if orbit == "GTO / GEO":
        near = [b for b in bands or [] if _adiff((b["from"] + b["to"]) / 2, 90) <= 30 and b["events"] >= 2]
        if near:
            b = max(near, key=lambda b: b["events"])
            return {"kind": "estimated", "az": b["from"] + 2.5, "nm": DEFAULT_PATH_NM,
                    "basis": f"geostationary-bound: the site's most-used easterly corridor ({b['events']} events)"}
        return {"kind": "estimated", "az": 90.0, "nm": DEFAULT_PATH_NM, "basis": "geostationary-bound: due east"}
    good = [b for b in bands or [] if b["events"] >= 3]
    if good:
        b = max(good, key=lambda b: b["events"])
        return {"kind": "estimated", "az": b["from"] + 2.5, "nm": DEFAULT_PATH_NM,
                "basis": f"the site's most-used corridor ({b['events']} charted events)"}
    return None


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


def same_vehicle(a: str | None, b: str | None) -> bool | None:
    """True or False when both names are read; None when either is not known."""
    if not a or not b or P.NOT_KNOWN in (a, b):
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


# ---------- the index ----------

def _hours_apart(a: str | None, b: str | None) -> float | None:
    x, y = _dt(a), _dt(b)
    return abs((x - y).total_seconds()) / 3600 if x and y else None


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


def _bear(pad, areas: list[dict]) -> list[dict]:
    """Bearing and distance from the record's pad to each area that has a centroid and no bearing yet."""
    if not pad:
        return areas
    return [a if a.get("azimuth") is not None or not a.get("centroid") else
            {**a, "azimuth": round(history.bearing(pad[1], pad[0], a["centroid"][1], a["centroid"][0]), 1),
             "downrange_nm": round(notam.haversine_nm(pad[1], pad[0], a["centroid"][1], a["centroid"][0]), 1)}
            for a in areas]


def build_index(hist: dict, ledger: dict, upcoming: list[dict], corridors: list[dict], now: str,
                nfc_doc: dict | None = None) -> dict:
    sites = ledger.get("sites") or {}
    nowdt = _dt(now)
    events = chart_events(hist)
    all_copies: dict[str, list] = {}
    for e in hist.get("events") or []:
        all_copies.setdefault(e["id"], []).append(e)
    bands_by_site = site_bands(corridors, sites)
    closures_by_ll2: dict[str, list] = {}
    for c in ledger.get("closures") or []:
        closures_by_ll2.setdefault(c["ll2"], []).append(c)
    gcat = [r for r in ledger.get("launches") or [] if r.get("source") == "gcat"]
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
        progs, mtype = P.programmes(g.get("flight"), g.get("mission"), *g["payloads"]["names"])
        g_info[g["id"]] = {"site": g_site(g), "pad": g_pad(g), "progs": progs, "mtype": mtype,
                           "vehicle": P.vehicle(g.get("vehicle_raw")),
                           "time": g.get("time") or (g["date"] + "T12:00:00Z")}

    # Charted events <-> GCAT launches. Pass 1: within MATCH_HOURS (a day when either has no time), near in place or
    # of the same country. Pass 2, for the rest: within 72 hours, near in place and of the same vehicle or programme
    # (a charted name often carries the scheduled time: a day early, or before a slip).
    def candidates(e, second: bool):
        e_progs = set(P.programmes(e.get("payload"), e.get("label"))[0])
        e_veh = P.vehicle(e.get("vehicle"))
        for g in gcat:
            gi = g_info[g["id"]]
            h = _hours_apart(e["time"], gi["time"])
            if h is None:
                continue
            d = notam.haversine_nm(e["pad"][1], e["pad"][0], gi["pad"][1], gi["pad"][0]) if (e.get("pad") and gi["pad"]) else None
            same = (e_veh != P.NOT_KNOWN and e_veh == gi["vehicle"]) or bool(e_progs & set(gi["progs"]))
            if not second:
                tol = MATCH_HOURS if (e["time_basis"] == "time" and g.get("time")) else 30
                if h > tol or not ((d is not None and d <= MATCH_NM) or (e.get("actor") and e["actor"] == g.get("country"))):
                    continue
            elif h > 72 or d is None or d > MATCH_NM or not same:
                continue
            yield h + (0 if same else 1.5) + (d or 0) / 400, g["id"], {"hours": round(h, 1), "nm": None if d is None else round(d),
                                                                    "same": same, "pass": 2 if second else 1}

    # Each charted event takes its best GCAT launch; several placemarks of one launch (one per notice, say)
    # all join it, and the page shows that launch once.
    chart_to_g, join = {}, {}
    usable = [e for e in events if e["kind"] in ("launch", "upcoming") and e.get("time") and e["time_basis"] != "none"]
    for second in (False, True):
        for e in usable:
            if e["id"] in chart_to_g:
                continue
            best = min(candidates(e, second), default=None, key=lambda c: c[0])
            if best:
                chart_to_g[e["id"]], join[e["id"]] = best[1], best[2]
    gby = {g["id"]: g for g in gcat}

    # NotamForChina's launches (see _nfc_join). Then two joins by NOTAM: a charted event that joined no GCAT
    # launch, holding a notice (same number, same FIR) that NotamForChina lists for a launch GCAT has, joins that
    # launch (pass 3: the charted name or NotamForChina's sheet is a year or a month out now and then); and a NotamForChina
    # launch that joined nothing joins the charted event that holds one of its notices. Else, before ledger_since
    # (where GCAT's list here does not reach), one unjoined charted event within NFC_HOURS, not of another
    # vehicle, at the same site when the vehicle is not read. Else a record of its own.
    nfc_by_tag, nfc_loose, nfc_counts = _nfc_join(nfc_doc, gcat, g_info)
    chart_keys = {e["id"]: chart_notice_keys(all_copies.get(e["id"], [e])) for e in events}
    nfc_tags: dict[str, dict] = {}
    for tag, xs in nfc_by_tag.items():
        for x in xs:
            for k in nfc_notice_keys(x):
                nfc_tags.setdefault(k[0], {}).setdefault(k[1], set()).add(tag)
    nfc_counts["chart_by_notam"] = 0
    for e in events:
        if e["id"] in chart_to_g or not chart_keys[e["id"]]:
            continue
        hits = {t for k in chart_keys[e["id"]] for t in _key_hits(k, nfc_tags)}
        if len(hits) == 1:
            gid = "gcat:" + hits.pop()
            h = _hours_apart(e.get("time"), g_info[gid]["time"])
            chart_to_g[e["id"]] = gid
            join[e["id"]] = {"hours": None if h is None else round(h, 1), "nm": None, "pass": 3,
                             "same": bool(same_vehicle(P.vehicle(e.get("vehicle")), g_info[gid]["vehicle"]))}
            nfc_counts["chart_by_notam"] += 1
    g_to_chart: dict[str, list] = {}
    for e in events:
        if e["id"] in chart_to_g:
            g_to_chart.setdefault(chart_to_g[e["id"]], []).append(e)

    chart_by_key: dict[str, dict] = {}
    for eid, ks in chart_keys.items():
        for k in ks:
            chart_by_key.setdefault(k[0], {}).setdefault(k[1], set()).add(eid)
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

    # The inclination of the last launch of the same programme (else the same vehicle, when its recent launches
    # agree) from the same site: for a launch whose own payloads have none yet, and for scheduled launches.
    inc_hist: dict[tuple, list] = {}
    for g in gcat:
        gi = g_info[g["id"]]
        if g.get("inc") and gi["site"]:
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
                out.append({"ring": n["ring"], "centroid": [round(lo, 4), round(la, 4)]})
        return out

    def finish(r: dict, *, drawn=None, areas=None, orbit_code=None):
        if (r["mtype"] == P.MTYPES[-1] and P.payload_unknown(r.get("payload"))
                and all(P.payload_unknown(n) for n in (r.get("payloads") or {}).get("names") or [])):
            r["mtype"] = P.NO_PAYLOAD  # nothing to read, as opposed to a name the table does not know
        site, inc, note = r.get("site"), r.get("inc"), None
        if r.get("orbit") in ("GTO / GEO", "Deep space / lunar"):
            inc = None  # a payload's inclination there is its final orbit's, not the launch's
        known_class = r.get("orbit") in P.CLASS_INC or r.get("orbit") == "GTO / GEO" or orbit_code in P.STATION_INC
        if not inc and r["status"] != "notice" and not known_class:
            inc, note = borrowed_inc(site, r.get("programmes"), r.get("vehicle"), r.get("time") or "9999")
        path = infer_path(r.get("pad"), site, bands_by_site.get(site or "", []), drawn=drawn, areas=areas, inc=inc,
                          inc_note=note, orbit_code=orbit_code, orbit=r.get("orbit"))
        if path:
            r["path"] = path
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
        cl = closures_by_ll2.get(link["id"], [])
        if cl:
            r["closures"] = _closure_list(cl)
        return cl

    groups = [[e] for e in events if e["id"] not in chart_to_g] + list(g_to_chart.values())
    for grp in groups:
        e = max(grp, key=lambda x: (bool(x.get("paths")), len(x.get("areas") or []), -grp.index(x)))
        g = gby.get(chart_to_g.get(e["id"], ""))
        gi = g_info.get(g["id"]) if g else None
        texts = [x for m in grp for x in (m.get("payload"), m.get("label"), m.get("extra"))]
        chart_progs = P.programmes(*texts)[0]
        if g:
            texts += [g.get("flight"), g.get("mission"), *g["payloads"]["names"]]
        progs, mtype = P.programmes(*texts)
        if any(P.MTYPE_OF[p] == P.MSL for p in chart_progs):  # a charted "ICBM" outranks a joined launch's payloads
            mtype = P.MSL
        future = bool(nowdt and _dt(e.get("time")) and _dt(e["time"]) > nowdt)
        status = ("launched" if g else "notice" if e["kind"] == "unknown" or not e.get("time") else
                  "upcoming" if future else "launched")
        veh = P.vehicle(e.get("vehicle"))
        r = {"id": e["id"], "status": status, "time": e.get("time"), "time_basis": e.get("time_basis"),
             "actor": e.get("actor") or (g or {}).get("country"), "label": e.get("label"),
             "vehicle": veh if veh != P.NOT_KNOWN or not g else gi["vehicle"],
             "payload": e.get("payload") or ((g or {}).get("mission") or None),
             "programmes": progs, "mtype": mtype, "pad": e.get("pad") or (gi["pad"] if gi else None),
             "site": chart_site.get(e["id"]) or (gi["site"] if gi else None),
             "orbit": P.orbit_class((g or {}).get("category")), "cancelled": e.get("cancelled"),
             "sources": ["chart"] + (["gcat"] if g else []), "chart": [m["id"] for m in grp],
             "areas": sum(len(m.get("areas") or []) for m in grp)}
        if len(grp) > 1:
            r["chart_labels"] = [m["label"] for m in grp if m is not e]
        if g:
            r.update({"gcat": g["tag"], "outcome": g.get("outcome"), "inc": g.get("inc"), "gcat_vehicle": g.get("vehicle_raw"),
                      "payloads": g.get("payloads"), "flight": g.get("flight"), "join": join.get(e["id"])})
            if g.get("time"):
                h = _hours_apart(e.get("time"), g["time"])
                r["time"], r["time_basis"] = g["time"], "time"
                if h is not None and h > 1:
                    r["chart_time"] = e.get("time")
        attach_ll2(r, ll2_link(r.get("time"), r.get("pad")) if r.get("time") else None)
        extra = add_nfc(r, (nfc_by_tag.get(g["tag"], []) if g else []) +
                        [x for m in grp for x in nfc_by_chart.get(m["id"], [])],
                        [c for m in grp for c in all_copies.get(m["id"], [m])])
        # bearings from the record's pad to every area of the group (placemarks without a path have none)
        areas = _bear(r.get("pad"), [a for m in grp for a in (m.get("areas") or [])] + extra)
        finish(r, drawn=[p for m in grp for p in (m.get("paths") or [])], areas=areas,
               orbit_code=P.gcat_orbit_code((g or {}).get("category")))

    for g in gcat:
        if g["id"] in g_to_chart:
            continue
        gi = g_info[g["id"]]
        r = {"id": g["id"], "status": "launched", "time": g.get("time") or (g["date"] + "T00:00:00Z"),
             "time_basis": "time" if g.get("time") else "date", "actor": g.get("country"),
             "label": " · ".join(x for x in (g.get("vehicle_raw"), g.get("flight") or g.get("mission")) if x),
             "vehicle": gi["vehicle"], "gcat_vehicle": g.get("vehicle_raw"), "payload": g.get("mission") or g.get("flight"),
             "flight": g.get("flight"), "programmes": gi["progs"], "mtype": gi["mtype"], "pad": gi["pad"],
             "pad_basis": "site", "site": gi["site"], "orbit": P.orbit_class(g.get("category")),
             "outcome": g.get("outcome"), "inc": g.get("inc"), "payloads": g.get("payloads"), "sources": ["gcat"],
             "gcat": g["tag"], "areas": 0}
        link = ll2_link(g.get("time"), gi["pad"]) if g.get("time") else None
        cl = attach_ll2(r, link)
        if link and link.get("lat") is not None:
            r["pad"], r["pad_basis"] = [link["lon"], link["lat"]], "ll2"
        extra = add_nfc(r, nfc_by_tag.get(g["tag"], []), [])
        finish(r, areas=list(cl) + _bear(r["pad"], extra), orbit_code=P.gcat_orbit_code(g.get("category")))

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
             "orbit": P.NOT_KNOWN, "sources": [], "areas": 0}
        if status == "notice":
            r["nfc_unmatched"] = True
        extra = add_nfc(r, [x], [])
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
             "ll2_status": u.get("status"), "provider": u.get("provider"), "sources": ["ll2"], "ll2": u["id"],
             "ll2_url": u.get("ll2_url"), "areas": 0}
        if provisional:
            r["provisional"] = True
        cl = closures_by_ll2.get(u["id"], [])
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
        finish(r, areas=cl)
    for u in ll2_all:
        if u["id"] in used_ll2 or u.get("status") in LL2_FLOWN:
            continue
        r, cl = ll2_rec(u, "upcoming", False)
        finish(r, areas=cl)

    recs.sort(key=lambda r: (r.get("time") or "0000", r["id"]))
    counts = {"chart": len(events), "gcat": len(gcat), "chart_joined": len(chart_to_g), "gcat_joined": len(g_to_chart),
              "provisional": sum(1 for r in recs if r.get("provisional")),
              "upcoming": sum(1 for r in recs if r["status"] == "upcoming"),
              "paths": {k: sum(1 for r in recs if (r.get("path") or {}).get("kind") == k) for k in ("drawn", "estimated")}}
    if nfc_doc:
        nn = [n for r in recs for n in r.get("nfc_notices") or []]
        counts["nfc"] = {**nfc_counts, "own_records": len(nfc_loose),
                         "own_launched": sum(1 for x in nfc_loose if x["time"][:10] < since),
                         "records": sum(1 for r in recs if r.get("nfc")), "notices": len(nn),
                         "charted": sum(1 for n in nn if n.get("ring")), "chart_held": sum(1 for n in nn if n.get("chart")),
                         "chart_disagree": sum(1 for n in nn if (n.get("gap_nm") or 0) > NFC_AGREE_NM),
                         "folded": sum(1 for n in nn if n.get("folded"))}
    used_sites = {r["site"] for r in recs if r.get("site")}
    site_list, seen = [], set()
    for s in sites.values():
        if s["name"] in used_sites and s["name"] not in seen:
            seen.add(s["name"])
            p = reps.get(s["name"]) or [s["lon"], s["lat"]]
            site_list.append({"name": s["name"], "lon": p[0], "lat": p[1], "country": s.get("country")})
    for r in recs:  # Launch Library 2 sites GCAT does not list
        if r.get("site") and r["site"] not in seen and r.get("pad") and "ll2" in r["sources"]:
            seen.add(r["site"])
            site_list.append({"name": r["site"], "lon": r["pad"][0], "lat": r["pad"][1], "country": r.get("actor")})
    out = {"generated_at": now, "ledger_since": ledger.get("since"), "counts": counts, "sites": site_list,
           "mtypes": P.MTYPES, "orbits": P.ORBITS, "programme_notes": P.NOTES, "default_path_nm": DEFAULT_PATH_NM,
           "records": recs}
    if nfc_doc:
        out["nfc"] = {k: nfc_doc.get(k) for k in ("source", "commit", "licence", "attribution")}
        out["nfc"].update(licence_file=NFC_LICENCE_FILE, agree_nm=NFC_AGREE_NM)
    return out
