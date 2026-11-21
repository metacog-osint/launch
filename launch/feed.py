"""Launch's contract-v2 feed (tic-feed/2, GeoJSON). Observations, tier routine except one rule: a space operations
TFR the FAA issued within NEW_HOURS is an anomaly against the TFRs in force NEW_HOURS earlier (the rule Cordon used
for these TFRs before it left them to Launch, 14 Nov 2026). Items:
  - each FAA SPACE OPERATIONS TFR in the active list (its polygon);
  - each scheduled launch that coincides with a closure area in time and place, or that GCAT has since dated
    inside the area's window ("grouped"), drawn as the area. Time-only coincidences stay on the page: across
    oceans they are mostly chance (Orbit found one on 13 Nov 2026).
Orbit's own navigational-warning areas are not repeated here; they are in Orbit's feed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
from tic_doctrine import CONTRACT, geo  # noqa: E402

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
             "title": "Scheduled launches (Launch Library 2), GCAT launches, launch-hazard navigational warnings",
             "url": "https://orbit.theintelligence.company", "licence": "Each item keeps its source's terms",
             "grade": "B2", "independence_group": "orbit", "source_type": "aggregator"}
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


def _tfr_item(t: dict, generated: str, accessed: str) -> dict:
    d = t.get("detail") or {}
    alt = "; ".join(f"{a.get('name') or 'area'}: {a['lower']} to {a['upper']}" for a in d.get("areas") or [])
    issued = d.get("issued_utc")
    is_new = bool(issued and _dt(issued) >= _dt(generated) - timedelta(hours=NEW_HOURS))
    activity = d.get("activity")
    props = {
        **_base(generated),
        "tier": "anomaly" if is_new else "routine",
        "id": f"launch:tfr:{t['id']}",
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
        props["baseline_ref"] = {"id": "faa-space-ops-tfrs-in-force", "type": "rolling", "version": "1",
                                 "window": f"the space operations TFRs the FAA listed {NEW_HOURS} hours earlier"}
    return {"type": "Feature", "geometry": _geom(t["rings"]), "properties": props}


def _match_item(m: dict, area: dict, generated: str, accessed: str, cordon_at: str | None = None) -> dict:
    end = _dt(m["window"][1])
    lvl = m["level"]
    what = ("GCAT has since dated launch " + m["grouped_with"]["launch_tag"] + f" ({m['grouped_with']['vehicle']}) "
            "from that site inside the window") if lvl == "grouped" else m["place_basis"]
    props = {
        **_base(generated),
        "id": f"launch:match:{m['launch']}:{m['area']}",
        "title": f"Closure area {m['area']} coincides ({lvl}) with scheduled launch {m['launch_name']}",
        "summary": (f"{m['launch_name']} is scheduled for {m['net'][:16].replace('T', ' ')} UTC (Launch Library 2 via "
                    f"Orbit). Closure area {m['area']} ({area.get('source')}) has a window "
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
        "sources": [{**SRC_ORBIT, "accessed_at": accessed}]
                   + ([{**SRC_CORDON, "accessed_at": cordon_at or accessed}]
                      if area.get("source") == "cordon-navwarn" else [])
                   + ([{**SRC_NMS, "accessed_at": accessed}] if area.get("source") == "faa-nms" else []),
    }
    return {"type": "Feature", "geometry": _geom([area["ring"]]), "properties": props}


def build_feed(snap: dict) -> dict:
    generated = snap["generated_at"]
    lanes = snap.get("lanes") or {}
    tfr_at = (lanes.get("tfr") or {}).get("fetched_at") or generated
    orb_at = (lanes.get("orbit") or {}).get("fetched_at") or generated
    cor_at = (lanes.get("cordon") or {}).get("fetched_at") or generated
    features = [_tfr_item(t, generated, tfr_at) for t in snap.get("tfr") or []]
    areas = {(a.get("key") or a.get("id")): a for a in snap.get("areas") or []}
    now = _dt(generated)
    for m in snap.get("matches") or []:
        if m["level"] in ("time and place", "grouped") and _dt(m["window"][1]) >= now - timedelta(hours=24):
            a = areas.get(m["area"])
            if a:
                features.append(_match_item(m, a, generated, orb_at, cor_at))
    return {
        "type": "FeatureCollection", "contract": CONTRACT, "program": "launch", "generated_at": generated,
        "method_version": METHOD,
        "licence": "FAA TFRs and NGA warnings: US Government works. Orbit's items keep their sources' terms "
                   "(GCAT CC BY 4.0).",
        "attribution": "Launch, The Intelligence Company. FAA TFRs; NGA navigational warnings via Cordon; Orbit "
                       "(Launch Library 2, GCAT by J. McDowell)",
        "language_key": LANGUAGE_KEY, "features": features,
    }
