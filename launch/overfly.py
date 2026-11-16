"""Overflight: the countries a History flight path's ground track crosses (the fourth of the old launch mapper's features;
the old tool only guessed "likely crosses land" from the azimuth).

A path is the line the History map draws: as charted (each leg a great circle) or estimated (a great circle from the
pad on the inferred azimuth, to the farthest closure area or catalog.DEFAULT_PATH_NM). It is sampled every SAMPLE_NM
along the track and each sample is looked up in the doctrine kit's Natural Earth country outlines
(doctrine/kit/geo/countries.json: admin 0, de facto borders, rings thinned to 0.05 deg, so a border is good to a few
NM and a country narrower than SAMPLE_NM across the track can be missed). Land only: territorial waters and EEZs are
not counted. The result is one list per path (an estimated path has one; a charted event can have two or three,
longest first, the one catalog.infer_path() takes its azimuth from), each a list of runs in order along the track,
{"cc", "from", "to"} in NM from the path's start (the pad, for an estimated path).

Crossing a country's ground track is not flying through its airspace: most of a launch's track is above any
airspace within a few hundred NM of the pad. The History tab says so where it shows this.
"""
from __future__ import annotations

import math
from functools import lru_cache

R_NM = 3440.065
SAMPLE_NM = 5.0
BAND = 0.25  # degrees of latitude per edge bucket
GAP_NM = 25  # a gap this short between two runs over the same country (a bay, a lagoon) is closed


class World:
    """Point-in-country lookups on the kit's outlines: even-odd over all of a country's rings (so holes and islands
    both work), with each country's edges bucketed by latitude band and a 1-degree grid of the countries whose rings'
    boxes reach each cell."""

    def __init__(self, countries: dict):
        self.countries = []
        for c in countries["countries"]:
            edges: dict[int, list[tuple[float, float, float, float]]] = {}
            for ring in c["rings"]:
                pts = ring if ring[0] == ring[-1] else ring + [ring[0]]
                for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                    if y1 == y2:
                        continue
                    for b in range(math.floor(min(y1, y2) / BAND), math.floor(max(y1, y2) / BAND) + 1):
                        edges.setdefault(b, []).append((x1, y1, x2, y2))
            xs = [p[0] for r in c["rings"] for p in r]
            ys = [p[1] for r in c["rings"] for p in r]
            self.countries.append((c["cc"], (min(xs), min(ys), max(xs), max(ys)), edges))
        self.grid: dict[tuple[int, int], list[int]] = {}
        for i, c in enumerate(countries["countries"]):
            for ring in c["rings"]:
                x0, x1 = math.floor(min(p[0] for p in ring)), math.floor(max(p[0] for p in ring))
                y0, y1 = math.floor(min(p[1] for p in ring)), math.floor(max(p[1] for p in ring))
                for gx in range(x0, x1 + 1):
                    for gy in range(y0, y1 + 1):
                        cell = self.grid.setdefault((gx, gy), [])
                        if not cell or cell[-1] != i:
                            cell.append(i)
        self._at = lru_cache(maxsize=400_000)(self._lookup)

    def _lookup(self, qx: int, qy: int) -> str | None:
        lon, lat = qx / 100, qy / 100
        hits = []
        for i in self.grid.get((math.floor(lon), math.floor(lat)), ()):
            cc, (x0, y0, x1, y1), edges = self.countries[i]
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            inside = False
            for ax, ay, bx, by in edges.get(math.floor(lat / BAND), ()):
                if (ay > lat) != (by > lat) and lon < ax + (lat - ay) * (bx - ax) / (by - ay):
                    inside = not inside
            if inside:
                hits.append(((x1 - x0) * (y1 - y0), cc))
        # An enclave (Lesotho, San Marino, the Vatican) sits inside its neighbour's outer ring when the kit keeps no
        # hole for it: the smaller country is the answer.
        return min(hits)[1] if hits else None

    def at(self, lon: float, lat: float) -> str | None:
        lon = (lon + 180) % 360 - 180
        return self._at(round(lon * 100), round(lat * 100))  # 0.01 deg cells: the outlines' own rounding


