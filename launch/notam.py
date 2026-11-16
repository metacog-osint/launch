"""Parse ICAO-format NOTAMs (and the coordinate lists in navigational warnings) into fields and shapes.

What it reads (ICAO Annex 15 / PANS-AIM NOTAM format):
  header   series, number/year and type: NOTAMN (new), NOTAMR (replaces), NOTAMC (cancels), with the
           NOTAM it replaces or cancels
  Q)       FIR / NOTAM code (Q + 2-letter subject + 2-letter condition) / traffic / purpose / scope /
           lower / upper (flight levels) / centre DDMMN DDDMME and radius in NM
  A)-G)    locations (one or more), start, end (EST or PERM allowed), schedule, text, lower and upper limits

Shapes come from the E) text, in this order: polygons (runs of coordinates), circles ("RADIUS 10NM CENTRED
ON ..."), and, only when the text gives none, the Q-line circle, marked approximate. Every shape records how it
was derived. Coordinates the parser cannot read unambiguously (for example the seven-digit "0055535N" in
VCCF A0580/26) are listed under `rejected`, never guessed.

Coordinate forms read (all seen in real notices, 2023-2026):
  N330400E0984900   N3304E09849           prefix hemisphere, DDMM[SS] DDDMM[SS]
  091600N 1185700E  075500.00N 1195800.00E   suffix hemisphere, optional decimal seconds
  2438S 15700W      DDMM DDDMM, suffix
  36 31 00 S 131 00 00 W   05 00 S 164 15 W   spaced degrees, minutes[, seconds]
  59-42.60S 165-49.20E     degrees-decimal minutes (navigational warnings)

The NOTAM Code meanings below are the subset Launch uses, from the ICAO NOTAM Code (Doc 8400, PANS-ABC);
any other code is shown as written.
"""
from __future__ import annotations

import html
import math
import re
from datetime import datetime, timezone

SUBJECT = {
    "RA": "airspace reservation", "RD": "danger area", "RM": "military operating area",
    "RP": "prohibited area", "RR": "restricted area", "RT": "temporary restricted area",
    "WE": "exercises", "WM": "missile, gun or rocket firing", "WP": "parachute jumping exercise",
    "WU": "unmanned aircraft", "WL": "ascent of free balloon", "AF": "flight information region",
}
CONDITION = {
    "CA": "activated", "CD": "deactivated", "CH": "changed", "LW": "will take place", "XX": "plain language",
}

# ICAO location-indicator prefixes -> state, for the FIRs that issue launch and reentry notices. Longest prefix
# wins. A FIR is the issuing state's area of responsibility, not a claim about who launches.
FIR_STATE = {
    "Z": "CN", "ZK": "KP", "ZM": "MN", "RJ": "JP", "RO": "JP", "RK": "KR", "RC": "TW", "RP": "PH",
    "VH": "HK", "VM": "MO", "VV": "VN", "VD": "KH", "VL": "LA", "VT": "TH", "VY": "MM", "VC": "LK",
    "VA": "IN", "VI": "IN", "VE": "IN", "VO": "IN", "VR": "MV", "VG": "BD", "VN": "NP", "OP": "PK",
    "WA": "ID", "WI": "ID", "WR": "ID", "WM": "MY", "WB": "MY", "WS": "SG", "AY": "PG", "AG": "SB",
    "Y": "AU", "NZ": "NZ", "NT": "PF", "NW": "NC", "NF": "FJ", "NC": "CK", "NS": "WS", "NI": "NU",
    "U": "RU", "UA": "KZ", "UT": "UZ", "UK": "UA", "UM": "BY", "UB": "AZ", "UD": "AM", "UG": "GE",
    "K": "US", "PA": "US", "PH": "US", "PG": "US", "PK": "US", "PZ": "US", "C": "CA", "MM": "MX",
    "FM": "MG", "FA": "ZA", "FI": "MU", "FS": "SC", "HK": "KE", "GO": "SN", "SB": "BR", "SC": "CL",
    "SP": "PE", "SA": "AR", "SO": "GF", "TT": "TT", "E": "EU", "EN": "NO", "ES": "SE", "EF": "FI",
    "EG": "GB", "L": "EU", "LF": "FR", "OI": "IR", "OE": "SA", "OM": "AE", "OO": "OM", "LL": "IL",
}
# Text naming the state a notice is issued for, when that is not the issuing FIR's state ("relayed").
NAMED_STATE = [
    ("CN", re.compile(r"\bBY CHINA\b|\bCAA ?CHINA\b|\bCAAC\b|CIVIL AVIATION ADMINISTRATION OF CHINA|\bCHINESE\b")),
    ("RU", re.compile(r"\bRUSSIA(N)?\b|\bROSCOSMOS\b|\bROSAVIATSIA\b")),
    ("US", re.compile(r"\bUNITED STATES\b|\bNASA\b|\bUS SPACE FORCE\b|\bSPACEX\b")),
    ("JP", re.compile(r"\bJAPAN(ESE)?\b|\bJAXA\b")),
    ("KP", re.compile(r"\bDPRK\b|\bNORTH KOREA\b")),
    ("IN", re.compile(r"\bISRO\b|\bINDIA(N)?\b")),
]
LAUNCH_WORDS = re.compile(
    r"AEROSPACE|ROCKET|SPACE ?(?:DEBRIS|LAUNCH|VEHICLE|CRAFT|OPERATIONS|FLIGHT|FLT)|RE-?ENTRY|SPLASH ?DOWN|"
    r"UNBURNED DEBRIS|FALLING (?:DEBRIS|OBJECTS|PARTS)|DEBRIS RETURN|LAUNCH VEHICLE|STAGE|MISSILE")

