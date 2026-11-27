"""Reading GCAT tables for the history backfill (J. McDowell, planet4589.org/space/gcat, CC BY 4.0).

Launch reads GCAT through Orbit's snapshot on every run. The backfill is the one exception: once, from GCAT's own
tables (launch.tsv, satcat.tsv, satcat100k.tsv, sites.tsv, orgs.tsv), it lists every launch since 2012 (orbital, suborbital and missile firings) so
the history does not start on the day Launch began. The readers follow Orbit's (orbit/gcat.py, read 14 Nov 2026).
"""
from __future__ import annotations

import gzip
import re
from datetime import date
from pathlib import Path

STATE_ISO = {
    "F": "FR", "J": "JP", "UK": "GB", "D": "DE", "I": "IT", "L": "LU", "E": "ES", "N": "NO", "S": "SE",
    "T": "TH", "B": "BE", "P": "PT", "UAE": "AE", "SU": "RU", "BGN": "BG", "HKUK": "HK", "CSSR": "CZ",
    "CSFR": "CZ", "CYM": "KY", "MYM": "MM", "ESIB": "ES",
}
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
VAGUE_RE = re.compile(r"^(\d{4})(?:\s+([A-Z][a-z]{2}))?(?:\s+(\d{1,2}))?(?:\s+(\d{2})(\d{2})(?::(\d{2}))?)?")
TABLES = ("launch", "satcat", "satcat100k", "sites", "orgs")
CITATION = "Data from GCAT (J. McDowell, planet4589.org/space/gcat), CC BY 4.0"


def iso_country(state: str) -> str | None:
    s = (state or "").strip()
    if s in ("X", "-", "") or s.startswith("I-"):
        return None
    if s in STATE_ISO:
        return STATE_ISO[s]
    return s if len(s) == 2 and s.isalpha() else None


def vague_date(text: str) -> dict:
    t = (text or "").strip()
    out = {"date": None, "time": None, "uncertain": "?" in t}
    m = VAGUE_RE.match(t.replace("?", ""))
    if not m or not m.group(2) or not m.group(3):
        return out
    y, mon, d = int(m.group(1)), MONTHS.get(m.group(2)), int(m.group(3))
    if not mon:
        return out
    try:
        day = date(y, mon, d)
    except ValueError:
        return out
    out["date"] = day.isoformat()
    if m.group(4):
        hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)
        if hh < 24 and mm < 60 and ss < 60:
            out["time"] = f"{day.isoformat()}T{hh:02d}:{mm:02d}:{ss:02d}Z"
    return out


def parse_tsv(body: bytes) -> list[dict]:
    text = body.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#"):
        raise ValueError("not a GCAT table: no '#' header line")
    hdr = lines[0].lstrip("#").split("\t")
    return [dict(zip(hdr, [c.strip() for c in line.split("\t")])) for line in lines[1:] if line and not line.startswith("#")]


def sites_table(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:
        code = r.get("Site", "")
        try:
            lon, lat = float(r.get("Longitude", "")), float(r.get("Latitude", ""))
        except ValueError:
            continue
        if code not in out or r.get("TStop", "") in ("*", "-", ""):
            out[code] = {"name": r.get("ShortName") or r.get("Name") or code, "full_name": r.get("Name", ""),
                         "lat": lat, "lon": lon, "country": iso_country(r.get("StateCode", ""))}
    return out


def orgs_table(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:
        code = (r.get("Code") or "").strip()
        if code and (code not in out or r.get("TStop", "") in ("*", "-", "")):
            out[code] = {"name": r.get("Name", ""), "state": r.get("StateCode", ""),
                         "english": next((r[k] for k in ("EName", "ShortEName") if (r.get(k) or "-") != "-"), "")}
    return out


def owner_codes(owner: str) -> list[str]:
    """The organisation codes in one satcat owner field: a joint owner ('ESA/NASA') is each of its codes, GCAT's
    doubt mark ('?') is dropped."""
    return [c for c in (p.strip().rstrip("?") for p in (owner or "").split("/")) if c not in ("", "-")]


def owner_names(orgs: dict, owners) -> dict[str, str]:
    """Code -> readable name for the owner fields given: orgs.tsv's English name where it has one, else its name. A
    code orgs.tsv does not list is left out."""
    codes = sorted({c for o in owners for c in owner_codes(o)})
    return {c: orgs[c].get("english") or orgs[c]["name"] for c in codes
            if c in orgs and (orgs[c].get("english") or orgs[c]["name"]) not in ("", "-")}


def agency_country(agency: str, orgs: dict) -> str | None:
    """The first launch agency's country ('CALT', 'SPX/NASA' -> its state in orgs.tsv)."""
    first = re.split(r"[/,\s]+", (agency or "").strip())[0]
    o = orgs.get(first)
    return iso_country(o["state"]) if o else None


def read_dir(root: Path) -> dict[str, bytes]:
    """GCAT tables from a folder: either <table>.tsv / <table>.tsv.gz, or Orbit's raw cache layout
    (gcat-<table>/<hash>.tsv.gz, the newest file wins)."""
    out = {}
    for t in TABLES:
        cands = [root / f"{t}.tsv", root / f"{t}.tsv.gz"] + sorted((root / f"gcat-{t}").glob("*.tsv*"),
                                                                     key=lambda p: p.stat().st_mtime)
        cands = [p for p in cands if p.exists()]
        if not cands:
            raise FileNotFoundError(f"no GCAT {t} table in {root}")
        p = cands[-1]
        body = p.read_bytes()
        out[t] = gzip.decompress(body) if p.suffix == ".gz" else body
    return out
