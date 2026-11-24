"""Live lanes and launch matching.

  tfr     FAA temporary flight restrictions (tfr.faa.gov, no key): the list, the shapes from the FAA's own map
          service, and each SPACE OPERATIONS TFR's XML for its altitudes. Only space operations are kept.
  orbit   Orbit's published snapshot (orbit.theintelligence.company/data/snapshot.json, one request): its
          scheduled launches, its launch-hazard navigational warnings (NGA, NAVAREA XI) and GCAT's launches of
          the last 30 days. Launch reads them rather than fetching those sources a second time.
  cordon  Cordon's published feed (cordon.theintelligence.company/data/feed.geojson, one request): NGA's
          navigational warnings in its `launch` category, with the windows, hazard and cancels Cordon parses
          (method cordon-feed-1.1). Cordon is the suite's one NGA reader (decided 17 Nov 2026); Launch takes the
          warnings with a launch, debris or reentry hazard and leaves the missile firings. Orbit's own copy of
          them is no longer used.
  nms     FAA NOTAM Management Service NOTAMs through Cordon (launch/nms.py): Cordon holds the keys and pulls
          them (decided 18 Nov 2026); Launch reads its launch-areas subset and keeps closures by its own rules.

Matching, three levels, each named on the page:
  time            a scheduled launch's NET falls in an area's window of WINDOW_MAX_H (six) hours or less, or up to
                  an hour before it opens (Orbit's rule, method orbit-2.2, rule 5, with four hours; widened on 22 Nov
                  2026: Ariane 6 VA271's own NOTAMs and NAVAREA IV warning ran 4.9 to 5.7 hours and matched nothing).
  time and place  the same, and the area lies in an azimuth band where the charted history has closures from that
                  pad, or (no history for the pad) within PLACE_NM of it.
  grouped         after the launch: GCAT dates a launch from that site inside the window of an area that had
                  matched on time and place. History events are grouped as charted.
None of these says an area is for a launch; each says which coincidence holds.

Named, beside the level: the notice's text has the launch's mission designator (a word of letters and digits in
LL2's mission name, hyphens ignored: NROL-136, VA271 if LL2 had it, LE-04), `named_by` "mission"; or the
vehicle's name (ARIANE 6 for an Ariane 64) in an area that also fits in place, `named_by` "vehicle". A mission
designator also lets a window up to NAMED_MAX_DAYS match, since a debris area that names its launch often stays
open for the backup days (Tahiti's A1508/26 for NROL-136, five days). Still a coincidence of words: it is shown as
such.
"""
from __future__ import annotations

import json
import math
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
CORDON_FEED = "https://cordon.theintelligence.company/data/feed.geojson"
NGA_PAGE = "https://msi.nga.mil/NavWarnings"
NGA_SERIES = {"4": ("navarea-iv", "NAVAREA IV"), "12": ("navarea-xii", "NAVAREA XII"), "A": ("hydrolant", "HYDROLANT"),
              "P": ("hydropac", "HYDROPAC"), "C": ("hydroarc", "HYDROARC")}
WINDOW_MAX_H = 6
NAMED_MAX_DAYS = 7
BEFORE_H = 1
PLACE_NM = 1500
NEAR_PAD_NM = 30       # an area this near the pad is the pad's own hazard area: place, whatever the bands say
MIN_BAND_EVENTS = 10   # a pad with fewer charted events has bands too thin to rule an area out (most US pads)
AZ_TOL = 5             # degrees either side of a launch azimuth for an inclination flown from the site
MIN_FLOWN = 5          # launches GCAT shows at an inclination (to 0.5 degree) before it counts as the site's
SITE_NM = 30           # a GCAT launch this near the pad counts as flown from its site


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


# The FAA issues amateur high-power rocketry TFRs under 14 CFR 91.143 too, in the same SPACE OPERATIONS class: FDC 6/8694
# (Boise, 21 Nov 2026) names Tripoli Idaho Rocketry as its point of contact. The operator's words in the text mark them.
AMATEUR_ROCKETRY = re.compile(r"\b(?:ROCKETRY|TRIPOLI|ROCKET (?:CLUB|SOCIETY))\b", re.I)
AMATEUR_LABEL = "amateur/high-power rocketry (FAA 91.143)"


def tfr_activity(text: str | None) -> str | None:
    """The label for a TFR whose text names an amateur rocketry operator, else None. The TFR is kept either way."""
    return AMATEUR_LABEL if AMATEUR_ROCKETRY.search(text or "") else None