def _xyz(lon, lat):
    p, l = math.radians(lat), math.radians(lon)
    return math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p)


def _lonlat(x, y, z):
    return math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y)))


def leg_samples(a, b, step=SAMPLE_NM):
    """Points every `step` NM along the great circle a -> b ([lon, lat]), with their distance from a."""
    pa, pb = _xyz(*a), _xyz(*b)
    d = math.acos(max(-1.0, min(1.0, sum(i * j for i, j in zip(pa, pb)))))
    nm = d * R_NM
    n = max(1, math.ceil(nm / step))
    if math.sin(d) < 1e-9:  # same point, or antipodal (no single great circle): straight between them
        return [(a, 0.0), (b, nm)] if nm else [(a, 0.0)]
    out = []
    for k in range(n + 1):
        f = k / n
        s1, s2 = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        out.append((_lonlat(*(s1 * i + s2 * j for i, j in zip(pa, pb))), f * nm))
    return out


def track_samples(lon, lat, az, nm, step=SAMPLE_NM):
    """Points every `step` NM along the great circle from (lon, lat) on azimuth `az` for `nm`, with distances."""
    p1, l1, th = math.radians(lat), math.radians(lon), math.radians(az)
    out = []
    n = max(1, math.ceil(nm / step))
    for k in range(n + 1):
        d = nm * k / n
        dl = d / R_NM
        p2 = math.asin(math.sin(p1) * math.cos(dl) + math.cos(p1) * math.sin(dl) * math.cos(th))
        l2 = l1 + math.atan2(math.sin(th) * math.sin(dl) * math.cos(p1), math.cos(dl) - math.sin(p1) * math.sin(p2))
        out.append(((math.degrees(l2), math.degrees(p2)), d))
    return out


def line_samples(line, step=SAMPLE_NM):
    """A charted path (a few points, each leg a great circle) -> samples with distance from its first point."""
    out, base = [], 0.0
    for a, b in zip(line, line[1:]):
        leg = leg_samples(a, b, step)
        out.extend((p, base + d) for p, d in (leg if not out else leg[1:]))
        base += leg[-1][1]
    return out


def runs(world: World, samples) -> list[dict]:
    """Samples along a track -> the countries it crosses, in order: [{"cc", "from", "to"}] in NM."""
    out: list[dict] = []
    prev_d = 0.0
    for (lon, lat), d in samples:
        cc = world.at(lon, lat)
        if cc and out and out[-1]["cc"] == cc and out[-1]["_open"]:
            out[-1]["to"] = d
        elif cc:
            # Entered between the last sample and this one: halfway is as close as the sampling can say.
            start = 0.0 if d == 0 else (prev_d + d) / 2
            if out and out[-1]["_open"]:
                out[-1]["to"] = start
            out.append({"cc": cc, "from": start, "to": d, "_open": True})
        elif out and out[-1]["_open"]:
            out[-1]["to"] = (prev_d + d) / 2
            out[-1]["_open"] = False
        prev_d = d
    joined: list[dict] = []
    for r in out:
        if joined and joined[-1]["cc"] == r["cc"] and r["from"] - joined[-1]["to"] <= GAP_NM:
            joined[-1]["to"] = r["to"]
        else:
            joined.append(dict(r))
    return [{"cc": r["cc"], "from": round(r["from"]), "to": round(r["to"])} for r in joined]


def overflight(world: World, record: dict, chart_paths: list[list]) -> list[list[dict]] | None:
    """The countries each of a record's flight paths crosses (one list per path), or None when it has no path."""
    path = record.get("path")
    if not path:
        return None
    if path.get("kind") == "drawn":
        lines = sorted((p for p in chart_paths if len(p) >= 2), key=len, reverse=True)  # infer_path()'s max(key=len)
        return [runs(world, line_samples(p)) for p in lines] or None
    pad = record.get("pad")
    if not pad or path.get("az") is None or not path.get("nm"):
        return None
    return [runs(world, track_samples(pad[0], pad[1], path["az"], path["nm"]))]
