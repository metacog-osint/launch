"""The gate between the source map (Launch's charted notices) and the public history file.

history/history.json is committed and is published as data/history.json, so nothing may reach it that has not
been cleared. For the map's "Launch Sites" layer the rule is:

  sites   only a name listed in history/public_sites.json is published, with its kind: launch pad, landing site
          or drop zone. A site that is not listed is withheld, so a point added to the map later stays out until
          someone lists it. A name that reads as a ship (YW-*), or that carries a date or a time of day, is never
          published, listed or not: a position with a time on it is a track point, not a site.
  notes   the map's own free text on a site is never published. The only note a site can carry is the text
          written for it in history/public_sites.json, and that text may not hold a speed, a heading, a
          coordinate or a time of day.

  events  an event whose name reads as a ship is never published. (What else of an event is withheld is decided
          at import, in history.py: positions tied to a restricted source, and points with no notice behind them.)

sites() applies the rule at import. history() and patterns() apply it again when the site is built, so a history
file written by older code cannot publish more than the rule allows. problems() is the check that the tests run
on the committed files and that `launch.py check` runs on the built ones, before any deploy.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

ALLOWLIST = Path(__file__).resolve().parents[1] / "history" / "public_sites.json"
KINDS = ("launch pad", "landing site", "drop zone")
SITE_KEYS = ("name", "lon", "lat", "kind", "note")
RULE = ("Launch pads, landing sites and drop zones named on Launch's allow-list. Other points on the source map, "
        "and the map's own notes on its sites, are not published.")

# Edges are written out instead of \b: the map's names join their parts with underscores ("11 Jan 24_0530UTC_..."),
# and \b counts an underscore as a letter. Hemisphere letters and true/magnetic marks are upper case only, so
# "China's 2026 plans" or "100 m" in a note is not read as a position or a heading.
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
# A line of the map's own about where a notice came from (see history.SOURCE_LINE): never published.
SOURCE_LINE = re.compile(r"\bSOURCES?\s*[:\-]", re.I)
SHIP = re.compile(r"(?<![A-Za-z0-9])YW(?:[-\s_]*\d|[-_]|(?![A-Za-z0-9]))|YUAN[\s-]?WANG|LIAO[\s-]?WANG|"
                  r"(?<![A-Za-z0-9])(?:ships?|vessels?|USNS)(?![A-Za-z0-9])", re.I)
SPEED = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*(?:kts?|knots?|kn|mph|kph|km/h|kmh|m/s)(?![A-Za-z0-9])|"
                   r"(?<![A-Za-z0-9])(?:speed|sog)(?![A-Za-z0-9])", re.I)
HEADING = re.compile(
    r"(?<![A-Za-z0-9])(?:heading|hdg|course|cog|bearing|brg)(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])(?:north|south|east|west)(?:[-\s]?(?:east|west))?[-\s]?bound(?![A-Za-z0-9])"
    r"|(?<![0-9.])[0-3]\d\d\s?[°º]?\s?(?:true|mag(?:netic)?)(?![A-Za-z0-9])"   # 270 true
    r"|(?<![0-9.])(?-i:[0-3]\d\d[°º]?[TM])(?![A-Za-z0-9])"                      # 090T
    r"|\d\s*(?:[°º]|deg(?:rees?)?(?![A-Za-z0-9]))", re.I)                       # 97°, 97 deg
COORD = re.compile("|".join([
    r"(?<![0-9.])\d{4,7}(?:\.\d+)?\s?[NS](?![A-Za-z])",                         # 3553N, 360200N, 360200N1120100E
    r"(?<![0-9.])\d{5,8}(?:\.\d+)?\s?[EW](?![A-Za-z])",                         # 11209E, 1120100E
    r"(?<![A-Za-z])[NS]\s?\d{4,7}(?:\.\d+)?(?![0-9])",                          # N360200, N360200E1120100
    r"(?<![A-Za-z])[EW]\s?\d{5,8}(?:\.\d+)?(?![0-9])",                          # E1120100
    r"(?<![0-9])\d{1,3}-\d{1,2}(?:\.\d+)?(?:-\d{1,2}(?:\.\d+)?)?\s?[NSEW](?![A-Za-z])",        # 59-42.60S
    r"(?<![0-9.])\d{1,3}\s+\d{1,2}(?:\s+\d{1,2}(?:\.\d+)?)?\s?[NSEW](?![A-Za-z])",             # 36 31 00 S
    r"(?<![0-9.])\d{1,2}\s?[NS][\s,/]+\d{1,3}\s?[EW](?![A-Za-z])",                             # 38N 111E
    r"(?<![0-9.])\d{1,3}\.\d+\s?[NSEW](?![A-Za-z])",                                           # 38.85N
    r"(?<![0-9.])[-+]?\d{1,3}\.\d{2,}\s*[,;/\s]\s*[-+]?\d{1,3}\.\d{2,}(?![0-9])",              # 38.8491, 111.6085
    r"\d\s?[°º]",                                                                              # 38° 51'
    r"(?<![A-Za-z0-9])\d{1,2}[C-HJ-NP-X]\s?[A-HJ-NP-Z]{2}\s?\d{4,10}(?![0-9])",                # MGRS 51RUQ12345678
    r"(?i:(?<![A-Za-z])(?:lat|lon|latitude|longitude|coords?|coordinates?|mgrs)(?![A-Za-z]))",
]))
TIME = re.compile(r"(?<![0-9])(?:[01]\d|2[0-4])[0-5]\d\s?(?:z|utc|gmt|lt|local|zulu)(?![A-Za-z])"   # 0846Z, 1132 UTC
                  r"|(?<![0-9:])(?:[01]?\d|2[0-3]):[0-5]\d(?![0-9])"                                # 19:24
                  r"|(?<![0-9])\d{1,2}\s?(?:am|pm)(?![A-Za-z])", re.I)
DATE = re.compile(r"(?<![A-Za-z0-9])\d{1,2}\s*" + _MONTH + r"\.?(?:\s*'?\d{2,4})?(?![A-Za-z])"       # 11 Jan 24
                  r"|(?<![A-Za-z])" + _MONTH + r"\.?\s+\d{1,2}(?:,\s*|\s+)\d{4}(?![0-9])"             # March 22, 2026
                  r"|(?<![0-9])\d{4}-\d{2}-\d{2}(?![0-9])"
                  r"|(?<![0-9/])\d{1,2}/\d{1,2}/\d{2,4}(?![0-9/])", re.I)
NOTE_SCREENS = (("a speed", SPEED), ("a heading", HEADING), ("a coordinate", COORD), ("a time of day", TIME))
NAME_SCREENS = (("reads as a ship", SHIP), ("carries a date", DATE), ("carries a time of day", TIME),
                ("carries a speed", SPEED), ("carries a heading", HEADING), ("carries a coordinate", COORD))


def key(name: str | None) -> str:
    """A site name as the allow-list is matched: spaces collapsed, accents in one form. Case is kept."""
    return unicodedata.normalize("NFC", " ".join((name or "").split()))


def note_problems(text: str | None) -> list[str]:
    """What a note holds that keeps it out of the public file: a speed, a heading, a coordinate, a time of day."""
    return [label for label, rx in NOTE_SCREENS if text and rx.search(text)]


def name_problems(name: str | None) -> list[str]:
    """Why a name can never be a public site: it reads as a ship, or carries a date, time, speed, heading or
    coordinate (a pad does not have a time)."""
    return [label for label, rx in NAME_SCREENS if rx.search(name or "")]


def allowlist(path: Path | str | None = None) -> dict:
    """history/public_sites.json as {kinds: {name: kind}, notes: {name: text}, held: {name: reason},
    problems: [...]}. A list that does not parse cleanly publishes nothing it is unsure of: a name listed
    twice, under an unknown kind or as both published and held is left out, and said so in `problems`."""
    raw = json.loads(Path(path or ALLOWLIST).read_text(encoding="utf-8"))
    kinds, problems = {}, []
    held = {key(k): str(v) for k, v in (raw.get("held") or {}).items()}
    for kind, names in (raw.get("publish") or {}).items():
        if kind not in KINDS:
            problems.append(f"allow-list: '{kind}' is not a kind ({', '.join(KINDS)}); its {len(names)} names are not published")
            continue
        for n in names:
            k = key(n)
            if k in kinds:
                problems.append(f"allow-list: '{k}' is listed twice")
            elif k in held:
                problems.append(f"allow-list: '{k}' is both published and held; it is not published")
            elif name_problems(k):
                problems.append(f"allow-list: '{k}' {' and '.join(name_problems(k))}; it is never published")
            else:
                kinds[k] = kind
    notes = {}
    for n, text in (raw.get("notes") or {}).items():
        k, text = key(n), " ".join(str(text or "").split())
        if k not in kinds:
            problems.append(f"allow-list: a note is written for '{k}', which is not a published site")
        elif note_problems(text):
            problems.append(f"allow-list: the note for '{k}' holds {' and '.join(note_problems(text))}; it is not published")
        elif text:
            notes[k] = text
    return {"kinds": kinds, "notes": notes, "held": held, "problems": problems}


def sites(candidates: list[dict], allow: dict | None = None) -> tuple[list[dict], dict]:
    """The sites that may be published, and a count of what was withheld and why.

    Only `name`, `lon` and `lat` are read from a candidate. Whatever else it carries (the map's own note, in a
    history file written by older code) is dropped; the note comes from the allow-list or not at all."""
    allow = allow or allowlist()
    out, withheld, kinds, unlisted = [], Counter(), Counter(), []
    for s in candidates or []:
        name = (s.get("name") or "").strip()
        k = key(name)
        why = name_problems(k)
        if why:
            withheld["the name " + why[0]] += 1
        elif k in allow["kinds"]:
            kind = allow["kinds"][k]
            out.append({"name": name, "lon": s["lon"], "lat": s["lat"], "kind": kind, "note": allow["notes"].get(k)})
            kinds[kind] += 1
        elif k in allow["held"]:
            withheld["held on the allow-list"] += 1
        else:
            withheld["not on the allow-list"] += 1
            unlisted.append(name)
    return out, {"published": len(out), "kinds": dict(kinds), "notes": sum(1 for s in out if s["note"]),
                 "withheld": dict(withheld), "not_listed": sorted(set(unlisted))}


def ship_named(event: dict) -> bool:
    """An event whose name reads as a ship is a ship, not a launch or a notice: it is never published."""
    return bool(SHIP.search(key(event.get("label"))) or SHIP.search(key(event.get("extra"))))


def history(hist: dict, allow: dict | None = None) -> dict:
    """The history file as it may be published: its sites put through the gate again, and no event that is
    named as a ship."""
    out = {}
    for k, v in hist.items():
        if k == "sites":
            if "sites_rule" not in hist:
                out["sites_rule"] = RULE
            v = sites(v, allow)[0]
        elif k == "events":
            v = [e for e in v if not ship_named(e)]
        out[k] = v
    return out


def patterns(pat: dict, hist: dict) -> dict:
    """patterns.json as it may be published: a corridor is named after a site only if that site is published."""
    names = {s["name"] for s in hist.get("sites") or []}
    return {**pat, "corridors": [c if (c.get("site") is None or c["site"] in names) else {**c, "site": None}
                                 for c in pat.get("corridors") or []]}


def problems(hist: dict, pat: dict | None = None, allow: dict | None = None) -> list[str]:
    """Everything in a history file (and its patterns file) that the rule forbids. Empty when it may be
    published. The messages name sites and reasons, never a position or a note's text."""
    allow = allow or allowlist()
    errs = list(allow["problems"])
    names = set()
    for s in hist.get("sites") or []:
        name = s.get("name") or ""
        k = key(name)
        why = name_problems(k)
        if why:
            # a ship's name is not repeated in a log
            errs.append("a site whose name reads as a ship (YW-*) is in the file" if SHIP.search(k)
                        else f"site '{k}' is in the file, and its name {' and '.join(why)}")
            continue
        names.add(name)
        if k not in allow["kinds"]:
            errs.append(f"site '{k}' is not on the allow-list (history/public_sites.json)")
        elif s.get("kind") != allow["kinds"][k]:
            errs.append(f"site '{k}': kind is {s.get('kind')!r}, the allow-list says {allow['kinds'][k]!r}")
        extra = sorted(set(s) - set(SITE_KEYS))
        if extra:
            errs.append(f"site '{k}' carries fields that are not published: {', '.join(extra)}")
        note = s.get("note")
        if note:
            bad = note_problems(note)
            if bad:
                errs.append(f"site '{k}': its note holds {' and '.join(bad)}")
            if note != allow["notes"].get(k):
                errs.append(f"site '{k}': its note is not the one written for it on the allow-list")
    ships = sum(1 for e in hist.get("events") or [] if ship_named(e))
    sourced = sum(1 for e in hist.get("events") or []
                  if any(SOURCE_LINE.search(n.get("text") or "") for n in e.get("notams") or [])
                  or any(SOURCE_LINE.search(t or "") for t in e.get("texts") or []))
    if sourced:
        errs.append(f"{sourced} event(s) carry a SOURCE line in a notice's text")
    if ships:
        errs.append(f"{ships} event(s) named as a ship are in the file")
    for c in (pat or {}).get("corridors") or []:
        if c.get("site") and c["site"] not in names:
            errs.append("a corridor in patterns.json is named after a site that is not published"
                        + ("" if name_problems(c["site"]) else f": '{c['site']}'"))
    return errs
