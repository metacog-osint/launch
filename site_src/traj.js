/* Trajectory from a pad through pasted closure areas (the Paste tab; the old launch mapper's core). Pure functions,
   no DOM: tests/test_traj.py runs them in Node.

   Spherical Earth (R = 3,440.065 NM). For each area: the great-circle azimuth and distance from the pad to the
   area's centre, and the inclination a direct ascent on that azimuth gives, cos i = cos(pad latitude) * sin(azimuth)
   (the same formula as launch/history.py inclination() and the Patterns tab's bands). The azimuth to a drop zone
   stands in for the launch azimuth; Earth's rotation, a dog-leg and any yaw after staging are left out, so the
   inclination is indicative. 180 - azimuth gives the same inclination on the other branch (north-going vs
   south-going), which is the other direction a launch to that orbit could take from the same pad.

   Dog-leg test (needs two or more areas): the great circle from the pad through the farthest area's centre is the
   straight-ascent line. An area whose centre lies off that line by more than its own radius plus OFF_LINE_NM is off
   it; an area behind the pad (along-track distance below zero) is too. Either can mean a dog-leg, or that the areas
   belong to different events. */

const R_NM = 3440.065;
export const OFF_LINE_NM = 25;
const rad = (d) => (d * Math.PI) / 180, deg = (r) => (r * 180) / Math.PI;
const norm360 = (a) => ((a % 360) + 360) % 360;

export function bearing([lon1, lat1], [lon2, lat2]) {
  const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
  return norm360(deg(Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl))));
}
function angle([lon1, lat1], [lon2, lat2]) { // central angle, radians
  const p1 = rad(lat1), p2 = rad(lat2);
  return 2 * Math.asin(Math.min(1, Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(rad(lon2 - lon1) / 2) ** 2)));
}
export const distNm = (a, b) => angle(a, b) * R_NM;

export function inclination(lat, az) {
  return deg(Math.acos(Math.max(-1, Math.min(1, Math.cos(rad(lat)) * Math.sin(rad(az))))));
}
export const mirrorAzimuth = (az) => norm360(180 - az);

/* Orbit type from the implied inclination. Sun-synchronous orbits need about 96-102 deg (about 96.3 deg at 200 km
   to about 102 deg at 1,500 km), so a retrograde inclination there is named as in that range, not as an SSO. */
export function orbitType(i) {
  if (i < 10) return "Near-equatorial";
  if (i < 85) return "Prograde";
  if (i <= 95) return "Near-polar";
  if (i >= 96 && i <= 102) return "Retrograde, sun-synchronous range";
  return "Retrograde";
}

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
export const compass = (az) => COMPASS[Math.round(norm360(az) / 22.5) % 16];

/* An area's centre (the mean of its distinct vertices on the sphere) and radius (centre to farthest vertex, NM). */
export function areaCentre(ring) {
  const pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  let x = 0, y = 0, z = 0;
  for (const [lon, lat] of pts) { x += Math.cos(rad(lat)) * Math.cos(rad(lon)); y += Math.cos(rad(lat)) * Math.sin(rad(lon)); z += Math.sin(rad(lat)); }
  const n = Math.hypot(x, y, z);
  const centre = n < 1e-9 ? pts[0] : [deg(Math.atan2(y, x)), deg(Math.asin(z / n))];
  return { centre, radius: Math.max(0, ...pts.map((p) => distNm(centre, p))) };
}

/* Cross-track and along-track distance (NM) of `p` from the great circle that starts at `a` and passes `b`. */
export function track(a, b, p) {
  const d13 = angle(a, p), t13 = rad(bearing(a, p)), t12 = rad(bearing(a, b));
  const xt = Math.asin(Math.max(-1, Math.min(1, Math.sin(d13) * Math.sin(t13 - t12))));
  const cosAt = Math.cos(d13) / Math.cos(xt);
  const at = Math.acos(Math.max(-1, Math.min(1, cosAt))) * Math.sign(Math.cos(t13 - t12) || 1);
  return { cross: xt * R_NM, along: at * R_NM };
}

/* pad: [lon, lat]. areas: [{label, ring} or {label, point}]. Rows come back nearest first. */
export function analyse(pad, areas) {
  const rows = areas.map((a) => {
    const { centre, radius } = a.ring ? areaCentre(a.ring) : { centre: a.point, radius: 0 };
    const az = bearing(pad, centre), nm = distNm(pad, centre), inc = inclination(pad[1], az);
    return { label: a.label, centre, radius, az, nm, inc, type: orbitType(inc), mirror: mirrorAzimuth(az) };
  }).sort((p, q) => p.nm - q.nm);
  const far = rows[rows.length - 1];
  let dogleg = { tested: false, flagged: false };
  if (rows.length >= 2 && far.nm > 1) {
    rows.forEach((r) => {
      if (r === far) { r.line = { on: true, off: 0, behind: false }; return; }
      const t = track(pad, far.centre, r.centre);
      const off = Math.max(0, Math.abs(t.cross) - r.radius);
      r.line = { on: off <= OFF_LINE_NM && t.along >= 0, off, behind: t.along < 0 };
    });
    const offs = rows.filter((r) => !r.line.on);
    dogleg = { tested: true, flagged: offs.length > 0, worst: offs.sort((p, q) => q.line.off - p.line.off)[0] || null, farthest: far };
  }
  return { rows, dogleg, path: [pad, ...rows.map((r) => r.centre)] };
}

export function nearestSites(sites, point, n = 5) {
  return sites.map((s) => ({ site: s, nm: distNm([s.lon, s.lat], point) })).sort((a, b) => a.nm - b.nm).slice(0, n);
}
