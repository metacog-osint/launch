"""Closure-area patterns from the history: where each pad's closures fall, which drop zones recur, which are new.

Everything here is counted from the history file; nothing is predicted.

  corridors   per pad (the start of the event's flight path, rounded to 0.1 degree): each closure area's azimuth
              from the pad, its distance downrange and the inclination that azimuth implies. Areas are grouped
              into corridors of 5-degree azimuth bands.
  recurring   drop zones used by three or more events: areas whose centres lie within RECUR_NM of each other.
  first_seen  for each recurring zone, the first event that used it, so a new zone stands out.
  windows     how long closures stay open (B) to C)), by layer.
  firs        notices per FIR per year.
  hours       launch hour (UTC) by actor.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from . import notam

RECUR_NM = 25.0
RECUR_MIN = 3
BAND = 5


def _pad_key(pad) -> str:
    return f"{pad[1]:.1f},{pad[0]:.1f}"


def corridors(events: list[dict], sites: list[dict]) -> list[dict]:
    pads = defaultdict(lambda: {"events": set(), "bands": defaultdict(list)})
    for e in events:
        if e["kind"] != "launch" or not e.get("pad"):
            continue
        k = _pad_key(e["pad"])
        pads[k]["events"].add(e["id"])
        pads[k]["pad"] = e["pad"]
        for a in e["areas"]:
            if a.get("azimuth") is None:
                continue
            band = int(a["azimuth"] // BAND) * BAND
            pads[k]["bands"][band].append({"event": e["id"], "label": e["label"], "time": e["time"],
                                           "azimuth": a["azimuth"], "downrange_nm": a["downrange_nm"],
                                           "inclination_est": a["inclination_est"]})
    out = []
    for k, p in pads.items():
        site = _nearest_site(p["pad"], sites)
        bands = []
        for band, rows in sorted(p["bands"].items()):
            evs = sorted({r["event"] for r in rows})
            incl = sorted(r["inclination_est"] for r in rows)
            bands.append({"from": band, "to": band + BAND, "areas": len(rows), "events": len(evs),
                          "inclination_median": incl[len(incl) // 2],
                          "downrange_nm": [min(r["downrange_nm"] for r in rows), max(r["downrange_nm"] for r in rows)],
                          "latest": max((r["time"] or "") for r in rows) or None})
        out.append({"pad": p["pad"], "site": site, "events": len(p["events"]), "bands": bands})
    return sorted(out, key=lambda x: -x["events"])


def _nearest_site(pt, sites, within_nm: float = 20.0) -> str | None:
    best, name = within_nm, None
    for s in sites:
        d = notam.haversine_nm(pt[1], pt[0], s["lat"], s["lon"])
        if d < best:
            best, name = d, s["name"]
    return name


def recurring(events: list[dict]) -> list[dict]:
    """Greedy clustering of area centres: each zone is seeded by its earliest area."""
    rows = sorted(((e["time"] or "9999", e, a) for e in events if e["kind"] in ("launch", "upcoming")
                   for a in e["areas"]), key=lambda r: r[0])
    zones: list[dict] = []
    for t, e, a in rows:
        lon, lat = a["centroid"]
        for z in zones:
            if notam.haversine_nm(lat, lon, z["centre"][1], z["centre"][0]) <= RECUR_NM:
                z["uses"].append({"event": e["id"], "label": e["label"], "time": e["time"], "actor": e["actor"]})
                break
        else:
            zones.append({"centre": [lon, lat], "ring": a["ring"], "uses": [
                {"event": e["id"], "label": e["label"], "time": e["time"], "actor": e["actor"]}]})
    out = []
    for z in zones:
        evs = {u["event"] for u in z["uses"]}
        if len(evs) >= RECUR_MIN:
            uses = sorted(z["uses"], key=lambda u: u["time"] or "9999")
            out.append({"centre": [round(z["centre"][0], 3), round(z["centre"][1], 3)], "ring": z["ring"],
                        "events": len(evs), "first": uses[0], "latest": uses[-1],
                        "actors": dict(Counter(u["actor"] or "unknown" for u in uses))})
    return sorted(out, key=lambda z: -z["events"])


def windows(events: list[dict]) -> dict:
    by = defaultdict(list)
    for e in events:
        for n in e["notams"]:
            if n.get("start") and n.get("end"):
                h = (datetime.fromisoformat(n["end"][:19]) - datetime.fromisoformat(n["start"][:19])).total_seconds() / 3600
                if 0 <= h < 24 * 90:
                    by[e["layer"]].append(h)
    out = {}
    for layer, hs in by.items():
        hs.sort()
        out[layer] = {"notams": len(hs), "median_h": round(hs[len(hs) // 2], 2),
                      "p90_h": round(hs[int(len(hs) * 0.9)], 2), "max_h": round(hs[-1], 1)}
    return out


def firs(events: list[dict]) -> list[dict]:
    c = Counter()
    for e in events:
        for n in e["notams"]:
            fir = (n.get("q") or {}).get("fir")
            yr = (n.get("start") or "")[:4]
            if fir and yr:
                c[(fir, yr)] += 1
    rows = defaultdict(dict)
    for (fir, yr), n in c.items():
        rows[fir][yr] = n
    return sorted(({"fir": f, "state": notam.state_of_fir(f), "by_year": dict(sorted(y.items())),
                    "total": sum(y.values())} for f, y in rows.items()), key=lambda r: -r["total"])


def hours(events: list[dict]) -> dict:
    by = defaultdict(Counter)
    for e in events:
        if e["kind"] == "launch" and e["time_basis"] == "time":
            by[e["actor"] or "other"][int(e["time"][11:13])] += 1
    return {a: [c.get(h, 0) for h in range(24)] for a, c in by.items()}


def build(events: list[dict], sites: list[dict]) -> dict:
    return {"corridors": corridors(events, sites), "recurring": recurring(events), "windows": windows(events),
            "firs": firs(events), "hours": hours(events),
            "rules": {"recur_nm": RECUR_NM, "recur_min_events": RECUR_MIN, "azimuth_band_deg": BAND}}