HEADER = re.compile(r"\b([A-Z])(\d{4})/(\d{2})\s*NOTAM([NRC])(?:\s+([A-Z])(\d{4})/(\d{2}))?")
QLINE = re.compile(
    r"Q\)\s*([A-Z]{4})\s*/\s*Q([A-Z]{2})([A-Z]{2})\s*/\s*([A-Z ]{1,3}?)\s*/\s*([A-Z ]{1,4}?)\s*/\s*([A-Z ]{1,3}?)\s*/"
    r"\s*(\d{3})\s*/\s*(\d{3})\s*/\s*(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})?")
ITEM = re.compile(r"(?:(?<=\s)|(?<=^)|(?<=\)))([A-G])\)\s*")
STAMP = re.compile(r"^(\d{10})\s*(EST)?|^(PERM)")

_SEP = r"[\s,/]*"
COORD_PATTERNS = [
    # prefix hemisphere: N330400E0984900, N3304E09849, N330400.5E0984900.5
    ("prefix", re.compile(r"(?<![A-Z0-9])([NS])\s?(\d{4}|\d{6})(\.\d+)?" + _SEP + r"([EW])\s?(\d{5}|\d{7})(\.\d+)?(?![0-9])")),
    # suffix hemisphere: 091600N 1185700E, 2438S 15700W, 075500.00N 1195800.00E
    ("suffix", re.compile(r"(?<![0-9.])(\d{4}|\d{6})(\.\d+)?\s?([NS])" + _SEP + r"(\d{5}|\d{7})(\.\d+)?\s?([EW])(?![A-Z0-9])")),
    # degrees-decimal minutes: 59-42.60S 165-49.20E, 77-52.0N 061-55.0E
    ("dash", re.compile(r"(?<![0-9])(\d{1,2})-(\d{2}(?:\.\d+)?)\s?([NS])" + _SEP + r"(\d{1,3})-(\d{2}(?:\.\d+)?)\s?([EW])")),
    # spaced: 36 31 00 S 131 00 00 W, 05 00 S 164 15 W
    ("spaced", re.compile(r"(?<![0-9])(\d{1,2})\s(\d{2})(?:\s(\d{2}(?:\.\d+)?))?\s?([NS])" + _SEP +
                          r"(\d{1,3})\s(\d{2})(?:\s(\d{2}(?:\.\d+)?))?\s?([EW])(?![A-Z0-9])")),
]
# Hemisphere tokens with a digit count no form allows, such as 0055535N: reported, not read.
MALFORMED = re.compile(r"(?<![0-9.])(\d{5}|\d{7,8})(?:\.\d+)?\s?([NS])\b|(?<![A-Z0-9])([NS])(\d{5}|\d{7,8})(?=[EW])")
CIRCLE = re.compile(r"(?:RADIUS(?: OF)?|WI(?:THIN)?(?: A)?(?: RADIUS(?: OF)?)?|CIRCLE(?: WITH)?(?: RADIUS)?(?: OF)?)\s*"
                    r"(\d+(?:\.\d+)?)\s*(NM|KM)\b")
