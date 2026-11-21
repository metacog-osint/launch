"""Import Launch's charted notices (a Google My Maps KML export) into Launch's history.

The source map is a hand-built record, 2022 onward: one name per launch or event ("24 Sep 26_ 0846 UTC_LM-6A_
Yaogan-40 04A-C"), shared by every shape of that event: closure-area polygons (each carrying the NOTAM or
navigational-warning text and usually a source link), flight-path lines from the pad, and points. Layers sort
events by actor (Chinese, Russian, rest of world), exercises and unknown notices.

Each area keeps the polygon as charted on the map ("charted") and, when its text is a NOTAM, what Launch's own
parser reads from that text, with the distance between the two, so a hand-charting slip or a parse error shows.
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import notam, public

NS ={"k": "http://www.opengis.net/kml/2.2"}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                      "DEC"], 1)}
LAYER_ACTOR = {"Previous Chinese Launches": "CN", "2026 - Previous Chinese Launches": "CN",
               "Previous Russian Launches": "RU", "Upcoming Launches": None, "Previous ROW Launches": None,
               "Previous Exercise NOTAMs": None, "Previous Unknown NOTAMs": None, "Unknown NOTAMs": None}
LAYER_KIND = {"Previous Chinese Launches": "launch", "2026 - Previous Chinese Launches": "launch",
              "Previous Russian Launches": "launch", "Previous ROW Launches": "launch",
              "Upcoming Launches": "upcoming", "Previous Exercise NOTAMs": "exercise",
              "Previous Unknown NOTAMs": "unknown", "Unknown NOTAMs": "unknown"}
SKIP_LAYERS = {"BLANK FOR CLEAN SNIPPETS"}
# "24 Sep 26_ 0846 UTC_LM-6A_ Yaogan-40", "Dec 25_2326 UTC_LM-8A_...", "13-26 Aug 26_2100-1800 UTC_Russian Nav Warn"
NAME = re.compile(r"\s*(?:(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*)?([A-Za-z]{3})[a-z]*\.?(?:\s+'?(\d{4}|\d{2}))?\s*[_-]\s*"
                  r"(?:~?(\d{4})(?:\s*-\s*(\d{4}))?\s*(?:UTC|Z)?\s*[_-]?)?\s*(.*)$", re.S)
URL = re.compile(r"https?://[^\s<>\"']+", re.I)
# Vehicle names as the map writes them -> launching state, for layers that mix states (rest of world, upcoming).
VEHICLE_STATE = [
    (re.compile(r"^(LM|CZ|LONG MARCH|KZ|KUAIZHOU|ZQ|ZHUQUE|CERES|GRAVITY|JIELONG|SD-3|KINETICA|LIJIAN|TIANLONG|"
                r"HYPERBOLA|SQX|SMART DRAGON|PALLAS|NEBULA|YUNHAI)", re.I), "CN"),
    (re.compile(r"^(SOYUZ|ANGARA|PROTON|ROKOT|YARS|BULAVA|SARMAT|START|VOLNA|SINEVA)", re.I), "RU"),
    (re.compile(r"^(FALCON|F9|STARSHIP|ELECTRON|NEUTRON|ATLAS|VULCAN|NEW GLENN|MINOTAUR|PEGASUS|ANTARES|FIREFLY|"
                r"ALPHA|SLS|DELTA|TRIDENT|MINUTEMAN|SENTINEL)", re.I), "US"),
    (re.compile(r"^(H-?3|H-?IIA|H-?2A|EPSILON|KAIROS)", re.I), "JP"),
    (re.compile(r"^(PSLV|GSLV|LVM|SSLV|AGNI)", re.I), "IN"),
    (re.compile(r"^(NURI|KSLV|HANBIT)", re.I), "KR"),
    (re.compile(r"^(CHOLLIMA|HWASONG|UNHA)", re.I), "KP"),
    (re.compile(r"^(SIMORGH|QAEM|ZOLJANAH|QASED|SAFIR)", re.I), "IR"),
    (re.compile(r"^(ARIANE|VEGA)", re.I), "EU"),
]


def clean_kml(raw: bytes | str) -> str:
    t = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return re.sub("[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", t)


def _coords(el) -> list[list[float]]:
    out = []
    for tok in (el.text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            out.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
    return out


def _geoms(pm) -> list[tuple[str, list]]:
    out = []
    for poly in pm.iter("{%s}Polygon" % NS["k"]):
        c = poly.find(".//k:outerBoundaryIs//k:coordinates", NS)
        if c is not None:
            out.append(("polygon", _coords(c)))
    for ln in pm.iter("{%s}LineString" % NS["k"]):
        c = ln.find("k:coordinates", NS)
        if c is not None:
            out.append(("line", _coords(c)))
    for pt in pm.iter("{%s}Point" % NS["k"]):
        c = pt.find("k:coordinates", NS)
        if c is not None and _coords(c):
            out.append(("point", _coords(c)[0]))
    return out


CANCELLED = re.compile(r"(?i)\bcancel+ed\b")
# Publicly available information only. The source map also holds notes that are not public; none of that is
# imported. Kept: NOTAMs and official navigational or coastal warnings. The terms that mark a note as not public
# (RESTRICTED, RESTRICTED_URL, POSITION_TOOL) are not written in this public file: they are in the git-ignored
# history/source/terms.json, on the machine that holds the export, and load() refuses to run until use_terms()
# or load_terms() has set them.
#
# A note that names a restricted source takes its position with it:
#   - a Launch Sites point whose note names one is not imported, and neither is a flight path or a point drawn
#     at that position (within AT_NM) in any event;
#   - an event's point whose own note names one is not imported.
# A flight-path line or a closure area whose own note names one is kept and only the note is withheld: the
# shape is a hand-drawn path or a notice's area. The exception is a note that names a position tool
# (POSITION_TOOL): then the shape itself came from that tool, and no shape of that placemark is imported
# (15 Nov 2026).
# An official-warning text (OFFICIAL_TEXT) is imported only when it holds a coordinate: one with none may be an
# analyst's note that happens to use the word, so it is withheld, and a point on it has no notice behind it
# (15 Nov 2026).
# The Launch Sites layer's own notes are not imported at all, and which of its points are published is decided
# in public.py against history/public_sites.json.
#
# Ships and bare points in the event layers:
#   - a placemark whose name reads as a ship (public.SHIP: YW-*, Yuan Wang, Liao Wang, "ship", "vessel") is a
#     ship, not a launch or a notice, and is not imported, name or position;
#   - an event's point is imported only when its own placemark carries a notice (a NOTAM or a kept official
#     warning). A point with no note, or with a note that is not a notice, has no public source behind it;
#   - an event left with no date, no notice and no shape is not imported.
AT_NM = 0.5
TERMS_FILE = Path(__file__).resolve().parents[1] / "history" / "source" / "terms.json"
_NOTHING = re.compile(r"(?!)")
RESTRICTED = RESTRICTED_URL = POSITION_TOOL = _NOTHING  # set by use_terms(); load() refuses until then
_TERMS_SET = False


def use_terms(doc: dict) -> None:
    """Set the restricted-source patterns from a terms document: {"restricted", "restricted_url", "position_tool"},
    each a regular expression (matched without case). Tests pass made-up terms; the import passes the private file."""
    global RESTRICTED, RESTRICTED_URL, POSITION_TOOL, _TERMS_SET
    RESTRICTED = re.compile(doc["restricted"], re.I)
    RESTRICTED_URL = re.compile(doc["restricted_url"], re.I)
    POSITION_TOOL = re.compile(doc["position_tool"], re.I)
    _TERMS_SET = True


def load_terms(*paths: Path) -> Path:
    """Read the private terms file (TERMS_FILE, or the first of `paths` that exists) into use_terms()."""
    for p in [*paths, TERMS_FILE]:
        if p and Path(p).is_file():
            use_terms(json.loads(Path(p).read_text(encoding="utf-8")))
            return Path(p)
    raise SystemExit("History not imported: the private term file history/source/terms.json is not here. The "
                     "import runs only on the machine that holds it; see CLAUDE.md, 'Public gate for the map'.")
# Any latitude written as digits and a hemisphere ("30-00N", "3000.5N", "30 N"): looser than notam.coords on
# purpose, since warnings write coordinates many ways and the test is only whether the text holds one.
HAS_COORD = re.compile(r"\d+[^A-Za-z0-9]{0,3}[NS]\b", re.I)
# A line of the map's own about where a notice came from ("SOURCE: <link>", "SOURCE: <who>"): not part of
# the notice, and it can name a person or an office, so it is never published (15 Nov 2026).
SOURCE_LINE = public.SOURCE_LINE
OFFICIAL_TEXT = re.compile(r"NAVAREA|HYDROPAC|HYDROLANT|HYDROARC|COASTAL WARNING|NAVTEX|PRIP|NAVIP|"
                           r"NAV(?:IGATIONAL)? ?WARN|\bWARNING\b|\bNOTAM\b", re.I)


def parse_name(name: str) -> dict:
    first = (name or "").strip().split("\n")[0].strip()
    rest = " ".join((name or "").strip().split("\n")[1:]).strip()
    # Leading words such as "Canceled -", "NAVWARN" or "Nav Warn_" come before the date: try each start.
    m = None
    for start in [0] + [i + 1 for i, ch in enumerate(first) if ch in " _-"]:
        x = NAME.match(first, start) if start else NAME.match(first)
        if x and x.group(3).upper()[:3] in MONTHS:
            m = x
            break
    out = {"label": first, "cancelled": bool(CANCELLED.search(first)), "extra": rest or None, "day": None, "day_end": None, "month": None, "year": None,
           "hhmm": None, "hhmm_end": None, "vehicle": None, "payload": None}
    if not m or m.group(3).upper()[:3] not in MONTHS:
        return out
    day, day_end, mon, yy, hhmm, hhmm_end, tail = m.groups()
    out.update({"day": int(day) if day else None, "day_end": int(day_end) if day_end else None,
                "month": MONTHS[mon.upper()[:3]], "year": (int(yy) if len(yy) == 4 else 2000 + int(yy)) if yy else None, "hhmm": hhmm, "hhmm_end": hhmm_end})
    bits = [b.strip() for b in (tail or "").split("_") if b.strip()]
    if bits:
        out["vehicle"] = bits[0]
        out["payload"] = " ".join(bits[1:]) or None
    return out


def vehicle_state(vehicle: str | None) -> str | None:
    for rx, cc in VEHICLE_STATE:
        if vehicle and rx.search(vehicle.strip()):
            return cc
    return None


def _notam_year(nm: dict, notams: list[dict]) -> int | None:
    """The year of the event's own NOTAM when the name gives the same month and day (one day either side) in another
    year: "29 Dec 26_~0613 UTC_Jielong-3" holds A4790/25, in force 29 Dec 2025. The name is kept as charted."""
    if not (nm["year"] and nm["month"] and nm["day"]) or nm["year"] == 2099:
        return nm["year"]
    years = [int(n["start"][:4]) for n in notams if n.get("start") and int(n["start"][5:7]) == nm["month"]
             and abs(int(n["start"][8:10]) - nm["day"]) <= 1]
    return years[0] if years and nm["year"] not in years else nm["year"]


def _when(nm: dict, notams: list[dict]) -> tuple[str | None, str]:
    nm = {**nm, "year": _notam_year(nm, notams)}
    if nm["month"] and not nm["year"]:  # "17 Aug_0302 UTC_LM-2C": the year from the first NOTAM's window
        for n in notams:
            if n.get("start") and int(n["start"][5:7]) == nm["month"]:
                nm = {**nm, "year": int(n["start"][:4])}
                break
    """The event's UTC time and how sure: 'time' (date and time in the name), 'date' (no time), 'from notam'
    (no day in the name; taken from a NOTAM window the time falls in), 'month', or None."""
    if not nm["year"] or not nm["month"] or nm["year"] == 2099:  # "31 Dec 99_2359_???" is the map's blank template
        return None, "none"
    if nm["day"]:
        if nm["hhmm"] and int(nm["hhmm"][:2]) < 24 and int(nm["hhmm"][2:]) < 60:
            dt = datetime(nm["year"], nm["month"], nm["day"], int(nm["hhmm"][:2]), int(nm["hhmm"][2:]),
                          tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "time"
        try:
            return datetime(nm["year"], nm["month"], nm["day"], tzinfo=timezone.utc).strftime("%Y-%m-%dT00:00:00Z"), "date"
        except ValueError:
            return None, "none"
    if nm["hhmm"]:  # "Dec 25_2326 UTC": find the day from a NOTAM window that contains that time
        for n in notams:
            if not (n.get("start") and n.get("end")):
                continue
            s = datetime.fromisoformat(n["start"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(n["end"].replace("Z", "+00:00"))
            d = s.replace(hour=int(nm["hhmm"][:2]), minute=int(nm["hhmm"][2:]))
            for cand in (d, d.replace(day=e.day) if e.month == s.month else d):
                if s <= cand <= e and cand.month == nm["month"]:
                    return cand.strftime("%Y-%m-%dT%H:%M:%SZ"), "from notam"
    return f"{nm['year']:04d}-{nm['month']:02d}-01T00:00:00Z", "month"


def _ring_distance_nm(a: list[list[float]], b: list[list[float]]) -> float:
    """Largest distance from any vertex of a to the nearest vertex of b (a rough Hausdorff, NM)."""
    worst = 0.0
    for lo, la in a:
        best = min(notam.haversine_nm(la, lo, lb, lob) for lob, lb in b)
        worst = max(worst, best)
    return worst


def bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def inclination(lat: float, azimuth: float) -> float:
    """Orbital inclination for a launch on `azimuth` from latitude `lat` (spherical earth, no dog-leg):
    cos i = cos(lat) * sin(azimuth). An ascent toward the drop zone is an approximation of the launch azimuth."""
    c = math.cos(math.radians(lat)) * math.sin(math.radians(azimuth))
    return round(math.degrees(math.acos(max(-1.0, min(1.0, c)))), 1)


def load(raw: bytes | str) -> dict:
    """{sites, events, withheld}. `sites` are the Launch Sites layer's points as candidates only (name and
    position, never the map's note on them): public.sites() decides which are published. `withheld` counts what
    was left out and why: {sites, ships: {layer: n}, empty_events: {layer: n}, shapes: {layer: {why: n}}}."""
    if not _TERMS_SET:
        raise SystemExit("History not imported: no restricted-source terms are set (load_terms() reads the "
                         "private file history/source/terms.json).")
    root = ET.fromstring(clean_kml(raw))
    doc = root.find("k:Document", NS)
    sites, events, withheld_at, ships, empty = [], {}, [], Counter(), Counter()
    for fo in doc.findall("k:Folder", NS):
        layer = (fo.findtext("k:name", namespaces=NS) or "").strip()
        if layer in SKIP_LAYERS:
            continue
        for pm in fo.findall(".//k:Placemark", NS):
            name = pm.findtext("k:name", default="", namespaces=NS) or ""
            desc = pm.findtext("k:description", default="", namespaces=NS) or ""
            geoms = _geoms(pm)
            if RESTRICTED.search(notam.clean(name)):
                continue  # a note that is not a public notice
            if layer == "Launch Sites":
                pts = [g for k, g in geoms if k == "point"]
                if pts and RESTRICTED.search(re.sub(r"\s+", " ", notam.clean(desc))):
                    withheld_at.append(pts[0])  # the note names a restricted source: the position goes with it
                elif pts:
                    sites.append({"name": name.strip(), "lon": pts[0][0], "lat": pts[0][1]})
                continue
            if public.SHIP.search(public.key(name)):
                ships[layer] += 1  # a ship, not a launch or a notice: neither its name nor its position
                continue
            key = (layer, name.strip())
            ev = events.setdefault(key, {"layer": layer, "name": name.strip(), "placemarks": []})
            ev["placemarks"].append({"desc": desc, "geoms": geoms})
    out, shapes = [], {}
    for v in events.values():
        e, held = _event(v, withheld_at)
        if held:
            shapes.setdefault(v["layer"], Counter()).update(held)
        if not (e["time"] or e["areas"] or e["paths"] or e["points"] or e["notams"] or e["texts"]):
            empty[v["layer"]] += 1  # no date, no notice and no shape left: nothing public to say about it
            continue
        out.append(e)
    return {"sites": sites, "events": out,
            "withheld": {"sites": len(withheld_at), "ships": dict(ships), "empty_events": dict(empty),
                         "shapes": {layer: dict(c) for layer, c in shapes.items()}}}


def _at_withheld(pts: list[list[float]], withheld_at: list[list[float]]) -> bool:
    return any(notam.haversine_nm(p[1], p[0], w[1], w[0]) <= AT_NM for p in pts for w in withheld_at)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def _event(ev: dict, withheld_at: list[list[float]] | None = None) -> tuple[dict, Counter]:
    """The event as it may be published, and how many of its shapes were left out and why (see AT_NM)."""
    nm = parse_name(ev["name"])
    areas, paths, points, notams, texts, links = [], [], [], [], [], []
    withheld_at, held = withheld_at or [], Counter()
    for pm in ev["placemarks"]:
        desc = pm["desc"]
        for u in URL.findall(desc):
            u = strip_session(html_unescape(u).rstrip(").,"))
            if u not in links and not RESTRICTED_URL.search(u):
                links.append(u)
        parsed = None
        parsed_all = []
        full = notam.clean(desc).strip()
        flat = re.sub(r"\s+", " ", full)  # a restricted term can break across two lines of a note
        # SOURCE lines come off before the notice is parsed, so no parsed field can carry one
        txt = "\n".join(ln for ln in full.split("\n") if not SOURCE_LINE.search(ln)).strip()
        is_notice = bool(notam.HEADER.search(txt) or notam.QLINE.search(txt))
        restricted_note = bool(txt) and not is_notice and bool(RESTRICTED.search(flat))
        position_note = bool(POSITION_TOOL.search(flat) or POSITION_TOOL.search(desc))
        official = False
        if is_notice:
            for piece in notam.split_many(txt) or [txt]:
                try:
                    p = notam.parse(piece)
                except notam.ParseError:
                    continue
                parsed = parsed or p
                parsed_all.append(p)
                if p.get("number") not in [n.get("number") for n in notams]:
                    notams.append(p)
        elif (txt and OFFICIAL_TEXT.search(txt) and not RESTRICTED.search(flat)
              and HAS_COORD.search(scrub(txt)) and OFFICIAL_TEXT.search(scrub(txt))):
            texts.append(scrub(txt))  # the warning, without its SOURCE line
            official = True
        elif txt:
            ev.setdefault("withheld", 0)
            ev["withheld"] += 1
        for kind, g in pm["geoms"]:
            if position_note:
                held["shapes whose own note names a position tool"] += 1
                continue
            if kind == "polygon" and len(g) >= 3:
                ring = notam.unwrap(g if g[0] == g[-1] else g + [g[0]])
                area = {"ring": ring, "derived": "charted on the source map", "notam": None, "text_check": None}
                if parsed:
                    area["notam"] = parsed.get("number")
                    polys = [s for p in parsed_all for s in p["shapes"] if s["kind"] in ("polygon", "circle")]
                    if polys:
                        d = min(_ring_distance_nm(ring, s["ring"]) for s in polys)
                        area["text_check"] = {"max_vertex_nm": round(d, 1),
                                              "agrees": d <= 5.0,
                                              "parsed_from": polys[0]["derived"]}
                areas.append(area)
            elif kind == "line" and len(g) >= 2:
                if _at_withheld(g, withheld_at):
                    held["flight paths drawn at a withheld position"] += 1
                else:
                    paths.append(g)
            elif kind == "point":
                if restricted_note:
                    held["points whose own note names a restricted source"] += 1
                elif _at_withheld([g], withheld_at):
                    held["points at a withheld position"] += 1
                elif not (is_notice or official):
                    held["points with no notice behind them"] += 1
                else:
                    points.append(g)
    when, when_basis = _when(nm, notams)
    layer = ev["layer"]
    actor = LAYER_ACTOR.get(layer) or vehicle_state(nm["vehicle"])
    pad = paths[0][0] if paths else None
    for a in areas:
        la, lo = notam.centroid(a["ring"])
        a["centroid"] = [round(lo, 4), round(la, 4)]
        if pad:
            a["azimuth"] = round(bearing(pad[1], pad[0], la, lo), 1)
            a["downrange_nm"] = round(notam.haversine_nm(pad[1], pad[0], la, lo), 1)
            a["inclination_est"] = inclination(pad[1], a["azimuth"])
    return {
        "id": "hist:" + _slug(f"{layer}-{ev['name'].splitlines()[0]}"),
        "layer": layer, "kind": LAYER_KIND.get(layer, "unknown"), "actor": actor,
        "label": nm["label"], "extra": nm["extra"], "cancelled": nm["cancelled"], "vehicle": nm["vehicle"], "payload": nm["payload"],
        "time": when, "time_basis": when_basis,
        "window_end_hhmm": nm["hhmm_end"], "day_end": nm["day_end"],
        "pad": pad, "areas": areas, "paths": paths, "points": points,
        "notams": [{k: n.get(k) for k in ("number", "type", "refers_to", "locations", "start", "end",
                                           "schedule", "lower", "upper", "issuing_state", "named_states",
                                           "relayed", "launch_related", "checks")} | {"q": n.get("q"), "text": scrub(n["text"])}
                   for n in notams],
        "texts": texts, "links": links, "withheld_notes": ev.get("withheld", 0),
    }, held


def scrub(text: str) -> str:
    """A notice's text without any line that is not part of a public notice (see RESTRICTED and SOURCE_LINE) and
    without links."""
    keep = [ln for ln in text.split("\n") if not (RESTRICTED.search(ln) or SOURCE_LINE.search(ln))]
    return re.sub(URL, "", "\n".join(keep)).strip()


SESSION = re.compile(r"(?i)(?<=[?&;])(?:phpsessid|jsessionid|sid|sessionid|utm_[a-z]+)=[^&#;?]*[&;]?")


def strip_session(url: str) -> str:
    """A link without the session or tracking parameters a browser session added to it (the forum's PHPSESSID)."""
    u = SESSION.sub("", url).replace(";?", "?")
    return u if u == url else re.sub(r"[?&]+(?=#|$)", "", u)


def html_unescape(s: str) -> str:
    import html
    return html.unescape(s)