def tfr_detail(body: bytes) -> dict:
    """Altitudes and the schedule from a TFR's XNOTAM XML. `windows` are UTC (see tfr_windows); `effective`,
    `expires` and `time_zone` are kept as the XML writes them. `activity` is tfr_activity's label; the text itself,
    which carries contact telephone numbers, is not kept."""
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
            "windows": windows, "window_basis": basis, "local_name": first("txtLocalName"), "areas": areas,
            "activity": tfr_activity(first("txtDescrTraditional"))}


# ---------- Orbit ----------

def orbit_read(body: bytes) -> dict:
    s = json.loads(body)
    up = [{k: u.get(k) for k in ("id", "name", "net", "net_precision", "window_start", "window_end", "status",
                                 "provider", "provider_countries", "vehicle", "mission", "mission_type", "orbit", "pad",
                                 "location", "lat", "lon", "pad_country", "ll2_url", "last_updated")}
          for u in s.get("upcoming") or []]
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
    # When Orbit read LL2 (its upcoming lane), for the side-by-side check with Launch's own read (launch/compare.py).
    read = ((s.get("lanes") or {}).get("upcoming") or {}).get("fetched_at")
    return {"generated_at": s.get("generated_at"), "upcoming": up, "upcoming_read_at": read, "areas": areas,
            "launches": launches}


# ---------- Cordon ----------

def _nga_names(cordon_id: str) -> tuple[str, str] | None:
    """'cordon:navwarn:4-1081-2026' -> ('navarea-iv-1081-26', 'NAVAREA IV 1081/26'): the key Orbit used, so match
    ids stay the same across the switch, and NGA's own way of writing the number."""
    m = re.match(r"cordon:navwarn:([A-Z0-9]+)-(\d+)-(\d{4})$", cordon_id or "")
    if not m or m.group(1) not in NGA_SERIES:
        return None
    slug, name = NGA_SERIES[m.group(1)]
    yy = m.group(3)[2:]
    return f"{slug}-{m.group(2)}-{yy}", f"{name} {m.group(2)}/{yy}"


AREA_LETTER = re.compile(r"(?m)^\s*([A-Z])\.\s+")


def _rings(geom: dict | None) -> list[list[list[float]]]:
    if not geom:
        return []
    if geom.get("type") == "Polygon":
        return [geom["coordinates"][0]]
    if geom.get("type") == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def cordon_read(body: bytes) -> dict:
    """NGA launch, debris and reentry warnings from Cordon's feed, as areas for matching. A warning whose
    `measures.hazard` is null (a missile firing, which Cordon also files under `launch`) is left out."""
    doc = json.loads(body)
    nga = (doc.get("health") or {}).get("nga-navwarnings") or {}
    areas, skipped = [], 0
    for f in doc.get("features") or []:
        p = f.get("properties") or {}
        m = p.get("measures") or {}
        if not p.get("id", "").startswith("cordon:navwarn:") or m.get("category") != "launch":
            continue
        names = _nga_names(p["id"])
        if not m.get("hazard") or not names:
            skipped += 1
            continue
        key, number = names
        broadcasts = [{"id": number, "issuer": "nga", "issued": p.get("data_as_of"), "url": NGA_PAGE,
                       "cordon_id": p["id"]}]
        for r in m.get("rebroadcasts") or []:
            rn = _nga_names(r.get("id") or "")
            broadcasts.append({"id": rn[1] if rn else r.get("number"), "issuer": "nga", "issued": r.get("issued"),
                               "url": NGA_PAGE, "cordon_id": r.get("id")})
        rings = _rings(f.get("geometry"))
        labels = [a.get("label") or "" for a in m.get("area_windows") or []]
        if len(labels) != len(rings):  # lettered areas without windows of their own: the letters from the text
            labels = AREA_LETTER.findall(m.get("text") or "")
        if len(labels) != len(rings):
            labels = [""] * len(rings)
        regions = [x.upper() for x in (m.get("sea"), m.get("place")) if x]
        for ring, label in zip(rings, labels):
            ring = [list(c[:2]) for c in ring]
            if len(ring) < 3:
                continue
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            areas.append({"source": "cordon-navwarn", "key": key, "label": label, "hazard": m.get("hazard"),
                          "regions": regions, "ring": notam.unwrap(ring), "windows": m.get("windows") or [],
                          "window_mode": m.get("window_mode"), "expires": p.get("valid_until"),
                          "cancels": m.get("cancels") or [], "broadcasts": broadcasts, "cordon_id": p["id"],
                          "text": m.get("text") or ""})   # for named_in; not written to the snapshot
    return {"generated_at": doc.get("generated_at"), "nga_state": nga.get("state"),
            "missile_firings_left_out": skipped, "areas": areas}


