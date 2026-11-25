"""Which closure areas belong to a launch's ascent, and the path through them (catalog.infer_path).

A launch's ascent areas (booster, fairing and stage drop zones) lie along its climb, and a dog-leg shows as their
bearings from the pad changing with distance: Qianfan's LM-6A from Taiyuan at 171 deg 180 NM out, 175 at 600 and
178 at 1,236; Chollima-1 of 21 Nov 2023 at 191 deg in the Yellow Sea and 170 east of Luzon, where its second stage
turned east (Langbroek, SatTrackCam Leiden, 21 Nov 2023). So the path runs from the pad through each ascent area in
order of distance, and on from the last at the orbit's heading.

Not every area joined to a launch is on its ascent. Each is tested, in this order:
  time         the notice's windows (TIME_TOL_H either side) or its daily schedule (SCHED_TOL_MIN either side) do
               not hold the launch: another event's (LM-2D of 12 Dec 2024: A4241/24's 0541-0705 and 0856-1020 skip
               the 07:17 launch)
  later pass   off the first pass of the launch's own orbit and on a later pass (an upper stage's disposal area,
               SWOT of 16 Dec 2022: HYDROPAC 3529/22, 1 h 48 min after liftoff on its second southbound pass)
  far          beyond AREA_NM, unless tied to the launch's own notices and on its first pass (LM-2D of 12 Dec 2024,
               Brisbane FIR N5532/24, 3,484 NM out on its track)
  off bearing  a notice joined by its window alone, off the bearing the launch's other areas share: another event's
               (Lijian-2 of 3 Nov 2026: two areas at 135 deg, 960 NM off its track, beside its two at 187)
A notice's areas stand or fall together (HYDROPAC 2699/23 holds all three of Chollima-1's stage areas).

The ground track is an orbit on a spherical, rotating Earth, from the pad at liftoff. When GCAT gives the launch's
orbit (perigee and apogee, km), the track is that ellipse, perigee at the pad, for its period and ORBIT_TOL_MIN either
side; else a circular orbit for each period in PERIODS: good to about ON_TRACK_NM, enough to tell a first pass from a
later one.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from . import history, notam

TIME_TOL_H = 2          # a notice's window holds a launch this long either side (Joey0609's join rule)
SCHED_TOL_MIN = 10      # ... and its daily schedule this long either side (a launch flies inside its active
                        # window; the schedule's gaps are hours another event uses)
ON_TRACK_NM = 150       # an area this near a pass of the orbit's ground track lies on it
FIRST_MIN = 20          # the first pass: liftoff to this many minutes (ascent areas lie within ~15 min of flight)
LATER_MIN_NM = 1000     # a later-pass area lies at least this far from the pad and more than 2 x ON_TRACK_NM off
                        # the first pass (a dog-leg's areas lie off the first pass too, nearer in)
ASCENT_LAG_MIN = 6      # the model flies at orbital speed from liftoff; a real vehicle reaches orbit ~9 min in
PERIODS = range(88, 108, 2)   # minutes: circular orbits ~200 to ~1,100 km, when GCAT gives no orbit
ORBIT_TOL_MIN = 1       # with GCAT's orbit, its period and this either side (the ascent's timing is modelled)
EARTH_KM, MU_KM3_S2 = 6378.137, 398600.4418
EARTH_DEG_MIN = 360 / 1436.07
BEND_NM = 25            # a point this far off the straight line from the pad to the last area makes a bend
                        # (traj.js flags a dog-leg at 25 NM)
ZIGZAG_NM = 8           # area points this far off both sides of the line from the pad to the last are one line
                        # (zigzag()); nearer, a point lies within its own drop zone's width of the line
MAX_TURN_DEG = 40       # a point the path would turn sharper than this at is off the climb's line, not a dog-leg
                        # (areas side by side at about one distance); the largest real turns seen are ~30 deg
CLUSTER_NM = 60         # areas within this (or CLUSTER_FRAC of the distance) of the same distance are one point
CLUSTER_FRAC = 0.12
TIE_NOTAM = "notam"     # an area tied to the launch by its own notices (charted, NotamForChina, a NOTAM number,
TIE_WINDOW = "window"   # a reviewed published notice); else joined by its window and place alone

WHY = {"time": "its notice's window or schedule does not hold the launch",
       "later": "on a later pass of the launch's own orbit (an upper stage's disposal area)",
       "far": "farther than the ascent and off its first pass",
       "bearing": "joined by window alone, off the bearing the launch's other areas share"}


def _dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _unit(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def _nm(u, v) -> float:
    d = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1] + u[2] * v[2]))
    return math.acos(d) * 3440.065


def period_min(orbit_km) -> float | None:
    """The period (minutes) of an orbit [perigee, apogee] in km, or None when it is not a usable Earth orbit."""
    try:
        pe, ap = float(orbit_km[0]), float(orbit_km[1])
    except (TypeError, ValueError, IndexError):
        return None
    if ap < 100 or pe > ap or pe < -EARTH_KM / 2:
        return None
    a = EARTH_KM + (pe + ap) / 2
    return 2 * math.pi * math.sqrt(a ** 3 / MU_KM3_S2) / 60


def _true_anomaly(m: float, e: float) -> float:
    """The true anomaly at mean anomaly m (radians) of an orbit of eccentricity e (Kepler's equation, Newton)."""
    E = m if e < 0.8 else math.pi
    for _ in range(30):
        E -= (E - e * math.sin(E) - m) / (1 - e * math.cos(E))
    return 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2))


