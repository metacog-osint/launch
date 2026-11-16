"""NotamForChina: an open record of Chinese launches and the NOTAMs that closed their drop zones.

Source: github.com/mikezang/NotamForChina (Apache-2.0), pinned at SHA. Two parts are read:
  - data/ChinaRocketLaunch.xlsx, sheet 发射时间预测 ("launch time prediction"): one block per launch, with its
    vehicle and site, then one row per notice: FIR (or MSA for China's maritime notices), the notice's number
    (from late 2023), its window in UTC, and the actual launch time in Beijing time (UTC+8). 2022 onward.
  - notams/maps/<site>/<vehicle>/<YYYY年MM月DD日HH时MM分><site><vehicle>.kml|kmz: one file per launch, file name in
    Beijing time; polygons named "<FIR>/<number>" (the closure areas as charted from the notices) and lines (the
    trajectory as charted, named by inclination). 2012-2024.
Nothing in either is free text: names, numbers, times and shapes only.

`fetch` copies those files at the pinned commit into a git-ignored folder; `build` turns them into
history/nfc.json (committed); `join` ties each launch to GCAT's record within MATCH_HOURS.
"""
from __future__ import annotations

import io
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "mikezang/NotamForChina"
SHA = "2d06a628ab52e503ff94c96b7803e95dae55be79"  # pushed 19 Oct 2026
LICENCE = "Apache-2.0"
ATTRIBUTION = ("NotamForChina by mikezang (github.com/mikezang/NotamForChina), Apache License 2.0; "
               "read by Launch, which converts its sheet and drop-zone maps to JSON and joins them to GCAT.")
SHEET = "发射时间预测"
WORKBOOK = "data/ChinaRocketLaunch.xlsx"
MAPS = "notams/maps/"
BEIJING = timezone(timedelta(hours=8))
MATCH_HOURS = 1.0
UA = "Mozilla/5.0 (compatible; research-collector/1.0)"

SITES = {"酒泉": "Jiuquan", "西昌": "Xichang", "太原": "Taiyuan", "文昌": "Wenchang", "海南": "Hainan commercial",
         "海上": "sea", "黄海": "sea", "东海": "sea", "日照": "sea", "海阳": "sea", "南海": "sea"}
# GCAT site codes for each (launch.json `site_code`); "sea" matches any Chinese sea-launch code.
GCAT_SITES = {"Jiuquan": {"JQ"}, "Xichang": {"XSC"}, "Taiyuan": {"TYSC"}, "Wenchang": {"WEN", "HCSLS"},
              "Hainan commercial": {"HCSLS", "WEN"}, "sea": {"HHAI", "YJ", "ECS", "SCS", "YS", "BOH"}}
NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
SUFFIX = {"甲": "A", "乙": "B", "丙": "C", "丁": "D", "戊": "E", "改": "", "己": "F", "F": "F", "E": "E", "Ｅ": "E", "": ""}
FAMILY = [("长征", "LM-"), ("快舟", "KZ-"), ("谷神星", "Ceres-"), ("捷龙", "Jielong-"), ("朱雀", "ZQ-"),
          ("力箭", "Kinetica-"), ("双曲线", "Hyperbola-"), ("天龙", "Tianlong-"), ("智神星", "Pallas-"),
          ("引力", "Gravity-"), ("开拓者", "Kaituozhe-"), ("风暴", "FB-"), ("星云", "Nebula-"), ("天行", "Tianxing-")]
# "ZJSA/A0535/24", "MSA/GD32/24", "ZPKM" (older maps: FIR only), "ZGZU/ZSHA" or "ZGZU/ZSHA/A1234/24"
NOTICE = re.compile(r"^\s*((?:[A-Z]{4}|MSA)(?:\s*/\s*(?:[A-Z]{4}|MSA))*)(?:\s*/\s*([A-Z]{1,2}\d{1,4}/\d{2}))?\s*$")
FILE_TIME = re.compile(r"(\d{4})年(\d{2})月(\d{2})日(\d{2}|\?\?)[时時](\d{2}|\?\?)分")


def vehicle(zh: str | None) -> str | None:
    """长征二号丙 -> LM-2C, 长征二号己 or 长征二号F -> LM-2F, 朱雀二号Ｅ -> ZQ-2E, 快舟一号甲 -> KZ-1A, 谷神星一号海 -> Ceres-1S; None when the name is
    not one of these."""
    if not zh:
        return None
    first = zh.split("/")[0].strip()
    for fam, pre in FAMILY:
        if first.startswith(fam):
            m = re.match(re.escape(fam) + r"([一二三四五六七八九十]+)号?([甲乙丙丁戊己改FEＥ]?)(海)?", first)
            if not m:
                return None
            n = m.group(1)
            num = (NUM.get(n[0], 1) * 10 + (NUM.get(n[1], 0) if len(n) > 1 else 0)) if "十" in n and n != "十" \
                else NUM.get(n, 10 if n == "十" else 0)
            if n.startswith("十"):
                num = 10 + (NUM.get(n[1], 0) if len(n) > 1 else 0)
            return f"{pre}{num}{SUFFIX[m.group(2)]}{'S' if m.group(3) else ''}"
    return None


