"""Launch's contract-v2 feed (tic-feed/2, GeoJSON). Observations, tier routine except one rule: a space operations
TFR the FAA issued within NEW_HOURS is an anomaly against the TFRs in force NEW_HOURS earlier (the rule Cordon used
for these TFRs before it left them to Launch, 14 Nov 2026). Items:
  - each FAA SPACE OPERATIONS TFR in the active list (its polygon);
  - each scheduled launch that coincides with a closure area in time and place, or that GCAT has since dated
    inside the area's window ("grouped"), drawn as the area. Time-only coincidences stay on the page: across
    oceans they are mostly chance (Orbit found one on 13 Nov 2026);
  - each upcoming-launch record in Launch's multi-source schedule (launch/schedule.py `active()`, Ascent move step 3,
    25 Nov 2026), id `launch:upcoming:<record id>` with spaces as hyphens: `launch:upcoming:ll2:<LL2 id>` for a listed
    launch and `launch:upcoming:closure:<notice key>` for a closure with no listing (marked by `measures.evidence`).
    The record keeps its id when a later source joins it, so the item does too. A scheduled time is the provider's
    or press's; a closure record's time is the closure window's opening, not a launch time.
Orbit's own navigational-warning areas are not repeated here; they are in Orbit's feed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
from tic_doctrine import CONTRACT, __version__ as KIT_VERSION, geo  # noqa: E402

SITE = "https://launch.theintelligence.company"
METHOD = "launch-1.0"
LANGUAGE_KEY = "https://github.com/metacog-osint/tic-doctrine/blob/main/docs/language-key.md"
NEW_HOURS = 72  # a space operations TFR issued within this long is new, and new is tier anomaly

SRC_TFR = {"id": "faa-tfr", "publisher": "US Federal Aviation Administration", "title": "Temporary Flight Restrictions",
           "url": "https://tfr.faa.gov/", "licence": "US Government work", "grade": "A1",
           "independence_group": "faa", "source_type": "official"}
SRC_NMS = {"id": "faa-nms", "publisher": "NOTAMs read through the FAA NOTAM Management Service API",
           "title": "NOTAMs (NMS-API); not FAA data as published here, and not authoritative for non-US NOTAMs",
           "url": "https://api-nms.aim.faa.gov/", "licence": "Redistribution allowed (FAA NMS-API terms of service)",
           "grade": "A2", "independence_group": "faa", "source_type": "official"}
SRC_ORBIT = {"id": "orbit-snapshot", "publisher": "Orbit, The Intelligence Company",
             "title": "GCAT launches (Orbit's published snapshot)",
             "url": "https://orbit.theintelligence.company", "licence": "Each item keeps its source's terms",
             "grade": "B2", "independence_group": "orbit", "source_type": "aggregator"}
SRC_LL2 = {"id": "ll2-thespacedevs", "publisher": "The Space Devs (Launch Library 2)",
           "title": "Launch Library 2: upcoming launches", "url": "https://thespacedevs.com/llapi",
           "licence": "Free access stated by The Space Devs; no data licence stated (read 16 Nov 2026)", "grade": "B2",
           "independence_group": "thespacedevs", "source_type": "aggregator"}
SRC_CORDON = {"id": "cordon-feed", "publisher": "Cordon, The Intelligence Company",
              "title": "NGA navigational warnings (launch category), windows and hazard as parsed by Cordon",
              "url": "https://cordon.theintelligence.company", "licence": "NGA: US public domain",
              "grade": "A1", "independence_group": "nga", "source_type": "aggregator"}


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base(generated: str, valid_hours: int = 48) -> dict:
    return {
        "contract": CONTRACT, "program": "launch", "kind": "observation", "tier": "routine", "status": "actual",
        "msg_type": "new", "human_review": "none", "us_person_data": "organizations", "status_class": "reported",
        "product_category": "current", "published_at": generated,
        "valid_until": _iso(_dt(generated) + timedelta(hours=valid_hours)),
        "pmesii_pt": ["military", "infrastructure"], "ascope": ["areas", "capabilities"], "ie_aspect": ["physical"],
        "ncf": ["provide_satellite_access"], "method_version": METHOD,
    }


def _geom(rings: list) -> dict:
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}
    return {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}


def _countries(*codes) -> list[str]:
    return sorted({c for c in codes if c and geo.name(c)})


def _subject(item_id: str) -> str:
    """The item's id as a subject: the contract allows no spaces, and a NOTAM's area key has one."""
    return item_id.replace(" ", "-")


def _window_times(windows: list) -> dict:
    """event_start and event_end: the first window's start to the last window's end, as the notice states them."""
    starts = sorted(_iso(_dt(w["start"])) for w in windows or [] if w.get("start"))
    ends = sorted(_iso(_dt(w["end"])) for w in windows or [] if w.get("end"))
    if not starts:
        return {}
    return {"event_start": starts[0], **({"event_end": ends[-1]} if ends and ends[-1] >= starts[0] else {})}


def _tfr_item(t: dict, generated: str, accessed: str) -> dict:
    d = t.get("detail") or {}
    alt = "; ".join(f"{a.get('name') or 'area'}: {a['lower']} to {a['upper']}" for a in d.get("areas") or [])
    issued = d.get("issued_utc")
    is_new = bool(issued and _dt(issued) >= _dt(generated) - timedelta(hours=NEW_HOURS))
    activity = d.get("activity")
    issued_at = _iso(_dt(issued)) if issued else None
    times = _window_times(d.get("windows")) or ({"event_start": issued_at} if issued_at else {})
    props = {
        **_base(generated),
        "tier": "anomaly" if is_new else "routine",
        "id": f"launch:tfr:{t['id']}",
        "subject_id": _subject(f"launch:tfr:{t['id']}"),
        **times,
        **({"last_change": "new", "last_change_at": min(issued_at, generated)} if issued_at else {"last_change": "none"}),
        "title": (f"FAA space operations TFR FDC {t['id']}" + (f", {activity}" if activity else "")
                  + f": {t.get('description') or ''}").strip(),
        "summary": (f"The FAA lists FDC {t['id']} (space operations, {t.get('facility')}, {t.get('state')}), created "
                    f"{t.get('created')}: {t.get('description')}."
                    + (f" Limits: {alt}." if alt else "")
                    + (" In force " + "; ".join(f"{w['start']} to {w['end']}" for w in d["windows"][:3])
                       + (f" and {len(d['windows']) - 3} more windows" if len(d["windows"]) > 3 else "") + " (UTC)."
                       if d.get("windows") else "")
                    + (" The notice names an amateur rocketry group as its contact: high-power hobby rocketry, not an "
                       "orbital launch closure." if activity else "")
                    + " Not for navigation."),
        "data_as_of": accessed,
        "countries": ["US"],
        "requirement_ids": ["LA-PIR-1"],
        "coverage_fraction": 1.0,
        "precision_class": "area",
        "visual": {"type": "map", "url": f"{SITE}/#live"},
        "sources": [{**SRC_TFR, "url": t.get("page") or SRC_TFR["url"], "accessed_at": accessed}],
        "measures": {"notam_id": t["id"], "new": is_new, **({"issued": issued} if issued else {}),
                     **({"activity": activity} if activity else {})},
    }
    if is_new:
        hours = max((_dt(generated) - _dt(issued)).total_seconds() / 3600, 0)
        props["signal"] = {"name": "hours_since_faa_issued", "value": round(hours, 1), "unit": "hours", "tail": "low"}
        props["baseline_ref"] = {"id": "faa-space-ops-tfrs-in-force", "type": "rolling", "version": "1",
                                 "window": f"the space operations TFRs the FAA listed {NEW_HOURS} hours earlier"}
    return {"type": "Feature", "geometry": _geom(t["rings"]), "properties": props}


def _match_item(m: dict, area: dict, generated: str, accessed: str, cordon_at: str | None = None,
                rings: list | None = None, parts: list[str] | None = None) -> dict:
    """One feed item per launch and notice. A notice with lettered areas (NAVAREA XII 836/26 A, B and C) is one item:
    `rings` are all its matched areas and `parts` their letters; `m` is the best-rated part's match."""
    end = _dt(m["window"][1])
    lvl = m["level"]
    what = ("GCAT has since dated launch " + m["grouped_with"]["launch_tag"] + f" ({m['grouped_with']['vehicle']}) "
            "from that site inside the window") if lvl == "grouped" else m["place_basis"]
    props = {
        **_base(generated),
        "id": f"launch:match:{m['launch']}:{m['area']}",
        "subject_id": _subject(f"launch:match:{m['launch']}:{m['area']}"),
        "event_start": _iso(_dt(m["window"][0])),
        "event_end": _iso(end),
        "last_change": "none",   # a coincidence has no source date, and Launch keeps no log of its feed items
        "title": f"Closure area {m['area']}{_parts(parts)} coincides ({lvl}) with scheduled launch {m['launch_name']}",
        "summary": (f"{m['launch_name']} is scheduled for {m['net'][:16].replace('T', ' ')} UTC (Launch Library 2). "
                    f"Closure area {m['area']} ({area.get('source')}) has a window "
                    f"{m['window'][0][11:16]}-{m['window'][1][11:16]} UTC on {m['window'][0][:10]} and lies "
                    f"{m['distance_nm']} NM from the pad on azimuth {m['azimuth']} degrees (implied inclination about "
                    f"{m['inclination_est']} degrees): {what}. A coincidence, not a finding that the area is for "
                    "this launch."),
        "data_as_of": accessed,
        "valid_until": _iso(max(end + timedelta(hours=6), _dt(generated) + timedelta(hours=6))),
        "countries": _countries(*(area.get("countries") or [])),
        "requirement_ids": ["LA-PIR-2"],
        "coverage_fraction": 1.0,
        "precision_class": "area",
        "visual": {"type": "map", "url": f"{SITE}/#live"},
        "sources": [{**SRC_LL2, "accessed_at": accessed}]
                   + ([{**SRC_CORDON, "accessed_at": cordon_at or accessed}]
                      if area.get("source") == "cordon-navwarn" else [])
                   + ([{**SRC_NMS, "accessed_at": accessed}] if area.get("source") == "faa-nms" else []),
    }
    if parts and len(parts) > 1:
        props["measures"] = {"parts": parts}
    return {"type": "Feature", "geometry": _geom(rings or [area["ring"]]), "properties": props}


