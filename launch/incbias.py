"""The inclination a live launch's closure areas imply, calibrated on the site's own history.

history.inclination() reads an inclination from the bearing between the pad and an area's centre (cos i =
cos(lat) sin(az)): no Earth rotation, no dog-leg, no curve of the track. Against GCAT that runs off by a few degrees,
and by a different amount at each site and on each bearing: the bearing to Xichang's areas for its 35-degree
LM-2C and LM-2D launches reads about 31.5, Jiuquan's sun-synchronous launches about 3 high, Taiyuan's about right.
A fit of the rotating-earth ground track (live.ground_track) through the areas did no better overall (measured on
24 Nov 2026 over 450 low-orbit launches in the History list with areas and a GCAT inclination: median error -0.5,
mean absolute 4.7 degrees, against +1.7 and 4.6 for the bearing; better at Jiuquan, worse at Taiyuan, Mahia and
Vandenberg, no help at Xichang): real ascents do not fly a circular orbit from liftoff.

So the bearing's reading is corrected by its own error on past launches: of the launches from the same site
(within SITE_NM) whose farthest closure area lay within AZ_WIN of this bearing, the K nearest in bearing, MIN_N or
more of them, give the median of (reading - GCAT inclination), and that is taken off. Measured leave-one-out on the
519 samples: median error +1.9 -> 0.0, mean absolute 3.5 -> 1.8 degrees, 449 corrected (all within 5 degrees, not
the nearest 5: 2.2). Fewer than MIN_N: the bearing's reading stands, and the basis says so.

The samples (`samples()`, from the built History list) are low-orbit launches only (LEO, sun-synchronous or polar,
space station): a GTO or deep-space payload's inclination is its final orbit's, not the launch's. The bearing is
the published path's own (catalog.infer_path): to its farthest closure area, or to the last point of a dog-leg
drawn through its areas; a path set by the inclination itself is not a sample. History, not a forecast; an area
is never said to be for a launch.
"""
from __future__ import annotations

from statistics import median

from . import history, notam

AZ_WIN = 5.0         # degrees either side of the live bearing that a past launch's bearing may lie
K = 5                # the past launches nearest in bearing that set the correction
MIN_N = 3            # past launches on that bearing before the reading is corrected
SITE_NM = 30         # a past launch's pad this near the live pad counts as the same site
ORBITS = ("LEO", "SSO / polar", "Space station")
AREA_BASES = ("bearing from the pad to its farthest closure area", "through its closure areas")


def _adiff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def sample(rec: dict) -> list | None:
    """[lon, lat, bearing, GCAT inclination] for a launched low-orbit record whose path runs through its own
    closure areas, else None."""
    p, pad, inc = rec.get("path") or {}, rec.get("pad"), rec.get("inc")
    if rec.get("kind") != "Orbital" or rec.get("orbit") not in ORBITS or not pad or not inc or inc <= 0:
        return None
    basis = p.get("basis") or ""
    if not basis.startswith(AREA_BASES) or "suborbital" in basis:
        return None
    via = p.get("via")
    if via:
        az = history.bearing(pad[1], pad[0], via[-1][1], via[-1][0])
    elif basis.startswith(AREA_BASES[0]) and p.get("az") is not None and ", then on" not in basis:
        az = p["az"]
    else:
        return None
    return [round(pad[0], 4), round(pad[1], 4), round(az, 1), round(inc, 2)]


def samples(records: list[dict]) -> list[list]:
    return sorted(s for s in (sample(r) for r in records) if s)


def implied(lat: float, lon: float, az: float, table: list[list] | None) -> tuple[float, int]:
    """(inclination, n): the bearing's reading less the median error of the n past launches on that bearing from
    this site; n = 0 when fewer than MIN_N, and the reading stands."""
    raw = history.inclination(lat, az)
    near = sorted((_adiff(az, s[2]), s) for s in table or []
                  if _adiff(az, s[2]) <= AZ_WIN and notam.haversine_nm(lat, lon, s[1], s[0]) <= SITE_NM)
    errs = [history.inclination(s[1], s[2]) - s[3] for _, s in near[:K]]
    if len(errs) < MIN_N:
        return raw, 0
    est = raw - median(errs)
    return round(min(180.0, max(0.0, est)), 1), len(errs)


def basis(n: int) -> str:
    if not n:
        return ("the bearing from the pad to the area (too few past launches from this site on that bearing to "
                "correct it)")
    return (f"the bearing from the pad to the area, corrected by the median error of the {n} past launches from this "
            f"site nearest that bearing (within {AZ_WIN:g} degrees; GCAT inclinations)")