CIRCLE_AFTER = re.compile(r"^[\s,]*(?:RADIUS(?: OF)?|WI)\s*(\d+(?:\.\d+)?)\s*(NM|KM)\b")
NM_KM = 1.852


class ParseError(ValueError):
    pass


def clean(text: str) -> str:
    """HTML breaks to newlines, entities decoded, control characters dropped, curly quotes straightened."""
    t = re.sub(r"(?i)<br\s*/?>", "\n", text or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = t.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    t = re.sub("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", t)
    return t.replace("\r\n", "\n").replace("\r", "\n").upper()


def stamp(s: str) -> tuple[str | None, bool, bool]:
    """B)/C) value -> (ISO UTC, estimated, permanent). YYMMDDHHMM is UTC by definition."""
    m = STAMP.match((s or "").strip())
    if not m:
        return None, False, False
    if m.group(3):
        return None, False, True
    d = m.group(1)
    try:
        dt = datetime(2000 + int(d[:2]), int(d[2:4]), int(d[4:6]), int(d[6:8]) % 24, int(d[8:10]), tzinfo=timezone.utc)
    except ValueError:
        return None, False, False
    if d[6:8] == "24":  # 2400 is the end of the day
        dt = dt.replace(hour=0) + (datetime(2000, 1, 2) - datetime(2000, 1, 1))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), bool(m.group(2)), False


def _dms(deg: str, mins: str, secs: str | None, hemi: str, is_lat: bool) -> float | None:
    d, m = int(deg), float(mins)
    s = float(secs) if secs else 0.0
    if m >= 60 or s >= 60 or (is_lat and d > 90) or (not is_lat and d > 180):
        return None
    v = d + m / 60 + s / 3600
    if (is_lat and v > 90) or (not is_lat and v > 180):
        return None
    return round(-v if hemi in "SW" else v, 6)


def _packed(digits: str, frac: str | None, hemi: str, is_lat: bool) -> float | None:
    """DDMM[SS] or DDDMM[SS], with an optional decimal fraction on the last field."""
    n = 2 if is_lat else 3
    deg, mins, secs = digits[:n], digits[n:n + 2], digits[n + 2:]
    if secs:
        return _dms(deg, mins, secs + (frac or ""), hemi, is_lat)
    return _dms(deg, mins + (frac or ""), None, hemi, is_lat)


def coords(text: str) -> tuple[list[dict], list[dict]]:
    """Every coordinate in the text, in order: [{lat, lon, start, end, form}], plus rejected tokens."""
    found, taken = [], []
    for form, rx in COORD_PATTERNS:
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            g = m.groups()
            if form in ("prefix", "suffix"):
                if form == "prefix":
                    (la_h, la, la_f, lo_h, lo, lo_f) = g
                else:
                    (la, la_f, la_h, lo, lo_f, lo_h) = g
                lat = _packed(la, la_f, la_h, True)
                lon = _packed(lo, lo_f, lo_h, False)
            elif form == "dash":
                (ld, lm, la_h, od, om, lo_h) = g
                lat, lon = _dms(ld, lm, None, la_h, True), _dms(od, om, None, lo_h, False)
            else:
                (ld, lm, ls, la_h, od, om, os_, lo_h) = g
                lat, lon = _dms(ld, lm, ls, la_h, True), _dms(od, om, os_, lo_h, False)
            taken.append((m.start(), m.end()))
            if lat is None or lon is None:
                found.append({"bad": m.group(0).strip(), "start": m.start(), "end": m.end()})
                continue
            found.append({"lat": lat, "lon": lon, "start": m.start(), "end": m.end(), "form": form})
    rejected = [{"token": f["bad"], "reason": "out of range"} for f in found if "bad" in f]
    for m in MALFORMED.finditer(text):
        if not any(m.start() < e and s < m.end() for s, e in taken):
            rejected.append({"token": m.group(0).strip(), "reason": "digit count fits no coordinate form"})
            taken.append((m.start(), m.end()))
    good = sorted((f for f in found if "bad" not in f), key=lambda f: f["start"])
    return good, rejected


def _gap_breaks(gap: str) -> bool:
    """True when the text between two coordinates is more than a joiner, so they belong to different shapes."""
    g = re.sub(r"\b(TO|AND|THEN|BACK TO (THE )?START(ING POINT)?|TO BEGINNING|TO START|POINT|PSN|THENCE)\b", " ", gap)
    g = re.sub(r"\b[A-Z]\b\.?|\b\d{1,2}\.", " ", g)  # vertex labels "A." and list numbers "1."
    return len(re.sub(r"[^A-Z]", "", g)) > 12