def track(lat0: float, lon0: float, inc: float, north: bool, period: float, t0: float, t1: float,
          step: float = 0.5, lag: float = 0.0, ecc: float = 0.0) -> list[tuple[float, tuple]]:
    """[(minutes after liftoff, unit vector)] along an orbit's ground track through the pad (perigee there when
    `ecc` > 0); `lag`: minutes the Earth turns beyond the orbit's own time (the ascent is slower than the orbit)."""
    s = math.sin(math.radians(lat0)) / math.sin(math.radians(inc))
    if abs(s) > 1:
        return []
    u0 = math.asin(s) if north else math.pi - math.asin(s)
    ci = math.cos(math.radians(inc))
    node = math.radians(lon0) - math.atan2(ci * math.sin(u0), math.cos(u0))
    out, t = [], t0
    while t <= t1:
        m = 2 * math.pi * t / period
        u = u0 + (_true_anomaly(m, ecc) if ecc > 1e-4 else m)
        la = math.asin(math.sin(math.radians(inc)) * math.sin(u))
        lo = node + math.atan2(ci * math.sin(u), math.cos(u)) - math.radians(EARTH_DEG_MIN * (t + (lag if t > 0 else 0)))
        out.append((t, _unit(math.degrees(la), math.degrees(lo))))
        t += step
    return out


class Orbit:
    """The first and later passes of an orbit of inclination `inc` through the pad, both directions."""

    def __init__(self, pad, inc: float, north: bool | None = None, orbit_km=None):
        """`north`: the launch heads north (True) or south (False); None tries both. `orbit_km`: GCAT's [perigee,
        apogee] for the launch, which sets the later passes' period and shape (else PERIODS, circular)."""
        self.ok = inc is not None and 0 < inc < 180 and abs(pad[1]) <= min(inc, 180 - inc)
        if not self.ok:
            return
        ways = (True, False) if north is None else (north,)
        self.first = [p for w in ways for _, p in track(pad[1], pad[0], inc, w, 92, 0, FIRST_MIN)]
        per0 = period_min(orbit_km)
        if per0:
            pe, ap = float(orbit_km[0]), float(orbit_km[1])
            ecc = (ap - pe) / (2 * EARTH_KM + pe + ap)
            pers = [per0 - ORBIT_TOL_MIN, per0, per0 + ORBIT_TOL_MIN]
        else:
            ecc, pers = 0.0, list(PERIODS)
        self.later = [p for w in ways for per in pers
                      for _, p in track(pad[1], pad[0], inc, w, per, per / 2, 2.2 * per, 1.0, lag=ASCENT_LAG_MIN,
                                        ecc=ecc)]

    def first_nm(self, lat, lon) -> float | None:
        if not self.ok:
            return None
        u = _unit(lat, lon)
        return min(_nm(u, p) for p in self.first)

    def later_nm(self, lat, lon) -> float | None:
        if not self.ok:
            return None
        u = _unit(lat, lon)
        return min(_nm(u, p) for p in self.later)


