"""Internet Archive copies of two official notice sources, for the years Launch's live lanes never saw.

  - FAA TFRs (tfr.faa.gov): every distinct capture of the list page (tfr2/list.html) is read for rows of type SPACE
    OPERATIONS; for each, one capture of its detail page (save_pages/detail_<n>.html) is fetched and read for the
    NOTAM number, issue time, location, window and the area's vertices or circle. Captures 2006 onward.
  - NGA broadcast warnings (msi.nga.mil/api/publications/broadcast-warn...): every distinct capture of the API's
    JSON; warnings kept on Orbit's rule (ngawarn.HAZARD: rocket launching, space debris, space vehicle or
    spacecraft, reentry). Captures 2021 onward, few.
Nothing else on those hosts is read (forum.nasaspaceflight.com's copies are never touched: its robots.txt disallows
this reader, and reading it through the archive would sidestep that).

`fetch` lists captures with the CDX API and fetches each with the id_ form (the original bytes), at most one request
a second (PAUSE), with UA, into git-ignored history/wayback_source/ with index.json, so a rerun fetches nothing
twice and an interrupted run resumes. `build` writes history/wayback.json (committed): fields read from the pages,
each with its capture URL as its source. Contact names, telephone numbers and email addresses on the pages are not
kept.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ngawarn, notam

UA = "tic-launch (+https://launch.theintelligence.company)"
CDX = "https://web.archive.org/cdx/search/cdx"
WEB = "https://web.archive.org/web/{ts}id_/{url}"
PAUSE = 1.05       # seconds between any two requests to the archive
SAVE_EVERY = 10    # captures between index writes
RETRIES = 5
TFR_LIST = "tfr.faa.gov/tfr2/list.html"
TFR_DETAIL_PREFIX = "tfr.faa.gov/save_pages/"
NGA_PREFIX = "msi.nga.mil/api/publications/broadcast-warn"
NEVER = ("nasaspaceflight.com",)


class Archive:
    """The archive, paced and cached. index.json: {"cdx": {query: [rows]}, "got": {key: {file, ts, url, status}}}."""

    def __init__(self, dest: Path, opener=None, pause: float = PAUSE, log=print):
        self.dest, self.pause, self.log = dest, pause, log
        self.dest.mkdir(parents=True, exist_ok=True)
        self.ipath = dest / "index.json"
        self.index = json.loads(self.ipath.read_text(encoding="utf-8")) if self.ipath.exists() else {"cdx": {}, "got": {}}
        self.opener = opener or self._open
        self.last = 0.0
        self.requests = 0
        self.failed = 0
        self.served = None  # the capture the archive served (it redirects to the nearest one it holds)
        self.unsaved = 0

    def save(self, force: bool = True):
        """Write the index; with force False, only every SAVE_EVERY captures (a lost entry is fetched again)."""
        self.unsaved += 1
        if not force and self.unsaved < SAVE_EVERY:
            return
        self.unsaved = 0
        tmp = self.ipath.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.index, separators=(",", ":")), encoding="utf-8")
        for i in range(10):  # Windows refuses the rename while another process reads the index
            try:
                tmp.replace(self.ipath)
                return
            except PermissionError:
                time.sleep(1 + i)
        tmp.replace(self.ipath)

    def _open(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as r:
            self.served = r.geturl()
            body = r.read()
            # id_ captures can carry the original Content-Encoding header on a body that is not gzipped
            if body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            return body

    def get(self, url: str) -> bytes:
        if any(h in url for h in NEVER):
            raise ValueError("not read: " + url)
        err = None
        for i in range(RETRIES):
            wait = self.pause - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            try:
                body = self.opener(url)
                if b"Temporarily Offline" in body[:600] and url.startswith(CDX):
                    raise IOError("archive temporarily offline")
                return body
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise
                err = e
            except Exception as e:  # noqa: BLE001  (network trouble: wait longer and retry)
                err = e
            time.sleep(min(60, 5 * 2 ** i))
        raise IOError(f"gave up after {RETRIES} tries: {url}: {err}")

    def cdx(self, params: dict) -> list[list[str]]:
        """CDX rows (space-separated fields), cached by query."""
        q = urllib.parse.urlencode(params)
        if q in self.index["cdx"]:
            return self.index["cdx"][q]
        body = self.get(CDX + "?" + q).decode("utf-8", "replace")
        rows = [ln.split(" ") for ln in body.splitlines() if ln.strip()]
        self.index["cdx"][q] = rows
        self.save()
        return rows

    def capture(self, key: str, ts: str, url: str) -> Path | None:
        """One capture's original bytes, once."""
        got = self.index["got"].get(key)
        if got and got.get("status") == "ok":
            return self.dest / got["file"]
        if got and got.get("status") == "missing":
            return None
        name = hashlib.sha1(key.encode()).hexdigest()[:16]
        f = f"{key.split(':')[0]}/{name}"
        self.served = None
        try:
            body = self.get(WEB.format(ts=ts, url=url))
        except urllib.error.HTTPError as e:
            self.index["got"][key] = {"status": "missing", "ts": ts, "url": url, "code": e.code}
            self.save(force=False)
            return None
        except IOError as e:  # gave up after RETRIES: skipped this run, tried again on the next
            self.log(f"  skipped {key}: {e}"[:200])
            self.failed += 1
            return None
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except (OSError, EOFError):
                pass
        (self.dest / f).parent.mkdir(parents=True, exist_ok=True)
        (self.dest / f).write_bytes(body)
        m = re.search(r"/web/(\d{14})", self.served or "")
        self.index["got"][key] = {"status": "ok", "file": f, "ts": m.group(1) if m else ts, "url": url, "asked": ts}
        self.save(force=False)
        return self.dest / f