# ---------- Matching ----------

def _windows_of(area: dict) -> list[tuple[datetime, datetime]]:
    out = []
    for w in area.get("windows") or []:
        try:
            out.append((_dt(w["start"]), _dt(w["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def time_match(net: datetime, windows, max_h: float = WINDOW_MAX_H) -> tuple[datetime, datetime] | None:
    for s, e in windows:
        if e - s <= timedelta(hours=max_h) and s - timedelta(hours=BEFORE_H) <= net <= e:
            return s, e
    return None


# ---------- a notice that names the launch ----------

def _joined(s: str) -> str:
    """Upper case, hyphens inside a designator dropped: "NROL-136" and "NROL136" read the same."""
    return re.sub(r"(?<=[A-Z0-9])-(?=[A-Z0-9])", "", (s or "").upper())


def mission_words(u: dict) -> list[str]:
    """The launch's designators: words of LL2's mission name (and the name after "|") with letters and digits,
    four characters or more once joined. "Amazon Leo (LE-04)" -> ["LE04"]; "Starlink Group 31-2" -> [] (no letter)."""
    name = u.get("name") or ""
    src = " ".join([u.get("mission") or "", name.split("|", 1)[1] if "|" in name else ""])
    out = []
    for w in re.findall(r"[A-Z0-9]+", _joined(src)):
        if len(w) >= 4 and re.search(r"[A-Z]", w) and re.search(r"\d", w) and w not in out:
            out.append(w)
    return out


def vehicle_pattern(v: str | None) -> re.Pattern | None:
    """The vehicle's name as a notice writes it: its words up to the first number, and that number's first digit
    ("Ariane 64 Block 2" -> ARIANE 6, "Falcon 9 Block 5" -> FALCON 9, "Long March 2C" -> LONG MARCH 2C), at least
    four letters. None when there is nothing to read."""
    parts, words = [], re.split(r"[\s-]+", (v or "").upper().strip())
    for w in words:
        if not w or w == "BLOCK":
            break
        if w[0].isdigit():   # "2C" and "1A" whole; "64" and "2.1B/FREGAT" by the first digit
            parts.append(w if re.fullmatch(r"\d+[A-Z]+", w) else w[0])
            break
        parts.append(w)
        if re.search(r"\d", w):
            break
    if sum(c.isalpha() for c in "".join(parts)) < 4:
        return None
    tail = "" if parts[-1].isdigit() and len(parts[-1]) == 1 else r"\b"
    return re.compile(r"\b" + r"[\s-]*".join(re.escape(x) for x in parts) + tail)


def named_in(u: dict, text: str | None) -> tuple[str, str] | None:
    """(the words as the text writes them, "mission") when the text has a mission designator, (words, "vehicle") when
    it has the vehicle's name, else None."""
    if not text:
        return None
    up = text.upper()
    for w in mission_words(u):
        m = re.search(r"\b" + "-?".join(re.escape(c) for c in w) + r"\b", up)
        if m:
            return m.group(0), "mission"
    pat = vehicle_pattern(u.get("vehicle"))
    m = pat.search(up) if pat else None
    return (m.group(0), "vehicle") if m else None


def corridor_of(corridors: list[dict], lat: float, lon: float, within_nm: float = 15) -> dict | None:
    best = None
    for c in corridors:
        d = notam.haversine_nm(lat, lon, c["pad"][1], c["pad"][0])
        if d <= within_nm and (best is None or d < best[0]):
            best = (d, c)
    return best[1] if best else None


def corridor_bands(corridors: list[dict], lat: float, lon: float, within_nm: float = 15) -> list[dict] | None:
    c = corridor_of(corridors, lat, lon, within_nm)
    return c["bands"] if c else None


def flown_inclinations(flown: list[dict] | None, lat: float, lon: float, within_nm: float = SITE_NM,
                       min_n: int = MIN_FLOWN) -> list[float]:
    """Inclinations (to 0.5 degree) GCAT shows flown at least `min_n` times from within `within_nm` of the pad, so a
    one-off orbit does not open its azimuth (24 Nov 2026: about 80 of 360 degrees pass at Vandenberg and the Cape)."""
    n: dict[float, int] = {}
    for f in flown or []:
        if f.get("inc") is not None and f.get("lat") is not None and notam.haversine_nm(
                lat, lon, f["lat"], f["lon"]) <= within_nm:
            k = round(f["inc"] * 2) / 2
            n[k] = n.get(k, 0) + 1
    return sorted(k for k, c in n.items() if c >= min_n)


def launch_azimuths(lat: float, inc: float) -> list[float]:
    """The two launch azimuths for inclination `inc` from latitude `lat` (spherical earth, cos i = cos(lat) sin(az)).
    An inclination below the latitude cannot be flown directly: due east (or west, retrograde) is the nearest."""
    s = math.cos(math.radians(inc)) / math.cos(math.radians(lat))
    if abs(s) >= 1:
        return [90.0] if s > 0 else [270.0]
    b = math.degrees(math.asin(s))
    return [b % 360, (180 - b) % 360]


def _az_off(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def place_test(corridor: dict | None, incs: list[float], lat: float, az: float, dist: float) -> tuple[bool, str]:
    """Whether an area fits a launch from this pad in place, and why. A pad's charted bands (patterns.json) rule an
    area out only when they rest on MIN_BAND_EVENTS events or more; below that, an area on the azimuth (+-AZ_TOL) of
    an inclination GCAT shows flown from the site, within PLACE_NM, fits too. An area within NEAR_PAD_NM always fits.
    A pad with no bands and no GCAT launches keeps the plain PLACE_NM rule."""
    if dist <= NEAR_PAD_NM:
        return True, f"within {NEAR_PAD_NM} NM of the pad"
    bands = corridor["bands"] if corridor else None
    if bands:
        # Inside a band's azimuths (+-5 degrees) and its downrange distances (x0.5 - 50 NM to x1.25 + 100 NM).
        if any(b["from"] - 5 <= az < b["to"] + 5
               and b["downrange_nm"][0] * 0.5 - 50 <= dist <= b["downrange_nm"][1] * 1.25 + 100 for b in bands):
            return True, "azimuth band and downrange distance seen in the history for this pad"
    events = (corridor or {}).get("events")
    rich = bool(bands) and (events is None or events >= MIN_BAND_EVENTS)
    if rich or (bands and not incs):
        return False, "outside the azimuth bands and distances in the history for this pad"
    if not incs:
        if dist <= PLACE_NM:
            return True, f"within {PLACE_NM} NM of the pad (no history for this pad)"
        return False, f"over {PLACE_NM} NM from the pad"
    thin = f"the pad's charted history is thin ({events or 0} events)"
    if dist > PLACE_NM:
        return False, f"over {PLACE_NM} NM from the pad; {thin}"
    fits = [i for i in incs if any(_az_off(az, x) <= AZ_TOL for x in launch_azimuths(lat, i))]
    if fits:
        best = min(fits, key=lambda i: min(_az_off(az, x) for x in launch_azimuths(lat, i)))
        return True, (f"on the azimuth of a {best:g}-degree orbit flown from this site (GCAT), within {PLACE_NM} NM; "
                      f"{thin}")
    return False, f"off the azimuths of the orbits flown from this site (GCAT); {thin}"


def match(upcoming: list[dict], areas: list[dict], corridors: list[dict], recent: list[dict],
          flown: list[dict] | None = None) -> list[dict]:
    """`flown`: GCAT launches as {lat, lon, inc} (history/ledger.json), read where a pad's charted bands are thin."""
    rows = []
    for u in upcoming:
        if u.get("lat") is None or not u.get("net"):
            continue
        net = _dt(u["net"])
        corridor = corridor_of(corridors, u["lat"], u["lon"])
        incs = flown_inclinations(flown, u["lat"], u["lon"])
        for i, a in enumerate(areas):
            if a.get("off_live"):   # a NOTAM whose text says it is not a launch (nms.off_live): shown on request only
                continue
            wins = _windows_of(a)
            hit = time_match(net, wins)
            name = named_in(u, a.get("text"))
            if not hit and name and name[1] == "mission":
                hit = time_match(net, wins, NAMED_MAX_DAYS * 24)
            if not hit:
                continue
            la, lo = notam.centroid(a["ring"])
            az = history.bearing(u["lat"], u["lon"], la, lo)
            dist = notam.haversine_nm(u["lat"], u["lon"], la, lo)
            place, place_basis = place_test(corridor, incs, u["lat"], az, dist)
            level = "time and place" if place else "time"
            if name and name[1] == "vehicle" and not place:
                name = None   # a vehicle's name alone: many launches share it, so it counts only with the place
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
                         "area_i": i, "area_source": a.get("source"), "window": [_iso(hit[0]), _iso(hit[1])], "level": level,
                         "azimuth": round(az, 1), "distance_nm": round(dist), "place_basis": place_basis,
                         "inclination_est": history.inclination(u["lat"], az), "grouped_with": grouped,
                         "named": name[0] if name else None, "named_by": name[1] if name else None})
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
