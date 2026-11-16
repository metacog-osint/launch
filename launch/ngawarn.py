"""NGA navigational warnings that name rocket launching, space debris or reentry: Orbit's rules, copied.

The constants and parse_windows, parse_coords and parse_body below are copied from Orbit (orbit/navwarn.py,
15 Nov 2026), not imported, with one constant renamed (Orbit's window-pair pattern is SPAN here): each program stands on its own. Only warnings whose text names
rocket launching, space debris, a space vehicle or spacecraft, or reentry are kept (HAZARD); missile firings and
everything else are left out. Fix a rule in Orbit first and copy it here again.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _year_for(month: int, issued: datetime) -> int:
    """A window's year: the warning's own year, or the next one for a January window issued in December."""
    return issued.year + 1 if month < issued.month - 6 else issued.year


def _when(day: int, hh: int, mm: int, month: int, issued: datetime) -> datetime:
    return datetime(_year_for(month, issued), month, day, hh, mm, tzinfo=timezone.utc)


HAZARD = re.compile(r"ROCKET LAUNCH\w*(?: SUSPENDED)?|SPACE DEBRIS|SPACE VEHICLE|SPACECRAFT|RE-?ENTRY")
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MON = "(" + "|".join(MONTHS) + ")"
COORD = re.compile(r"(\d{1,2})-(\d{2}(?:\.\d+)?)\s?([NS])[,\s]+(\d{1,3})-(\d{2}(?:\.\d+)?)\s?([EW])")
SPAN = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z TO (\d{2})(\d{2})(\d{2})Z\b")
DAILY = re.compile(r"\b(\d{2})(\d{2})Z TO (\d{2})(\d{2})Z (?:COMMENCING )?DAILY (\d{1,2})(?: " + MON + r")?"
                   r" (?:THRU|THR|TO) (\d{1,2}) " + MON)
DAILY_AND = re.compile(r"\b(\d{2})(\d{2})Z TO (\d{2})(\d{2})Z (?:COMMENCING )?DAILY ((?:\d{1,2}(?:, | AND ))+\d{1,2}) "
                       + MON)
CANCEL_THIS = re.compile(r"CANCEL THIS MSG (\d{2})(\d{2})(\d{2})Z " + MON + r"(?: (\d{2}))?")
CANCEL_OTHER = re.compile(r"CANCEL (?!THIS)((?:HYDROPAC|HYDROLANT|HYDROARC|NAVAREA [IVX]+) )?(\d{3,4})/(\d{2})")
AREA_LABEL = re.compile(r"(?m)^\s*([A-Z])\.\s+")








def parse_windows(text: str, issued: datetime) -> tuple[list[dict], str]:
    """Time windows in a warning's own words, as UTC [start, end] pairs, and how they were written:
    'single', 'alternates' (the first window, then the issuer's alternates), 'daily', or '' if none parsed."""
    t = re.sub(r"\s+", " ", text)
    out: list[dict] = []
    mode = ""
    for m in DAILY.finditer(t):
        h0, m0, h1, m1, d0, mon0, d1, mon1 = m.groups()
        end_month = MONTHS.index(mon1) + 1
        start_month = MONTHS.index(mon0) + 1 if mon0 else end_month
        day = _when(int(d0), 0, 0, start_month, issued)
        last = _when(int(d1), 0, 0, end_month, issued)
        while day <= last and len(out) < 62:
            s = day.replace(hour=int(h0), minute=int(m0))
            e = day.replace(hour=int(h1), minute=int(m1))
            if e <= s:
                e += timedelta(days=1)
            out.append({"start": _iso(s), "end": _iso(e)})
            day += timedelta(days=1)
        mode = "daily"
    for m in DAILY_AND.finditer(t):
        h0, m0, h1, m1, days, mon = m.groups()
        for d in re.findall(r"\d{1,2}", days):
            s = _when(int(d), int(h0), int(m0), MONTHS.index(mon) + 1, issued)
            e = s.replace(hour=int(h1), minute=int(m1))
            if e <= s:
                e += timedelta(days=1)
            out.append({"start": _iso(s), "end": _iso(e)})
        mode = "daily"
    pairs = list(SPAN.finditer(t))
    for m in pairs:
        mon = re.compile(r"\b" + MON + r"\b").search(t, m.end())
        if not mon:
            continue
        month = MONTHS.index(mon.group(1)) + 1
        d0, h0, n0, d1, h1, n1 = (int(g) for g in m.groups())
        s = _when(d0, h0, n0, month, issued)
        e = _when(d1, h1, n1, month, issued)
        if e <= s:  # the window ends in the next month: the month named is the end's
            s = _when(d0, h0, n0, month - 1 or 12, issued)
        out.append({"start": _iso(s), "end": _iso(e)})
    if pairs:
        mode = "alternates" if "ALTERNATE" in t else ("single" if len(pairs) == 1 and mode != "daily" else mode or "list")
    out.sort(key=lambda w: w["start"])
    seen, uniq = set(), []
    for w in out:
        k = (w["start"], w["end"])
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    return uniq, mode


def parse_coords(text: str) -> list[list[float]]:
    """Every vertex as [lon, lat], longitudes unwrapped so an area across 180 degrees stays one shape."""
    pts = []
    for m in COORD.finditer(text):
        la = int(m.group(1)) + float(m.group(2)) / 60
        lo = int(m.group(4)) + float(m.group(5)) / 60
        la = -la if m.group(3) == "S" else la
        lo = -lo if m.group(6) == "W" else lo
        if pts:
            while lo - pts[-1][0] > 180:
                lo -= 360
            while pts[-1][0] - lo > 180:
                lo += 360
        pts.append([round(lo, 4), round(la, 4)])
    return pts


def parse_body(text: str, issued: datetime) -> dict | None:
    """One warning's text -> hazard, regions, areas (each with its own windows when the text gives them), the
    message-level windows, its cancel time and the warnings it cancels. None if it is not about a launch."""
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    full = "\n".join(lines)
    hz = HAZARD.search(full)
    if not hz:
        return None
    regions = []
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("1.") or HAZARD.search(ln) or re.match(r"\d{4}Z|\d{6}Z", ln):
            break
        regions.append(ln.rstrip("."))
    expires = None
    cm = CANCEL_THIS.search(full)
    if cm:
        d, h, n, mon, yy = cm.groups()
        exp_issued = issued.replace(year=2000 + int(yy)) if yy else issued
        expires = _iso(_when(int(d), int(h), int(n), MONTHS.index(mon) + 1, exp_issued))
    cancels = [((m.group(1) or "").strip() + " " + m.group(2) + "/" + m.group(3)).strip()
               for m in CANCEL_OTHER.finditer(full)]
    # Body of the hazard paragraph: from the hazard words to the next numbered paragraph or the cancel line.
    start = hz.start()
    stop = re.compile(r"(?m)^\d\.\s|CANCEL ").search(full, hz.end())
    para = full[start: stop.start() if stop else len(full)]
    labels = list(AREA_LABEL.finditer(para))
    blocks = []
    if labels:
        head = para[: labels[0].start()]
        for i, lb in enumerate(labels):
            blocks.append((lb.group(1), para[lb.end(): labels[i + 1].start() if i + 1 < len(labels) else len(para)]))
    else:
        head, blocks = para, [("", para)]
    windows, mode = parse_windows(head, issued)
    areas = []
    for label, btxt in blocks:
        coords = parse_coords(btxt)
        own, own_mode = parse_windows(btxt, issued) if labels else ([], "")
        if not coords:
            continue
        area = {"label": label, "coords": coords}
        if own:
            area["windows"], area["window_mode"] = own, own_mode
        areas.append(area)
    if not windows:  # every area carries its own windows (NAVAREA XII style): the message's are their union
        by_start: dict[str, str] = {}  # areas opening together are one window; it ends when the last area closes
        for a in areas:
            for w in a.get("windows", []):
                by_start[w["start"]] = max(by_start.get(w["start"], ""), w["end"])
        windows = [{"start": k, "end": v} for k, v in sorted(by_start.items())]
        modes = {a.get("window_mode") for a in areas if a.get("window_mode")}
        mode = modes.pop() if len(modes) == 1 else ("alternates" if "ALTERNATE" in para else "list")
    window_text = re.split(r"\bIN AREAS? BOUND|\bAREAS? BOUNDED", re.sub(r"\s+", " ", head))[0].strip(" ,:")
    window_text = window_text[len(hz.group(0)):].strip(" ,.:") if window_text.startswith(hz.group(0)) else window_text
    return {"hazard": hz.group(0).lower().replace("re-entry", "reentry"),
            "regions": regions, "areas": areas, "windows": windows, "window_mode": mode,
            "window_text": window_text[:300], "expires": expires, "cancels": cancels}