# ---- FAA TFR pages ---------------------------------------------------------------------------------------------

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
DETAIL = re.compile(r"save_pages/(detail_[0-9A-Za-z_]+\.html)", re.I)


def _text(fragment: str) -> str:
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def list_rows(page: str) -> list[dict]:
    """The list page's rows: date, NOTAM, facility, state, type, description and the detail page's file name."""
    out = []
    for r in ROW.finditer(page):
        cells = CELL.findall(r.group(1))
        d = DETAIL.search(r.group(1))
        if len(cells) < 6 or not d:
            continue
        t = [_text(c) for c in cells]
        out.append({"date": t[0], "notam": t[1], "facility": t[2], "state": t[3], "type": t[4],
                    "description": t[5], "detail": d.group(1)})
    return out


def is_space_ops(row: dict) -> bool:
    return "SPACE OPERATIONS" in (row.get("type") or "").upper()


ZONES = {"UTC": 0, "GMT": 0, "Z": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8,
         "PDT": -7, "AKST": -9, "AKDT": -8, "HST": -10, "AST": -4}
WHEN = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\s+at\s+(\d{2})(\d{2})\s*([A-Z]{1,4})?")
FIELD = r"{}\s*:\s*(.*?)\s*(?=Location\s*:|Beginning Date|Ending Date|Reason for NOTAM|Type\s*:|Replaced NOTAM|Jump To|Issue Date|Download|Affected Area|Airspace Definition|Operating Restrictions|Other Information|$)"
DMS = re.compile(r"(\d{1,3})\s*[º°o]\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*(?:\"|'')\s*([NSEW])")
DAILY_FORM = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\s+UTC\s+(\d{4})-(\d{4})\s+Daily", re.I)
RADIUS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:nautical mile|NM|nmi)", re.I)


def _when(s: str | None) -> tuple[str | None, str | None]:
    """'June 01, 2021 at 0001 UTC' -> (UTC ISO, zone as written); a zone not in ZONES gives (None, zone)."""
    m = WHEN.search(s or "")
    if not m:
        return None, None
    mon, d, y, hh, mm, zone = m.groups()
    try:
        local = datetime.strptime(f"{mon} {d} {y} {hh}{mm}", "%B %d %Y %H%M")
    except ValueError:
        return None, zone
    zone = zone or "UTC"
    if zone not in ZONES:
        return None, zone
    return (local - timedelta(hours=ZONES[zone])).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), zone


def _field(text: str, label: str) -> str | None:
    m = re.search(FIELD.format(label), text)
    return m.group(1).strip() if m and m.group(1).strip() else None


