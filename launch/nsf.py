"""Links to the NASASpaceflight forum's Chinese launch threads, from NotamForChina's link list.

NotamForChina (github.com/mikezang/NotamForChina, Apache-2.0, pinned at nfc.SHA) keeps `data/nsfLinkList.html`: one
link per forum thread, with the thread's title ("Shijian-11-07 - CZ-2C - JSLC - 05:28UTC, September 28, 2014").
Launch reads that file from GitHub, never the forum: the threads are linked from the History tab, not collected.
`fetch` copies the file at the pinned commit into git-ignored history/nfc_source/; `build` writes
history/nsf_links.json (committed): each thread's topic number, link, title and the launch date, UTC time and
vehicle read from the title where it gives them. catalog.nsf_join() puts each dated thread on its launch.
"""
from __future__ import annotations

import html
import re
import urllib.request
from pathlib import Path

from . import nfc as NFC
from . import programs as P

FILE = "data/nsfLinkList.html"
UA = "launch-history (github.com/metacog-osint/launch)"
LINK = re.compile(r"<a\b[^>]*\bhref=[\"']?([^\"' >]+)[\"']?[^>]*>(.*?)</a>", re.I | re.S)
TOPIC = re.compile(r"[?&;]topic=(\d+)")
PREFIX = re.compile(r"^\s*\d+:\s*Page\d+:\s*")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
_MON = "(" + "|".join(MONTHS) + ")"
DATE_MDY = re.compile(_MON + r"\s+(\d{1,2}),?\s+(\d{4})", re.I)
DATE_DMY = re.compile(r"\b(\d{1,2})\s+" + _MON + r",?\s+(\d{4})", re.I)
TIME = re.compile(r"\b(\d{1,2}):?(\d{2})(?::\d{2}(?:\.\d+)?)?\s*UTC", re.I)  # 05:28UTC, 0927UTC, 13:14:02.491 UTC
VEHICLE = re.compile(r"\b(CZ-\d+[A-Z]?|Long March[- ]\d+[A-Z]?|Jielong-\d|Kuaizhou-\d+[A-Z]?|KZ-\d+[A-Z]?|Ceres-\d|"
                     r"Zhuque-\d+[A-Z]?|ZQ-\d+[A-Z]?|Kinetica-\d|Lijian-\d|Hyperbola-\d+|Tianlong-\d|Gravity-\d|"
                     r"Kaituozhe-\d+[A-Z]?|OS-M\d?)\b", re.I)


def fetch(dest: Path) -> Path:
    """The link list at NotamForChina's pinned commit -> dest/data/nsfLinkList.html (GitHub, not the forum)."""
    url = f"https://raw.githubusercontent.com/{NFC.REPO}/{NFC.SHA}/{FILE}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    out = dest / FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return out


def read_title(title: str) -> dict:
    """The launch date (YYYY-MM-DD), UTC time (HH:MM) and vehicle a thread title gives, each None when it gives none."""
    t = PREFIX.sub("", title)
    date, span = None, (0, 0)
    m = DATE_MDY.search(t)
    if m:
        date, span = f"{int(m.group(3)):04d}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}", m.span()
    else:
        m = DATE_DMY.search(t)
        if m:
            date, span = f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}", m.span()
    # a time outside the date (the year is not a time), hours 0-23, minutes 0-59
    tm = next((x for x in TIME.finditer(t) if (x.end() <= span[0] or x.start() >= span[1])
               and int(x.group(1)) < 24 and int(x.group(2)) < 60), None)
    time = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm and date else None
    vm = VEHICLE.search(t)
    veh = P.vehicle(re.sub(r"Long March[- ]", "CZ-", vm.group(1), flags=re.I)) if vm else None
    return {"date": date, "time": time, "vehicle": veh}


def parse(body: str) -> list[dict]:
    """Every forum link in the list: topic number, link (the whole thread), title as listed, and read_title()."""
    out, seen = [], set()
    for href, text in LINK.findall(body):
        href = html.unescape(href)
        m = TOPIC.search(href)
        if "nasaspaceflight.com" not in href or not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        title = PREFIX.sub("", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text)))).strip()
        out.append({"topic": m.group(1), "url": f"https://forum.nasaspaceflight.com/index.php?topic={m.group(1)}.0",
                    "title": title, **read_title(title)})
    return out


def build(src: Path) -> dict:
    p = src / FILE
    if not p.exists():
        raise SystemExit(f"No {p}. Run `python tools/launch.py nfc links` first.")
    links = parse(p.read_text(encoding="utf-8", errors="replace"))
    return {"version": 1, "source": f"https://github.com/{NFC.REPO}/blob/{NFC.SHA}/{FILE}", "commit": NFC.SHA,
            "licence": NFC.LICENCE,
            "note": "Thread links and titles as NotamForChina lists them; the forum itself is not read.",
            "links": links}


def summary(doc: dict) -> dict:
    ls = doc.get("links") or []
    return {"links": len(ls), "dated": sum(1 for x in ls if x.get("date")),
            "timed": sum(1 for x in ls if x.get("time")), "vehicle": sum(1 for x in ls if x.get("vehicle"))}