def _sched_holds(sched: str | None, t: datetime) -> bool | None:
    """A daily schedule ("0541-0705,0856-1020", UTC): does it hold t (SCHED_TOL_MIN either side)? None: unread."""
    if not sched:
        return None
    pairs = re.findall(r"(\d{2})(\d{2})-(\d{2})(\d{2})", sched)
    if not pairs:
        return None
    m = t.hour * 60 + t.minute
    for a, b, c, d in pairs:
        lo, hi = int(a) * 60 + int(b) - SCHED_TOL_MIN, int(c) * 60 + int(d) + SCHED_TOL_MIN
        if hi < lo + 2 * SCHED_TOL_MIN:  # past midnight
            hi += 1440
        if lo <= m <= hi or lo <= m + 1440 <= hi:
            return True
    return False


def time_holds(area: dict, t: datetime | None) -> bool:
    """False only when the area's notice gives windows (or a daily schedule) and none holds the launch."""
    if t is None:
        return True
    ws = [(_dt(a), _dt(b)) for a, b in area.get("windows") or []]
    ws = [(a, b) for a, b in ws if a and b]
    tol = timedelta(hours=TIME_TOL_H)
    if ws and not any(a - tol <= t <= b + tol for a, b in ws):
        return False
    return _sched_holds(area.get("schedule"), t) is not False


def _adiff(a: float, b: float) -> float:
    x = abs(a - b) % 360
    return min(x, 360 - x)


def dest(pad, az: float, nm: float) -> list[float]:
    """The point `nm` from the pad on bearing `az` (great circle), [lon, lat]."""
    d, b = nm / 3440.065, math.radians(az)
    la1, lo1 = math.radians(pad[1]), math.radians(pad[0])
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2))
    return [round((math.degrees(lo2) + 540) % 360 - 180, 4), round(math.degrees(la2), 4)]


def centre(pad, a: dict) -> list[float]:
    return a.get("centroid") or dest(pad, a["azimuth"], a["downrange_nm"])


def select(pad, near: list[dict], far: list[dict], *, time=None, inc=None, own=False, area_nm=2500,
           spread=15.0, branch_az=None, others: list | None = None, orbit_km=None) -> tuple[list[dict], dict]:
    """(the ascent areas, {reason: count} of those set aside). `near`: areas within the distance limits; `far`:
    beyond area_nm. Each area: azimuth, downrange_nm, centroid [lon, lat], and optionally tie, notice, windows,
    schedule. `own`: the inclination is the record's own (a borrowed one tests nothing). `branch_az`: the
    azimuths that inclination allows from the pad. `others`: a list that gains the areas set aside as another
    event's (window or schedule, bearing); a later pass or a far area is still the launch's own. `orbit_km`: GCAT's
    [perigee, apogee] for the launch (Orbit)."""
    t = _dt(time)
    timed = [a for a in near + far if time_holds(a, t)]
    nearest = min(timed, key=lambda a: a["downrange_nm"]) if timed else None
    north = None if nearest is None else math.cos(math.radians(nearest["azimuth"])) > 0
    orbit = Orbit(pad, inc, north, orbit_km) if (own and inc) else None
    aside: dict[str, int] = {}
    keep = []
    for a in near + far:
        why = None
        if a not in timed:
            why = "time"
        elif orbit and orbit.ok:
            lo, la = centre(pad, a)
            fn = orbit.first_nm(la, lo)
            if (a["downrange_nm"] >= LATER_MIN_NM and fn > 2 * ON_TRACK_NM
                    and orbit.later_nm(la, lo) <= ON_TRACK_NM):
                why = "later"
            elif a["downrange_nm"] > area_nm and not (a.get("tie") == TIE_NOTAM and fn <= ON_TRACK_NM):
                why = "far"
        elif a["downrange_nm"] > area_nm:
            why = "far"
        if why:
            aside[why] = aside.get(why, 0) + 1
            if why == "time" and others is not None:
                others.append(a)
        else:
            keep.append(a)
    if not keep:
        return [], aside
    tied = [a for a in keep if a.get("tie") == TIE_NOTAM]
    if tied:
        chosen = [a for a in keep if a.get("tie") == TIE_NOTAM
                  or any(_adiff(a["azimuth"], x["azimuth"]) <= spread for x in tied)]
    else:
        def group(x):
            return [y for y in keep if _adiff(x["azimuth"], y["azimuth"]) <= spread]

        def score(x):
            g = group(x)
            off = min(_adiff(x["azimuth"], b) for b in branch_az) if branch_az else 0
            return (len(g), -round(off / spread), max(y["downrange_nm"] for y in g))
        chosen = group(max(keep, key=score))
    notices = {a.get("notice") for a in chosen if a.get("notice")}
    chosen = [a for a in keep if a in chosen or (a.get("notice") and a.get("notice") in notices)]
    n = len(keep) - len(chosen)
    if n:
        aside["bearing"] = n
        if others is not None:
            others.extend(a for a in keep if a not in chosen)
    return chosen, aside