def _points(text: str) -> list[list[float]]:
    vals = []
    for m in DMS.finditer(text):
        v = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600
        vals.append((-v if m.group(4) in "SW" else v, m.group(4)))
    pts, i = [], 0
    while i + 1 < len(vals):
        (a, ha), (b, hb) = vals[i], vals[i + 1]
        if ha in "NS" and hb in "EW":
            pts.append([round(b, 5), round(a, 5)])
            i += 2
        else:
            i += 1
    return pts


def parse_detail(page: str) -> dict:
    """A detail page's fields and areas. Times in UTC (the page's zone is kept when it is not UTC)."""
    text = _text(page)
    out = {"number": None, "issued": None, "location": None, "start": None, "end": None, "type": None,
           "reason": None, "zone": None, "areas": []}
    m = re.search(r"NOTAM Number\s*:\s*(?:FDC\s*)?(\d/\d{4})", text)
    out["number"] = m.group(1) if m else None
    out["issued"] = _when(_field(text, "Issue Date"))[0]
    out["location"] = _field(text, "Location")
    begin, ending = _field(text, "Beginning Date and Time"), _field(text, "Ending Date and Time")
    out["start"], z1 = _when(begin)
    out["end"], z2 = _when(ending)
    out["zone"] = z1 or z2
    dm = DAILY_FORM.search(begin or "")
    if not out["start"] and dm:  # "January 22, 2025 UTC 0445-1415 Daily" to "February 08, 2025 UTC"
        em = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})", ending or "")
        out["start"] = _when(f"{dm.group(1)} {dm.group(2)}, {dm.group(3)} at {dm.group(4)} UTC")[0]
        if em:
            out["end"] = _when(f"{em.group(1)} {em.group(2)}, {em.group(3)} at {dm.group(5)} UTC")[0]
        out["zone"], out["schedule"] = "UTC", f"{dm.group(4)}-{dm.group(5)} daily"
    out["type"] = _field(text, "Type")
    out["reason"] = _field(text, "Reason for NOTAM")
    for block in re.split(r"Airspace Definition\s*:", text)[1:]:
        block = re.split(r"Operating Restrictions and Requirements|Other Information\s*:", block)[0]
        pts = _points(block)
        r = RADIUS.search(block)
        if r and pts and re.search(r"radius", block, re.I):
            ring = notam.circle_ring(pts[0][1], pts[0][0], float(r.group(1)))
            out["areas"].append({"kind": "circle", "ring": ring, "radius_nm": float(r.group(1))})
        elif len(pts) >= 3:
            ring = pts + [pts[0]] if pts[0] != pts[-1] else pts
            out["areas"].append({"kind": "polygon", "ring": ring})
    return out


# ---- fetch and build -------------------------------------------------------------------------------------------

def _detail_key(key: str) -> str:
    return "tfr:" + key