# Launch Library 2's NET precision words as the contract's event_time_precision (Orbit's map, plus the parts of a day,
# where the day is known and the time is not). Second and Minute need none; a closure window's times are exact.
NET_PRECISION = {"Hour": "hour", "Day": "day", "Week": "day", "Month": "month", "Quarter": "month", "Year": "month",
                 "Fiscal Year": "month"}
DAY_PARTS = ("Morning", "Afternoon", "Night")


def _precision(word: str | None) -> str | None:
    word = word or ""
    return NET_PRECISION.get(word) or ("day" if word.startswith(DAY_PARTS) else None)


def _floor(iso: str, precision: str | None) -> str:
    """A time at the start of its period, as the contract's event_time_precision reads it."""
    return {"month": f"{iso[:7]}-01T00:00:00Z", "day": f"{iso[:10]}T00:00:00Z",
            "hour": f"{iso[:13]}:00:00Z"}.get(precision or "", iso)


def _upcoming_item(r: dict, generated: str, read_at: str, notice_src: dict) -> dict | None:
    """One record of Launch's upcoming-launch store as a feed item, or None when it has no time."""
    try:
        net = _iso(_dt(r["net"]))
        end = _iso(_dt(r.get("window_end") or r["net"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    closure = not (r.get("refs") or {}).get("ll2") and "closure" in (r.get("sources") or [])
    precision = None if closure else _precision(r.get("net_precision"))
    start, stop = _floor(net, precision), _floor(end, precision)
    when = net[:16].replace("T", " ")
    item_id = _subject(f"launch:{r['id']}")
    lat, lon = r.get("lat"), r.get("lon")
    if closure:
        cl = r.get("closure") or {}
        notices = cl.get("notices") or list((r.get("refs") or {}).values())
        srcs = []
        for k in notices:
            # The notice's own lane (launch/unlisted.py rows); NOTAM keys not found there are read through NMS.
            src = SRC_CORDON if notice_src.get(k) == "cordon-navwarn" else SRC_NMS
            if src not in srcs:
                srcs.append(src)
        maybe = cl.get("maybe_listed") or []
        title = f"Closure with no listed launch near {r.get('location')}: window opens {when} UTC"
        summary = (f"Closure notice {', '.join(notices)} has a window {when}-{end[11:16]} UTC near "
                   f"{r.get('location')}, a site with launch history, and no schedule Launch reads lists a launch "
                   "from that site in it."
                   + (f" The site's own history puts a launch in such a window at about "
                      f"{cl['expect_at'][11:16]} UTC." if cl.get("expect_at") else "")
                   + (f" {len(maybe)} listed launch" + ("es are" if len(maybe) != 1 else " is")
                      + " dated only to a day or month, so not placed in the window." if maybe else "")
                   + " Closures are also issued for tests and other activity, and some are cancelled: this says a "
                   "closure exists and no launch is listed for it, not that a launch is coming.")
        sources = [{**x, "accessed_at": read_at} for x in srcs]
    else:
        mission_bits = [b for b in (r.get("mission_type"), r.get("orbit_name")) if b and b != "Unknown"]
        title = f"Scheduled launch: {r.get('name')} ({r.get('status')}), {when} UTC"
        summary = (f"Launch Library 2 lists {r.get('name')} for {when} UTC (status "
                   f"{r.get('status_name') or r.get('status')}; NET precision {r.get('net_precision') or 'not given'}) "
                   f"from {r.get('pad')}, {r.get('location')}. Provider {r.get('provider')}."
                   + (f" Mission: {', '.join(mission_bits)}." if mission_bits else "")
                   + " A scheduled time is the provider's or press's, not Launch's, and often moves.")
        link = (r.get("links") or {}).get("ll2")
        sources = [{**SRC_LL2, "url": link or SRC_LL2["url"], "accessed_at": read_at}]
    point = lat is not None and lon is not None
    props = {
        **_base(generated),
        "id": item_id,
        "subject_id": item_id,
        "event_start": start,
        **({"event_end": stop} if stop > start else {}),
        **({"event_time_precision": precision} if precision else {}),
        # The record is new when Launch first read it; its time changes are counted in measures.net_changes.
        "last_change": "new",
        "last_change_at": min(r.get("first_seen") or generated, generated),
        "title": title,
        "summary": summary,
        "data_as_of": min(read_at, generated),
        "valid_until": _iso(max(_dt(end) + timedelta(hours=6), _dt(generated) + timedelta(hours=6))),
        "countries": _countries(r.get("pad_country"), *(r.get("provider_countries") or []),
                                geo.country_at(lat, lon) if point else None),
        "requirement_ids": ["LA-PIR-3"],
        "coverage_fraction": 1.0,
        "precision_class": "point" if point else "none",
        # A pad on land has no sea area; a sea platform's is the sea it lies in (coarse sea outlines put coastal
        # pads such as Mahia at sea, so land is tested first).
        **({"place_basis": "location",
            "sea_areas": [] if geo.country_at(lat, lon) else [x for x in [geo.sea_at(lat, lon)] if x]}
           if point else {}),
        "visual": {"type": "table", "url": f"{SITE}/#live"},
        "sources": sources,
        "measures": {"record_id": r["id"], "evidence": r.get("evidence") or [],
                     "schedule_sources": r.get("sources") or [],
                     **({"aliases": r["aliases"]} if r.get("aliases") else {}),
                     **({"net_changes": r["net_changes"]} if r.get("net_changes") else {})},
    }
    geom = {"type": "Point", "coordinates": [lon, lat]} if point else None
    return {"type": "Feature", "geometry": geom, "properties": props}


def _parts(parts: list[str] | None) -> str:
    return f" (areas {', '.join(parts)})" if parts and len(parts) > 1 else ""


LEVEL_RANK = {"grouped": 0, "time and place": 1, "time": 2}


def build_feed(snap: dict) -> dict:
    generated = snap["generated_at"]
    lanes = snap.get("lanes") or {}
    tfr_at = (lanes.get("tfr") or {}).get("fetched_at") or generated
    # Match items cite Launch Library 2 as Launch read it (Ascent step 4, ideas#69), not Orbit's copy.
    sch_at = ((snap.get("schedule") or {}).get("read_at") or (lanes.get("schedule") or {}).get("fetched_at")
              or generated)
    cor_at = (lanes.get("cordon") or {}).get("fetched_at") or generated
    features = [_tfr_item(t, generated, tfr_at) for t in snap.get("tfr") or []]
    listed = snap.get("areas") or []
    areas = {(a.get("key") or a.get("id")): a for a in listed}
    now = _dt(generated)
    # One item per launch and notice: a notice's lettered areas each match on their own (the ledger keeps every ring),
    # but they share the item id, so the feed folds them (24 Nov 2026: 19 items held 14 ids).
    groups: dict[tuple, list[dict]] = {}
    for m in snap.get("matches") or []:
        if m["level"] in ("time and place", "grouped") and _dt(m["window"][1]) >= now - timedelta(hours=24):
            groups.setdefault((m["launch"], m["area"]), []).append(m)
    for ms in groups.values():
        ms.sort(key=lambda m: (LEVEL_RANK.get(m["level"], 3), m["distance_nm"]))
        best = ms[0]
        own = [listed[m["area_i"]] for m in ms if isinstance(m.get("area_i"), int) and m["area_i"] < len(listed)]
        a = (listed[best["area_i"]] if isinstance(best.get("area_i"), int) and best["area_i"] < len(listed)
             else areas.get(best["area"]))
        if a:
            parts = [x.get("label") or "" for x in own]
            features.append(_match_item(best, a, generated, sch_at, cor_at, rings=[x["ring"] for x in own] or None,
                                        parts=sorted(parts) if all(parts) else None))
    sch = snap.get("schedule") or {}
    read_at = sch.get("read_at") or (lanes.get("schedule") or {}).get("fetched_at") or generated
    notice_src = {n["key"]: n.get("source") for u in snap.get("unlisted") or [] for n in u.get("notices") or []
                  if n.get("key")}
    for r in sch.get("records") or []:
        item = _upcoming_item(r, generated, read_at, notice_src)
        if item:
            features.append(item)
    return {
        "type": "FeatureCollection", "contract": CONTRACT, "contract_rev": "2.1", "kit": KIT_VERSION,
        "program": "launch", "generated_at": generated,
        "method_version": METHOD,
        "licence": "FAA TFRs and NGA warnings: US Government works. NOTAMs read through the FAA NOTAM Management "
                   "Service API: redistribution allowed under its terms of service. Orbit's items keep their sources' "
                   "terms (GCAT CC BY 4.0). Launch Library 2 (The Space Devs): free access, "
                   "no data licence stated.",
        "attribution": "Launch, The Intelligence Company. FAA TFRs; NOTAMs read through the FAA NOTAM Management "
                       "Service API via Cordon (not FAA data, and not authoritative for notices issued outside the "
                       "United States); NGA navigational warnings via Cordon; Launch Library 2 "
                       "(The Space Devs); Orbit (Launch Library 2, GCAT by J. McDowell)",
        "language_key": LANGUAGE_KEY, "features": features,
    }