def site(zh: str | None) -> str | None:
    for k, v in SITES.items():
        if zh and k in zh:
            return v
    return None


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def _serial(v: str | None, tz=timezone.utc) -> datetime | None:
    """An Excel date serial (days since 1899-12-30) as an aware datetime, rounded to the minute."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f < 30000:
        return None
    d = datetime(1899, 12, 30, tzinfo=tz) + timedelta(days=f)
    return (d + timedelta(seconds=30)).replace(second=0, microsecond=0)


# ---- the workbook --------------------------------------------------------------------------------------------

_M = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _sheet_rows(xlsx: bytes, name: str) -> list[dict[str, str]]:
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    shared = ["".join(t.text or "" for t in si.iter("{%s}t" % _M["m"]))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _M)]
    target = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", _M):
        if sh.get("name") != name:
            continue
        path = "xl/" + target[sh.get(_RID)].lstrip("/").replace("xl/", "", 1)
        out = []
        for r in ET.fromstring(z.read(path)).find("m:sheetData", _M):
            row = {}
            for c in r:
                v = c.find("m:v", _M)
                t = v.text if v is not None else ""
                if c.get("t") == "s" and t:
                    t = shared[int(t)]
                row[re.sub(r"\d", "", c.get("r"))] = (t or "").strip()
            out.append(row)
        return out
    raise KeyError(f"sheet {name!r} not in the workbook")


def parse_sheet(xlsx: bytes) -> list[dict]:
    """One record per launch block: vehicle, site, launch time (UTC) and its notices with their windows."""
    out, cur = [], None
    for row in _sheet_rows(xlsx, SHEET)[2:]:
        if not any(row.values()):
            cur = None
            continue
        if row.get("A"):
            launched = _serial(row.get("M"), BEIJING)
            cur = {"vehicle_zh": row["A"], "vehicle": vehicle(row["A"]), "site_zh": row.get("B") or None,
                   "site": site(row.get("B")), "time": _iso(launched), "notices": []}
            out.append(cur)
        if cur is None:
            continue
        for fir in (row.get("C") or "").split("/"):
            if fir.strip():
                cur["notices"].append({"fir": fir.strip(), "number": row.get("D") or None,
                                       "start": _iso(_serial(row.get("E"))), "end": _iso(_serial(row.get("F")))})
    return out


# ---- the drop-zone maps --------------------------------------------------------------------------------------

_K = "{http://www.opengis.net/kml/2.2}"


def _coords(text: str) -> list[list[float]]:
    pts = []
    for tok in (text or "").split():
        p = tok.split(",")
        if len(p) >= 2:
            pts.append([round(float(p[0]), 5), round(float(p[1]), 5)])
    return pts


def parse_map(path: str, raw: bytes) -> dict:
    """One launch from one map file: time from the file name (Beijing time), site and vehicle from the folders."""
    if path.lower().endswith(".kmz"):
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(next(n for n in z.namelist() if n.lower().endswith(".kml")))
    parts = path[len(MAPS):].split("/")
    site_zh = re.sub(r"^\d+\.", "", parts[0]) if len(parts) > 2 else None
    veh_zh = re.sub(r"^\d+\.", "", parts[1]) if len(parts) > 2 else None
    m = FILE_TIME.search(parts[-1])
    when, basis = None, None
    if m:
        y, mo, d, hh, mm = m.groups()
        if "?" in hh + mm:
            when, basis = datetime(int(y), int(mo), int(d), tzinfo=BEIJING), "date"
        else:
            when, basis = datetime(int(y), int(mo), int(d), int(hh), int(mm), tzinfo=BEIJING), "time"
    areas, paths, other = [], [], 0
    root = ET.fromstring(re.sub("[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw.decode("utf-8", "replace")))
    for pm in root.iter(_K + "Placemark"):
        name = (pm.findtext(_K + "name") or "").strip()
        poly = pm.find(f".//{_K}Polygon/{_K}outerBoundaryIs//{_K}coordinates")
        line = pm.find(f".//{_K}LineString/{_K}coordinates")
        n = NOTICE.match(name)
        if poly is not None:
            # every charted area is kept; FIR and number when the name carries them, else the name ("1st Stage")
            areas.append({"fir": re.sub(r"\s+", "", n.group(1)) if n else None, "number": n.group(2) if n else None,
                          "label": None if n else (name or None), "ring": _coords(poly.text)})
        elif line is not None:
            paths.append(_coords(line.text))
        else:
            other += 1  # a polygon without a notice's name, or a point: not imported
    return {"file": path, "vehicle_zh": veh_zh, "vehicle": vehicle(veh_zh), "site_zh": site_zh,
            "site": site(site_zh), "time": _iso(when) if basis == "time" else None,
            "date": when.astimezone(timezone.utc).date().isoformat() if when and basis == "time"
            else (when.date().isoformat() if when else None),
            "areas": areas, "paths": paths, "skipped": other}


# ---- fetch, build, join ---------------------------------------------------------------------------------------

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def fetch(dest: Path, pause: float = 0.2) -> dict:
    """Copy the workbook and every drop-zone map at SHA into dest (git-ignored). Skips files already there."""
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{SHA}?recursive=1"))
    paths = [WORKBOOK] + sorted(t["path"] for t in tree["tree"] if t["type"] == "blob" and t["path"].startswith(MAPS)
                                and t["path"].lower().endswith((".kml", ".kmz")))
    got = 0
    for p in paths:
        out = dest / p
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_get(f"https://raw.githubusercontent.com/{REPO}/{SHA}/{urllib.parse.quote(p)}"))
        got += 1
        time.sleep(pause)
    return {"files": len(paths), "fetched": got}


def _hours(a: str | None, b: str | None) -> float | None:
    if not (a and b):
        return None
    f = "%Y-%m-%dT%H:%M:%SZ"
    return abs((datetime.strptime(a, f) - datetime.strptime(b, f)).total_seconds()) / 3600


def build(src: Path) -> dict:
    """history/nfc.json: one record per launch, maps and sheet merged (same site, within MATCH_HOURS)."""
    maps = [parse_map(str(p.relative_to(src)).replace("\\", "/"), p.read_bytes())
            for p in sorted((src / MAPS).rglob("*")) if p.suffix.lower() in (".kml", ".kmz")]
    sheet = parse_sheet((src / WORKBOOK).read_bytes())
    launches = []
    for m in maps:
        launches.append({**{k: m[k] for k in ("vehicle", "vehicle_zh", "site", "site_zh", "time", "date")},
                         "notices": [{"fir": a["fir"], "number": a["number"], "label": a["label"], "start": None,
                                      "end": None, "ring": a["ring"]} for a in m["areas"]],
                         "paths": m["paths"], "from": ["map"]})
    for s in sheet:
        hit = next((x for x in launches if x["site"] == s["site"] and "sheet" not in x["from"]
                    and (h := _hours(x["time"], s["time"])) is not None and h <= MATCH_HOURS), None)
        if hit is None:
            launches.append({**{k: s[k] for k in ("vehicle", "vehicle_zh", "site", "site_zh", "time")},
                             "date": s["time"][:10] if s["time"] else None,
                             "notices": [{**n, "label": None, "ring": None} for n in s["notices"]], "paths": [],
                             "from": ["sheet"]})
            continue
        hit["from"].append("sheet")
        for n in s["notices"]:
            same = next((x for x in hit["notices"] if x["number"] and x["number"] == n["number"]), None)
            if same:
                same.update(start=n["start"], end=n["end"])
            else:
                hit["notices"].append({**n, "label": None, "ring": None})
    launches.sort(key=lambda x: (x["time"] or x["date"] or "", x["site"] or ""))
    for i, x in enumerate(launches):
        x["id"] = f"nfc:{(x['time'] or x['date'] or 'undated')[:16].replace(':', '')}-{i:04d}"
    return {"source": f"github.com/{REPO}", "commit": SHA, "licence": LICENCE, "attribution": ATTRIBUTION,
            "launches": launches}


def join(doc: dict, ledger: list[dict]) -> dict:
    """Tie each launch to GCAT's record of it (Chinese site, within MATCH_HOURS). Returns counts."""
    cn = [r for r in ledger if r.get("country") == "CN" or (r.get("site") or {}).get("country") == "CN"]
    joined = 0
    for x in doc["launches"]:
        x["gcat"] = None
        if not x["time"]:
            continue
        codes = GCAT_SITES.get(x["site"] or "", set())
        best = min(((h, r) for r in cn if (h := _hours(x["time"], r.get("time"))) is not None and h <= MATCH_HOURS
                    and (not codes or r.get("site_code") in codes or x["site"] == "sea")),
                   default=None, key=lambda t: t[0])
        if best:
            x["gcat"] = best[1].get("tag")
            joined += 1
    return {"launches": len(doc["launches"]), "joined_to_gcat": joined}


def summary(doc: dict) -> dict:
    """Counts for the log: launches, notices, numbered notices, charted areas, years covered, by site."""
    L = doc["launches"]
    notices = [n for x in L for n in x["notices"]]
    years = sorted({(x["time"] or x["date"] or "")[:4] for x in L} - {""})
    sites: dict[str, int] = {}
    for x in L:
        sites[x["site"] or "?"] = sites.get(x["site"] or "?", 0) + 1
    return {"notices": len(notices), "numbered": sum(1 for n in notices if n["number"]),
            "charted": sum(1 for n in notices if n["ring"]), "with_window": sum(1 for n in notices if n["start"]),
            "years": f"{years[0]}-{years[-1]}" if years else None, "by_site": sites,
            "no_time": sum(1 for x in L if not x["time"]), "vehicle_unread": sum(1 for x in L if not x["vehicle"])}
