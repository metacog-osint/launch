/* "Same closures" on the History tab (history.js `near=` filter), kept apart from the page so it runs in Node
   (tests/test_same.py). A launch's notices fell in the same place as a given area when the centre of one of its
   notice areas lies within SIG_NM of that area's centre. Same numbers as launch/payloads.py's closure signature:
   from a launch, its areas nearer the pad than NEAR_PAD_NM are pad closures and say little of where it flew, so they
   are used only when it has no other; the same site is the History site filter.
   centres(r, events): [lat, lon] of each notice area on a record: charted notices (`events`, the record's charted
   events from data/history.json), stored live closures, NotamForChina, Joey0609/notams, archived FAA TFRs and NGA
   warnings, reviewed published notices and notices saved in this browser. A ring's centre is the mean of its
   vertices, as notam.centroid() in Python.
   The address carries the points as `near=lat,lon;lat,lon`, two decimals (about half a nautical mile). */

export const SIG_NM = 60;
export const NEAR_PAD_NM = 50;
export const MAX_POINTS = 24;

const R_NM = 3440.065;
const rad = (d) => (d * Math.PI) / 180;
export function nm(a, b) {
  const dLa = rad(b[0] - a[0]), dLo = rad(b[1] - a[1]);
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLo / 2) ** 2;
  return 2 * R_NM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/* A ring of [lon, lat] -> [lat, lon], the closing point left out, longitude wrapped to -180..180. */
export function centroid(ring) {
  const pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  const lon = pts.reduce((s, p) => s + p[0], 0) / pts.length, lat = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  return [lat, ((lon + 540) % 360) - 180];
}

const ok = (x) => Array.isArray(x) && x.length >= 3;
const ringsOf = (n) => (n.ring ? [n.ring] : n.rings || []);
const KEYS = ["closures", "nfc_notices", "joey_notices", "archive_notices", "published_notices", "saved_notices"];

export function centres(r, events) {
  const out = [];
  (events || []).forEach((e) => (e.areas || []).forEach((a) => {
    if (Array.isArray(a.centroid) && a.centroid.length === 2) out.push([a.centroid[1], a.centroid[0]]);
    else if (ok(a.ring)) out.push(centroid(a.ring));
  }));
  KEYS.forEach((k) => (r[k] || []).forEach((n) => ringsOf(n).filter(ok).forEach((g) => out.push(centroid(g)))));
  return out;
}

const round = (v) => Math.round(v * 100) / 100;
const key = (p) => `${round(p[0])},${round(p[1])}`;

/* The points a "same closures" view of record r searches from: its area centres beyond NEAR_PAD_NM of its pad, or
   all of them when every area is at the pad (or the pad is not known). Duplicates folded, at most MAX_POINTS. */
export function targets(r, events) {
  const cs = centres(r, events);
  const pad = Array.isArray(r.pad) ? [r.pad[1], r.pad[0]] : null;
  const far = pad ? cs.filter((c) => nm(pad, c) > NEAR_PAD_NM) : [];
  const use = far.length ? far : cs;
  const seen = new Map();
  use.forEach((c) => { const k = key(c); if (!seen.has(k)) seen.set(k, [round(c[0]), round(c[1])]); });
  return { points: [...seen.values()].slice(0, MAX_POINTS), atPad: !far.length && !!cs.length && !!pad };
}

export function write(points) { return points.map(key).join(";"); }

export function read(s) {
  if (!s) return [];
  const out = [];
  String(s).split(";").forEach((t) => {
    const m = /^\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\s*$/.exec(t);
    if (!m) return;
    const la = Number(m[1]), lo = Number(m[2]);
    if (la >= -90 && la <= 90 && lo >= -180 && lo <= 180) out.push([round(la), round(lo)]);
  });
  return out.slice(0, MAX_POINTS);
}

/* Does record r have a notice area within SIG_NM of any of the points? */
export function near(cs, points) {
  return cs.some((c) => points.some((p) => nm(c, p) <= SIG_NM));
}