def circle_ring(lat: float, lon: float, radius_nm: float, n: int = 64) -> list[list[float]]:
    """A geodesic-enough circle (spherical earth) as a closed [lon, lat] ring."""
    r = radius_nm * NM_KM / 6371.0088
    la, lo = math.radians(lat), math.radians(lon)
    ring = []
    for i in range(n + 1):
        b = 2 * math.pi * (i % n) / n
        la2 = math.asin(math.sin(la) * math.cos(r) + math.cos(la) * math.sin(r) * math.cos(b))
        lo2 = lo + math.atan2(math.sin(b) * math.sin(r) * math.cos(la), math.cos(r) - math.sin(la) * math.sin(la2))
        ring.append([round((math.degrees(lo2) + 540) % 360 - 180, 5), round(math.degrees(la2), 5)])
    return ring


def unwrap(ring: list[list[float]]) -> list[list[float]]:
    """Keep a ring that crosses the antimeridian continuous (longitudes beyond +-180), as MapLibre expects."""
    out = [list(ring[0])]
    for lon, lat in ring[1:]:
        prev = out[-1][0]
        while lon - prev > 180:
            lon -= 360
        while lon - prev < -180:
            lon += 360
        out.append([lon, lat])
    return out


def shapes_from_text(text: str) -> tuple[list[dict], list[dict]]:
    """Polygons and circles written in the text, each with how it was derived."""
    pts, rejected = coords(text)
    shapes, used = [], set()
    # circles: "RADIUS 5NM CENTRED ON <coord>" or "<coord> RADIUS 5NM"
    for m in CIRCLE.finditer(text):
        nm = float(m.group(1)) / (NM_KM if m.group(2) == "KM" else 1)
        after = [p for p in pts if 0 <= p["start"] - m.end() <= 40]
        before = [p for p in pts if 0 <= m.start() - p["end"] <= 6]
        centre = after[0] if after else (before[-1] if before else None)
        if centre is None:
            continue
        used.add(id(centre))
        shapes.append({"kind": "circle", "centre": [centre["lon"], centre["lat"]], "radius_nm": round(nm, 2),
                       "ring": circle_ring(centre["lat"], centre["lon"], nm), "derived": "text circle"})
    run: list[dict] = []
    runs: list[list[dict]] = []
    for i, p in enumerate(pts):
        if id(p) in used:
            continue
        if run:
            closed = len(run) >= 4 and (run[0]["lat"], run[0]["lon"]) == (run[-1]["lat"], run[-1]["lon"])
            if closed or _gap_breaks(text[run[-1]["end"]:p["start"]]):
                runs.append(run)
                run = []
        run.append(p)
    if run:
        runs.append(run)
    for r in runs:
        ring = [[p["lon"], p["lat"]] for p in r]
        distinct = {tuple(v) for v in ring}
        if len(distinct) >= 3:
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            shapes.append({"kind": "polygon", "ring": unwrap(ring), "vertices": len(distinct),
                           "derived": "text polygon", "forms": sorted({p["form"] for p in r})})
        elif len(distinct) == 2:
            shapes.append({"kind": "line", "line": [[p["lon"], p["lat"]] for p in r], "derived": "text line"})
        else:
            shapes.append({"kind": "point", "point": ring[0], "derived": "text point"})
    return shapes, rejected


def _items(body: str) -> dict:
    """Split the A)-G) items. A letter counts only in order (A before B ...), so 'E) ... (B) ...' stays text."""
    out, last, order = {}, None, "ABCDEFG"
    marks = []
    for m in ITEM.finditer(body):
        k = m.group(1)
        if last is None or order.index(k) > order.index(last):
            marks.append(m)
            last = k
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(1)] = body[m.end():end].strip()
    return out


def state_of_fir(fir: str | None) -> str | None:
    if not fir:
        return None
    for n in (2, 1):
        if fir[:n] in FIR_STATE:
            return FIR_STATE[fir[:n]]
    return None


def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a)) / NM_KM


def centroid(ring: list[list[float]]) -> tuple[float, float]:
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, (lon + 540) % 360 - 180


