"""Live lanes and launch matching.

  tfr     FAA temporary flight restrictions (tfr.faa.gov, no key): the list, the shapes from the FAA's own map
          service, and each SPACE OPERATIONS TFR's XML for its altitudes. Only space operations are kept.
  orbit   Orbit's published snapshot (orbit.theintelligence.company/data/snapshot.json, one request): its
          scheduled launches, its launch-hazard navigational warnings (NGA, NAVAREA XI) and GCAT's launches of
          the last 30 days. Launch reads them rather than fetching those sources a second time.
  nms     FAA NOTAM Management Service: waits for API access (requested 13 Nov 2026).

Matching, three levels, each named on the page:
  time            a scheduled launch's NET falls in an area's window of four hours or less, or up to an hour
                  before it opens (Orbit's rule, method orbit-2.2, rule 5).
  time and place  the same, and the area lies in an azimuth band where the charted history has closures from that
                  pad, or (no history for the pad) within PLACE_NM of it.
  grouped         after the launch: GCAT dates a launch from that site inside the window of an area that had
                  matched on time and place. History events are grouped as charted.
None of these says an area is for a launch; each says which coincidence holds.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from . import history, notam

TFR_LIST = "https://tfr.faa.gov/tfrapi/exportTfrList"
TFR_SHAPES = ("https://tfr.faa.gov/geoserver/TFR/ows?service=WFS&version=1.1.0&request=GetFeature"
              "&typeName=TFR:V_TFR_LOC&outputFormat=application/json")
TFR_XML = "https://tfr.faa.gov/download/detail_{a}_{b}.xml"
TFR_PAGE = "https://tfr.faa.gov/tfr3/?page=detail_{a}_{b}"
ORBIT_SNAPSHOT = "https://orbit.theintelligence.company/data/snapshot.json"
WINDOW_MAX_H = 4
BEFORE_H = 1
PLACE_NM = 1500


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- FAA TFRs ----------

def tfr_space_ops(list_body: bytes, shapes_body: bytes) -> list[dict]:
    """Active SPACE OPERATIONS TFRs from the FAA list, joined to their shapes. A shape whose NOTAM is not in the
    active list is dropped (the map service keeps some old shapes: 5/6914 of May 2025 was there on 13 Nov 2026)."""
    lst = json.loads(list_body)
    shapes = json.loads(shapes_body).get("features", [])
    want = {x["notam_id"]: x for x in lst if (x.get("type") or "").upper() == "SPACE OPERATIONS"}
    out = {}
    for f in shapes:
        p = f.get("properties") or {}
        nid = (p.get("NOTAM_KEY") or "").split("-")[0]
        if nid not in want or not f.get("geometry"):
            continue
        g = f["geometry"]
        rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [poly[0] for poly in g["coordinates"]]
        row = out.setdefault(nid, {"id": nid, "facility": want[nid].get("facility"), "state": want[nid].get("state"),
                                   "description": want[nid].get("description"), "created": want[nid].get("creation_date"),
                                   "rings": []})
        row["rings"] += rings
    return list(out.values())


# "EFFECTIVE 2611151701 UTC (1201 LOCAL 11/15/26) UNTIL 2611151850 UTC" in the NOTAM text, and the
# "2611151701-2611151850" range that ends it.
UTC_RANGE = re.compile(r"(\d{10})\s*UTC\b[^.]*?\bUNTIL\s+(\d{10})\s*UTC\b")
TAIL_RANGE = re.compile(r"\b(\d{10})-(\d{10})\s*$")


def _stamp(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%y%m%d%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def tfr_windows(text: str | None, pairs: list[tuple[str | None, str | None]]) -> tuple[list[dict], str | None]:
    """A TFR's windows in UTC and where they came from. The NOTAM text says UTC outright, so it comes first. The XML's
    dateEffective / dateExpire are UTC too, although codeTimeZone names a local zone (the zone the FAA's page shows):
    FDC 6/7113 on 15 Nov 2026 gave 17:01 to 18:50 with codeTimeZone EST, and its text read "EFFECTIVE 2611151701 UTC
    (1201 LOCAL 11/15/26) UNTIL 2611151850 UTC". Cordon reads them the same way (cordon/tfr.py)."""
    text = (text or "").strip()
    found = [(_stamp(a), _stamp(b)) for a, b in UTC_RANGE.findall(text)]
    if not found:
        m = TAIL_RANGE.search(text)
        found = [(_stamp(m.group(1)), _stamp(m.group(2)))] if m else []
    basis = "notam-text"
    if not any(s and e for s, e in found):
        found = []
        for a, b in pairs:
            try:
                found.append((_dt(a + "Z"), _dt(b + "Z")) if a and b else (None, None))
            except ValueError:
                continue
        basis = "xml-dates"
    out = []
    for s, e in found:
        w = {"start": _iso(s), "end": _iso(e)} if s and e and e > s else None
        if w and w not in out:
            out.append(w)
    return sorted(out, key=lambda w: w["start"]), (basis if out else None)


def tfr_detail(body: bytes) -> dict:
    """Altitudes and the schedule from a TFR's XNOTAM XML. `windows` are UTC (see tfr_windows); `effective`,
    `expires` and `time_zone` are kept as the XML writes them."""
    root = ET.fromstring(body)
    def first(tag):
        el = root.find(".//" + tag)
        return el.text.strip() if el is not None and el.text else None
    def texts(tag):
        return [(el.text or "").strip() or None for el in root.iter(tag)]
    windows, basis = tfr_windows(first("txtDescrTraditional"), list(zip(texts("dateEffective"), texts("dateExpire"))))
    areas = []
    for a in root.iter("aseTFRArea"):
        areas.append({"name": (a.findtext("txtName") or "").strip() or None,
                      "upper": f"{a.findtext('valDistVerUpper')} {a.findtext('uomDistVerUpper')} {a.findtext('codeDistVerUpper')}",
                      "lower": f"{a.findtext('valDistVerLower')} {a.findtext('uomDistVerLower')} {a.findtext('codeDistVerLower')}"})
    return {"issued_utc": (first("dateIssued") or "") + "Z" if first("dateIssued") else None,
            "effective": first("dateEffective"), "expires": first("dateExpire"), "time_zone": first("codeTimeZone"),
            "windows": windows, "window_basis": basis, "local_name": first("txtLocalName"), "areas": areas}


# ---------- Orbit ----------

def orbit_read(body: bytes) -> dict:
    s = json.loads(body)
    up = [{k: u.get(k) for k in ("id", "name", "net", "net_precision", "window_start", "window_end", "status",
                                 "provider", "provider_countries", "vehicle", "mission", "mission_type", "orbit", "pad",
                                 "location", "lat", "lon", "pad_country", "ll2_url")} for u in s.get("upcoming") or []]
    areas = []
    for w in (s.get("navwarn") or {}).get("areas") or []:
        for a in w.get("areas") or []:
            ring = [list(c) for c in a.get("coords") or []]
            if len(ring) >= 3:
                if ring[0] != ring[-1]:
                    ring.append(list(ring[0]))
                areas.append({"source": "orbit-navwarn", "key": w.get("key"), "label": a.get("label"),
                              "hazard": w.get("hazard"), "regions": w.get("regions"),
                              "ring": notam.unwrap(ring), "windows": w.get("windows") or [],
                              "broadcasts": w.get("broadcasts") or w.get("ids")})
    # GCAT launches (Orbit keeps 30 days): enough of each for matching and for the history ledger.
    launches = [{k: l.get(k) for k in ("launch_tag", "date", "time", "time_uncertain", "vehicle", "variant", "site_code",
                                       "site", "pad", "flight", "mission", "agency", "launchers", "category", "kind",
                                       "outcome", "payloads_cataloged")}
                | {"payloads": [{k: p.get(k) for k in ("name", "state", "owner", "op_orbit", "inc", "jcat") if k in p}
                                for p in l.get("payloads") or []]}
                for l in s.get("launches") or []]
    return {"generated_at": s.get("generated_at"), "upcoming": up, "areas": areas, "launches": launches}


# ---------- Matching ----------

def _windows_of(area: dict) -> list[tuple[datetime, datetime]]:
    out = []
    for w in area.get("windows") or []:
        try:
            out.append((_dt(w["start"]), _dt(w["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def time_match(net: datetime, windows) -> tuple[datetime, datetime] | None:
    for s, e in windows:
        if e - s <= timedelta(hours=WINDOW_MAX_H) and s - timedelta(hours=BEFORE_H) <= net <= e:
            return s, e
    return None


def corridor_bands(corridors: list[dict], lat: float, lon: float, within_nm: float = 15) -> list[dict] | None:
    best = None
    for c in corridors:
        d = notam.haversine_nm(lat, lon, c["pad"][1], c["pad"][0])
        if d <= within_nm and (best is None or d < best[0]):
            best = (d, c)
    return best[1]["bands"] if best else None


def match(upcoming: list[dict], areas: list[dict], corridors: list[dict], recent: list[dict]) -> list[dict]:
    rows = []
    for u in upcoming:
        if u.get("lat") is None or not u.get("net"):
            continue
        net = _dt(u["net"])
        bands = corridor_bands(corridors, u["lat"], u["lon"])
        for a in areas:
            hit = time_match(net, _windows_of(a))
            if not hit:
                continue
            la, lo = notam.centroid(a["ring"])
            az = history.bearing(u["lat"], u["lon"], la, lo)
            dist = notam.haversine_nm(u["lat"], u["lon"], la, lo)
            if bands is not None:
                # Inside a band's azimuths (+-5 degrees) and its downrange distances (x0.5 - 50 NM to x1.25 + 100 NM).
                place = any(b["from"] - 5 <= az < b["to"] + 5
                            and b["downrange_nm"][0] * 0.5 - 50 <= dist <= b["downrange_nm"][1] * 1.25 + 100
                            for b in bands)
                place_basis = ("azimuth band and downrange distance seen in the history for this pad" if place
                               else "outside the azimuth bands and distances in the history for this pad")
            else:
                place = dist <= PLACE_NM
                place_basis = f"within {PLACE_NM} NM of the pad (no history for this pad)" if place else f"over {PLACE_NM} NM from the pad"
            level = "time and place" if place else "time"
            grouped = None
            if place:
                for g in recent:
                    site = g.get("site") or {}
                    if g.get("time") and site.get("lat") is not None:
                        t = _dt(g["time"])
                        if hit[0] - timedelta(hours=BEFORE_H) <= t <= hit[1] and notam.haversine_nm(
                                site["lat"], site["lon"], u["lat"], u["lon"]) <= 30:
                            grouped = {"launch_tag": g["launch_tag"], "time": g["time"], "vehicle": g["vehicle"]}
                            level = "grouped"
            rows.append({"launch": u["id"], "launch_name": u["name"], "net": u["net"], "area": a.get("key") or a.get("id"),
                         "area_source": a.get("source"), "window": [_iso(hit[0]), _iso(hit[1])], "level": level,
                         "azimuth": round(az, 1), "distance_nm": round(dist), "place_basis": place_basis,
                         "inclination_est": history.inclination(u["lat"], az), "grouped_with": grouped})
    return rows


def tfr_areas(tfrs: list[dict], details: dict) -> list[dict]:
    """TFRs as areas for matching, with the UTC windows read from each TFR's XML (tfr_detail). A TFR whose XML
    was not read has no window and is shown but not time-matched."""
    out = []
    for t in tfrs:
        d = t.get("detail") or details.get(t["id"]) or {}
        for i, ring in enumerate(t["rings"]):
            out.append({"source": "faa-tfr", "id": f"FDC {t['id']}", "label": t.get("description"), "ring": ring,
                        "windows": list(d.get("windows") or []), "detail": d or None})
    return out


TFR_ID = re.compile(r"^(\d)/(\d{4})$")


def tfr_xml_url(nid: str) -> str | None:
    m = TFR_ID.match(nid)
    return TFR_XML.format(a=m.group(1), b=m.group(2)) if m else None