def fetch(dest: Path, opener=None, log=print, pause: float = PAUSE, since: str | None = None) -> dict:
    """List and fetch what build needs. Safe to stop and rerun."""
    a = Archive(dest, opener=opener, pause=pause, log=log)
    # 1. every distinct capture of the TFR list page; its space-operations rows are kept in the index
    lists = a.cdx({"url": TFR_LIST, "filter": "statuscode:200", "collapse": "digest", "fl": "timestamp,original"})
    rows_by = a.index.setdefault("rows", {})
    space: dict[str, dict] = {}
    for i, (ts, url) in enumerate(lists):
        if ts not in rows_by:
            p = a.capture(f"list:{ts}", ts, url)
            if not p:
                continue
            rows_by[ts] = [r for r in list_rows(p.read_text(encoding="utf-8", errors="replace")) if is_space_ops(r)]
            a.save(force=False)
        for row in rows_by[ts]:
            space.setdefault(tfr_key(row), {**row, "list_ts": ts})
        if i % 100 == 0:
            log(f"  list captures {i + 1}/{len(lists)}; space operations TFRs so far {len(space)}")
    a.index["space_ops"] = space
    a.save()
    # 2. every distinct capture of NGA's broadcast-warn API (few, so first)
    nga = a.cdx({"url": NGA_PREFIX, "matchType": "prefix", "filter": "statuscode:200", "collapse": "digest",
                 "fl": "timestamp,original"})
    n_nga = sum(1 for ts, url in nga if a.capture(f"nga:{ts}:{hashlib.sha1(url.encode()).hexdigest()[:8]}", ts, url))
    # 3. each TFR's detail page, the capture nearest the list capture that named it (the FAA reuses a page name
    #    every year, so the first capture of a name can be another year's TFR), newest first, from `since` (a list
    #    date, YYYY-MM-DD) when given; older TFRs stay as their list rows (number, date, place) until fetched
    want = sorted(((list_date(row) or "", k) for k, row in space.items()), reverse=True)
    want = [(dt, k) for dt, k in want if not since or dt >= since]
    got = 0
    for j, (_, k) in enumerate(want):
        row = space[k]
        if a.capture(_detail_key(k), row["list_ts"], "http://" + TFR_DETAIL_PREFIX + row["detail"]):
            got += 1
        if j % 50 == 0:
            log(f"  detail pages {j + 1}/{len(want)}")
    a.save()
    missing = sum(1 for _, k in want if (a.index["got"].get(_detail_key(k)) or {}).get("status") == "missing")
    return {"list_captures": len(lists), "space_ops_tfrs": len(space), "detail_wanted": len(want),
            "detail_pages": got, "detail_not_archived": missing, "nga_captures": len(nga), "nga_fetched": n_nga,
            "requests": a.requests, "skipped": a.failed}


def tfr_key(row: dict) -> str:
    """A TFR's key: its detail page's name and the year of the list row (names are reused every year)."""
    return f"{row['detail'].lower()}@{(list_date(row) or '????')[:4]}"