def parse(raw: str) -> dict:
    """One NOTAM's text -> fields, shapes and checks. Raises ParseError if there is no Q-line or header."""
    text = clean(raw)
    h = HEADER.search(text)
    q = QLINE.search(text)
    if not h and not q:
        raise ParseError("no NOTAM header and no Q-line")
    out: dict = {"text": text.strip()}
    if h:
        out.update({"series": h.group(1), "number": f"{h.group(1)}{h.group(2)}/{h.group(3)}",
                    "type": {"N": "new", "R": "replace", "C": "cancel"}[h.group(4)],
                    "refers_to": f"{h.group(5)}{h.group(6)}/{h.group(7)}" if h.group(5) else None})
    body = text[q.end():] if q else text[h.end():]
    if q:
        lat = (int(q.group(9)) + int(q.group(10)) / 60) * (-1 if q.group(11) == "S" else 1)
        lon = (int(q.group(12)) + int(q.group(13)) / 60) * (-1 if q.group(14) == "W" else 1)
        subj, cond = q.group(2), q.group(3)
        out["q"] = {
            "fir": q.group(1), "code": f"Q{subj}{cond}", "subject": subj, "condition": cond,
            "subject_text": SUBJECT.get(subj), "condition_text": CONDITION.get(cond),
            "traffic": q.group(4).replace(" ", ""), "purpose": q.group(5).replace(" ", ""),
            "scope": q.group(6).replace(" ", ""), "lower_fl": int(q.group(7)), "upper_fl": int(q.group(8)),
            "centre": [round(lon, 4), round(lat, 4)],
            "radius_nm": int(q.group(15)) if q.group(15) else None,
        }
    it = _items(body)
    out["locations"] = it.get("A", "").split() if it.get("A") else []
    start, _, _ = stamp(it.get("B", ""))
    end, est, perm = stamp(it.get("C", ""))
    out.update({"start": start, "end": end, "end_estimated": est, "permanent": perm,
                "schedule": re.sub(r"\s+", " ", it.get("D", "")).strip() or None,
                "e_text": it.get("E", "").strip(), "lower": (it.get("F") or "").strip() or None,
                "upper": (it.get("G") or "").strip() or None})
    shapes, rejected = shapes_from_text(out["e_text"] or body)
    qd = out.get("q")
    if not [s for s in shapes if s["kind"] in ("polygon", "circle")] and qd and qd.get("radius_nm"):
        c = qd["centre"]
        r = qd["radius_nm"] if qd["radius_nm"] < 999 else None
        if r:
            shapes.append({"kind": "circle", "centre": c, "radius_nm": r, "ring": circle_ring(c[1], c[0], r),
                           "derived": "Q-line circle (approximate: the notice's own area is not given as coordinates)"})
    checks = []
    if qd and qd.get("radius_nm") and qd["radius_nm"] < 999:
        for s in shapes:
            if s["kind"] == "polygon":
                la, lo = centroid(s["ring"])
                d = haversine_nm(la, lo, qd["centre"][1], qd["centre"][0])
                if d > qd["radius_nm"] * 1.5 + 30:
                    checks.append(f"polygon centre {d:.0f} NM from the Q-line centre (radius {qd['radius_nm']} NM)")
    if rejected:
        checks.append("unreadable coordinate(s): " + ", ".join(r["token"] for r in rejected))
    out["shapes"] = shapes
    out["rejected"] = rejected
    out["checks"] = checks
    fir = qd["fir"] if qd else (out["locations"][0] if out["locations"] else None)
    issuer = state_of_fir(out["locations"][0] if out["locations"] else fir)
    named = [cc for cc, rx in NAMED_STATE if rx.search(out["e_text"] or "")]
    out["issuing_state"] = issuer
    out["named_states"] = named
    out["relayed"] = bool(issuer and named and issuer not in named)
    out["launch_related"] = bool(LAUNCH_WORDS.search(out["e_text"] or "")) or (
        bool(qd) and qd["subject"] == "WM")
    return out


SPLIT = re.compile(r"(?=\b[A-Z]\d{4}/\d{2}\s*NOTAM[NRC]\b)")


def split_many(raw: str) -> list[str]:
    """Several NOTAMs pasted together -> one string each (split at each header)."""
    t = clean(raw)
    parts = [p.strip() for p in SPLIT.split(t) if p.strip()]
    return [p for p in parts if HEADER.search(p) or QLINE.search(p)]