def _mean_point(pts: list[list[float]]) -> list[float]:
    x = sum(_unit(p[1], p[0])[0] for p in pts)
    y = sum(_unit(p[1], p[0])[1] for p in pts)
    z = sum(_unit(p[1], p[0])[2] for p in pts)
    r = math.sqrt(x * x + y * y + z * z) or 1
    return [round(math.degrees(math.atan2(y, x)), 3), round(math.degrees(math.asin(z / r)), 3)]


def points(pad, areas: list[dict]) -> list[list[float]]:
    """The ascent areas as points in order of distance; areas at about the same distance are one point."""
    out, cur = [], []
    for a in sorted(areas, key=lambda a: a["downrange_nm"]):
        if cur and a["downrange_nm"] - cur[0]["downrange_nm"] > max(CLUSTER_NM, CLUSTER_FRAC * cur[0]["downrange_nm"]):
            out.append(_mean_point([centre(pad, c) for c in cur]))
            cur = []
        cur.append(a)
    if cur:
        out.append(_mean_point([centre(pad, c) for c in cur]))
    return out


def route(pad, pts: list[list[float]]) -> tuple[list[list[float]], int]:
    """(the points the path runs through, how many were left out): a point the path would turn more than
    MAX_TURN_DEG at is left out (the one before the last when the kink is at the last, so the farthest area keeps
    the direction), and so is a first point off the bearing to the last by more than that."""
    pts, out = list(pts), 0
    while len(pts) >= 2:
        overall = history.bearing(pad[1], pad[0], pts[-1][1], pts[-1][0])
        prev = history.bearing(pad[1], pad[0], pts[0][1], pts[0][0])
        if _adiff(prev, overall) > MAX_TURN_DEG:
            pts.pop(0)
            out += 1
            continue
        kink = None
        for i in range(1, len(pts)):
            leg = history.bearing(pts[i - 1][1], pts[i - 1][0], pts[i][1], pts[i][0])
            if _adiff(leg, prev) > MAX_TURN_DEG:
                kink = i if i < len(pts) - 1 else i - 1
                break
            prev = leg
        if kink is None:
            break
        pts.pop(kink)
        out += 1
    return pts, out


def _cross_nm(pad, end, p) -> float:
    """How far p lies off the great circle from pad to end (NM)."""
    a, b, c = _unit(pad[1], pad[0]), _unit(end[1], end[0]), _unit(p[1], p[0])
    n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    nn = math.sqrt(sum(x * x for x in n)) or 1
    return abs(math.asin(max(-1.0, min(1.0, sum(n[i] * c[i] for i in range(3)) / nn)))) * 3440.065


def _side_nm(pad, end, p) -> float:
    """How far p lies off the great circle from pad to end (NM), left of it negative."""
    a, b, c = _unit(pad[1], pad[0]), _unit(end[1], end[0]), _unit(p[1], p[0])
    n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    nn = math.sqrt(sum(x * x for x in n)) or 1
    return math.asin(max(-1.0, min(1.0, sum(n[i] * c[i] for i in range(3)) / nn))) * 3440.065


def zigzag(pad, pts: list[list[float]]) -> bool:
    """The points before the last lie on both sides of the straight line from the pad to the last, each side by
    more than ZIGZAG_NM: no one turn explains them, so they are drop zones side by side about one line, not a
    dog-leg (Soyuz MS-27 of 8 Apr 2025 from Baikonur: 22 NM one side at 450 NM out, 40 NM the other at 729)."""
    if len(pts) < 3:
        return False
    off = [_side_nm(pad, pts[-1], p) for p in pts[:-1]]
    return min(off) < -ZIGZAG_NM and max(off) > ZIGZAG_NM


def bends(pad, pts: list[list[float]]) -> bool:
    return len(pts) >= 2 and any(_cross_nm(pad, pts[-1], p) > BEND_NM for p in pts[:-1])


def legs_nm(pad, pts: list[list[float]]) -> float:
    route = [pad] + pts
    return sum(notam.haversine_nm(route[i][1], route[i][0], route[i + 1][1], route[i + 1][0])
               for i in range(len(route) - 1))


def final_bearing(a, b) -> float:
    """The heading on arrival at b along the great circle from a."""
    return (history.bearing(b[1], b[0], a[1], a[0]) + 180) % 360