def list_date(row: dict) -> str | None:
    """The list row's date (MM/DD/YYYY) as YYYY-MM-DD."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", row.get("date") or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def nga_warnings(doc) -> list[dict]:
    """Launch-related warnings in one capture of the API (its list, or a single warning)."""
    items = doc.get("broadcast-warn") if isinstance(doc, dict) else doc
    if isinstance(doc, dict) and items is None and doc.get("text"):
        items = [doc]
    out = []
    for w in items or []:
        if not isinstance(w, dict):
            continue
        area = ngawarn_area(w.get("navArea"))
        m = API_DATE.match(re.sub(r"\s+", " ", str(w.get("issueDate") or "")).strip().upper())
        if not area or not m:
            continue
        dd, hh, nn, mon, yyyy = m.groups()
        issued = datetime(int(yyyy), ngawarn.MONTHS.index(mon) + 1, int(dd), int(hh), int(nn), tzinfo=timezone.utc)
        text = str(w.get("text") or "").replace("\r", "").strip()
        try:
            parsed = ngawarn.parse_body(text, issued)
        except ValueError:  # Orbit's parser raises on a time written 2400Z: not read, counted (fix it in Orbit first)
            NGA_UNREAD.append(f"{area} {w.get('msgNumber')}/{w.get('msgYear')}")
            continue
        if not parsed:
            continue
        try:
            wid = f"{area} {int(w.get('msgNumber'))}/{int(w.get('msgYear')) % 100:02d}"
        except (TypeError, ValueError):
            continue
        out.append({"id": wid, "coordinator": area, "issued": ngawarn._iso(issued), "text": text[:2500], **parsed})
    return out


API_DATE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z\s+" + ngawarn.MON + r"\s+(\d{4})$")
NGA_UNREAD: list[str] = []   # warnings the copied parser could not read (see nga_warnings)
NGA_AREAS = {"P": "HYDROPAC", "A": "HYDROLANT", "C": "HYDROARC", "4": "NAVAREA IV", "12": "NAVAREA XII"}


def ngawarn_area(code) -> str | None:
    return NGA_AREAS.get(str(code or "").strip().upper())


PAGE_DAYS = 120   # a detail page issued this far from the list date that named it is another year's TFR


def _dt_iso(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None) if s else None
    except ValueError:
        return None


def build(src: Path) -> dict:
    """history/wayback.json from the cached captures (index.json)."""
    idx = json.loads((src / "index.json").read_text(encoding="utf-8"))
    tfrs, by_num, stale = [], {}, 0
    for name, row in sorted((idx.get("space_ops") or {}).items()):
        g = idx["got"].get(_detail_key(name))
        d = None
        if g and g.get("status") == "ok":
            d = parse_detail((src / g["file"]).read_text(encoding="utf-8", errors="replace"))
            ld, when = _dt_iso(list_date(row)), _dt_iso(d.get("issued") or d.get("start"))
            if "SPACE" not in (d.get("type") or "").upper() or not (ld and when) or abs((when - ld).days) > PAGE_DAYS:
                stale += 1  # the archive's nearest copy of the page is another TFR (or unreadable)
                d = None
        if d is None:
            # no detail page read (not archived, refused above, or older than the fetch's `since`): the list row only
            lg = idx["got"].get(f"list:{row.get('list_ts')}") or {}
            rec = {"id": "faa-tfr:" + (row.get("notam") or name), "number": row.get("notam"), "issued": None,
                   "start": None, "end": None, "list_date": list_date(row), "zone": None,
                   "location": row.get("description"), "facility": row.get("facility"), "state": row.get("state"),
                   "reason": None, "areas": [], "detail": False,
                   "source": WEB.format(ts=lg.get("ts", row.get("list_ts")), url=lg.get("url", "http://" + TFR_LIST)).replace("id_/", "/")}
            key = (rec["number"], (rec["list_date"] or "")[:4])
            if key not in by_num:
                by_num[key] = rec
                tfrs.append(rec)
            continue
        rec = {"id": "faa-tfr:" + (d["number"] or name), "number": d["number"] or row.get("notam"),
               "issued": d["issued"], "start": d["start"], "end": d["end"], "zone": d["zone"],
               "location": d["location"] or row.get("description"), "facility": row.get("facility"),
               "state": row.get("state"), "reason": d["reason"], "areas": d["areas"], "list_date": list_date(row),
               "detail": True, "source": WEB.format(ts=g["ts"], url=g["url"]).replace("id_/", "/")}
        key = (rec["number"], (rec["list_date"] or rec["start"] or "")[:4])
        if key in by_num:  # the same TFR under two page names
            continue
        by_num[key] = rec
        tfrs.append(rec)
    nga, seen = [], set()
    for key, g in sorted(idx["got"].items()):
        if not key.startswith("nga:") or g.get("status") != "ok":
            continue
        try:
            doc = json.loads((src / g["file"]).read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            continue
        for w in nga_warnings(doc):
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            nga.append({**w, "source": WEB.format(ts=g["ts"], url=g["url"]).replace("id_/", "/")})
    tfrs.sort(key=lambda r: (r["start"] or r["list_date"] or "", r["number"] or ""))
    nga.sort(key=lambda w: (w["issued"], w["id"]))
    return {"source": "web.archive.org (Internet Archive) copies of tfr.faa.gov and msi.nga.mil",
            "rule": "FAA TFRs of type SPACE OPERATIONS; NGA warnings naming rocket launching, space debris, a space "
                    "vehicle or spacecraft, or reentry (Orbit's rule, ngawarn.HAZARD)",
            "tfrs": tfrs, "tfr_pages_refused": stale, "nga": nga, "nga_unread": sorted(set(NGA_UNREAD))}


def summary(doc: dict) -> dict:
    def years(xs, k):
        out: dict[str, int] = {}
        for x in xs:
            y = (x.get(k) or "????")[:4]
            out[y] = out.get(y, 0) + 1
        return dict(sorted(out.items()))
    return {"tfrs": len(doc["tfrs"]), "tfrs_detail_read": sum(1 for t in doc["tfrs"] if t.get("detail")),
            "tfrs_with_area": sum(1 for t in doc["tfrs"] if t["areas"]),
            "tfrs_by_year": years(doc["tfrs"], "list_date"),
            "tfrs_detail_by_year": years([t for t in doc["tfrs"] if t.get("detail")], "list_date"),
            "tfr_pages_refused": doc.get("tfr_pages_refused", 0), "nga": len(doc["nga"]),
            "nga_by_year": years(doc["nga"], "issued"), "nga_unread": len(doc.get("nga_unread") or [])}
