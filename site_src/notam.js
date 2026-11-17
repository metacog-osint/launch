// Paste-and-map: the browser copy of Launch's NOTAM parser (launch/notam.py). Same rules: shapes from the E) text
// (polygons, circles), the Q-line circle only when the text has none (marked approximate), unreadable coordinates
// listed and never guessed. Nothing pasted leaves the page.
const SUBJECT = { RA: "airspace reservation", RD: "danger area", RM: "military operating area", RP: "prohibited area",
  RR: "restricted area", RT: "temporary restricted area", WE: "exercises", WM: "missile, gun or rocket firing",
  WP: "parachute jumping exercise", WU: "unmanned aircraft", WL: "ascent of free balloon" };
const CONDITION = { CA: "activated", CD: "deactivated", CH: "changed", LW: "will take place", XX: "plain language" };
const HEADER = /\b([A-Z])(\d{4})\/(\d{2})\s*NOTAM([NRC])(?:\s+([A-Z])(\d{4})\/(\d{2}))?/;
const QLINE = /Q\)\s*([A-Z]{4})\s*\/\s*Q([A-Z]{2})([A-Z]{2})\s*\/\s*([A-Z ]{1,3}?)\s*\/\s*([A-Z ]{1,4}?)\s*\/\s*([A-Z ]{1,3}?)\s*\/\s*(\d{3})\s*\/\s*(\d{3})\s*\/\s*(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})?/;
const SEP = "[\\s,/]*";
const FORMS = [
  ["prefix", new RegExp("(?<![A-Z0-9])([NS])\\s?(\\d{4}|\\d{6})(\\.\\d+)?" + SEP + "([EW])\\s?(\\d{5}|\\d{7})(\\.\\d+)?(?![0-9])", "g")],
  ["suffix", new RegExp("(?<![0-9.])(\\d{4}|\\d{6})(\\.\\d+)?\\s?([NS])" + SEP + "(\\d{5}|\\d{7})(\\.\\d+)?\\s?([EW])(?![A-Z0-9])", "g")],
  ["dash", new RegExp("(?<![0-9])(\\d{1,2})-(\\d{2}(?:\\.\\d+)?)\\s?([NS])" + SEP + "(\\d{1,3})-(\\d{2}(?:\\.\\d+)?)\\s?([EW])", "g")],
  ["spaced", new RegExp("(?<![0-9])(\\d{1,2})\\s(\\d{2})(?:\\s(\\d{2}(?:\\.\\d+)?))?\\s?([NS])" + SEP + "(\\d{1,3})\\s(\\d{2})(?:\\s(\\d{2}(?:\\.\\d+)?))?\\s?([EW])(?![A-Z0-9])", "g")],
];
const MALFORMED = /(?<![0-9.])(\d{5}|\d{7,8})(?:\.\d+)?\s?([NS])\b/g;
const CIRCLE = /(?:RADIUS(?: OF)?|WI(?:THIN)?(?: A)?(?: RADIUS(?: OF)?)?)\s*(\d+(?:\.\d+)?)\s*(NM|KM)\b/g;

export function clean(t) {
  return (t || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, " ").replace(/[‘’]/g, "'")
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, " ").replace(/\r\n?/g, "\n").toUpperCase();
}
function dms(d, m, s, h, lat) {
  d = +d; m = +m; s = s ? +s : 0;
  if (m >= 60 || s >= 60) return null;
  const v = d + m / 60 + s / 3600;
  if (lat ? v > 90 : v > 180) return null;
  return Math.round((h === "S" || h === "W" ? -v : v) * 1e6) / 1e6;
}
function packed(digits, frac, h, lat) {
  const n = lat ? 2 : 3, deg = digits.slice(0, n), min = digits.slice(n, n + 2), sec = digits.slice(n + 2);
  return sec ? dms(deg, min, sec + (frac || ""), h, lat) : dms(deg, min + (frac || ""), null, h, lat);
}
export function coords(text) {
  const found = [], taken = [], rejected = [];
  const overlaps = (s, e) => taken.some(([a, b]) => s < b && a < e);
  for (const [form, rx] of FORMS) {
    rx.lastIndex = 0;
    for (const m of text.matchAll(rx)) {
      const s = m.index, e = s + m[0].length;
      if (overlaps(s, e)) continue;
      let lat, lon;
      if (form === "prefix") { lat = packed(m[2], m[3], m[1], true); lon = packed(m[5], m[6], m[4], false); }
      else if (form === "suffix") { lat = packed(m[1], m[2], m[3], true); lon = packed(m[4], m[5], m[6], false); }
      else if (form === "dash") { lat = dms(m[1], m[2], null, m[3], true); lon = dms(m[4], m[5], null, m[6], false); }
      else { lat = dms(m[1], m[2], m[3], m[4], true); lon = dms(m[5], m[6], m[7], m[8], false); }
      taken.push([s, e]);
      if (lat === null || lon === null) { rejected.push({ token: m[0].trim(), reason: "out of range" }); continue; }
      found.push({ lat, lon, start: s, end: e, form });
    }
  }
  for (const m of text.matchAll(MALFORMED)) {
    const s = m.index, e = s + m[0].length;
    if (!overlaps(s, e)) { rejected.push({ token: m[0].trim(), reason: "digit count fits no coordinate form" }); taken.push([s, e]); }
  }
  return { pts: found.sort((a, b) => a.start - b.start), rejected };
}
function gapBreaks(gap) {
  let g = gap.replace(/\b(TO|AND|THEN|BACK TO (THE )?START(ING POINT)?|TO BEGINNING|TO START|POINT|PSN|THENCE)\b/g, " ");
  g = g.replace(/\b[A-Z]\b\.?|\b\d{1,2}\./g, " ");
  return g.replace(/[^A-Z]/g, "").length > 12;
}
export function circleRing(lat, lon, nm, n = 64) {
  const r = (nm * 1.852) / 6371.0088, la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180, ring = [];
  for (let i = 0; i <= n; i++) {
    const b = (2 * Math.PI * (i % n)) / n;
    const la2 = Math.asin(Math.sin(la) * Math.cos(r) + Math.cos(la) * Math.sin(r) * Math.cos(b));
    const lo2 = lo + Math.atan2(Math.sin(b) * Math.sin(r) * Math.cos(la), Math.cos(r) - Math.sin(la) * Math.sin(la2));
    ring.push([(((lo2 * 180) / Math.PI + 540) % 360) - 180, (la2 * 180) / Math.PI]);
  }
  return unwrap(ring);
}
export function unwrap(ring) {
  const out = [ring[0].slice()];
  for (let i = 1; i < ring.length; i++) {
    let [lon, lat] = ring[i];
    const prev = out[out.length - 1][0];
    while (lon - prev > 180) lon -= 360;
    while (lon - prev < -180) lon += 360;
    out.push([lon, lat]);
  }
  return out;
}
function shapes(text) {
  const { pts, rejected } = coords(text);
  const out = [], used = new Set();
  for (const m of text.matchAll(CIRCLE)) {
    const nm = +m[1] / (m[2] === "KM" ? 1.852 : 1), end = m.index + m[0].length;
    const c = pts.find((p) => p.start - end >= 0 && p.start - end <= 40) || [...pts].reverse().find((p) => m.index - p.end >= 0 && m.index - p.end <= 6);
    if (!c) continue;
    used.add(c);
    out.push({ kind: "circle", ring: circleRing(c.lat, c.lon, nm), derived: `text circle, ${Math.round(nm * 10) / 10} NM` });
  }
  const runs = [];
  let run = [];
  for (const p of pts) {
    if (used.has(p)) continue;
    if (run.length) {
      const closed = run.length >= 4 && run[0].lat === run[run.length - 1].lat && run[0].lon === run[run.length - 1].lon;
      if (closed || gapBreaks(text.slice(run[run.length - 1].end, p.start))) { runs.push(run); run = []; }
    }
    run.push(p);
  }
  if (run.length) runs.push(run);
  for (const r of runs) {
    const ring = r.map((p) => [p.lon, p.lat]);
    const distinct = new Set(ring.map((v) => v.join(","))).size;
    if (distinct >= 3) {
      if (ring[0].join() !== ring[ring.length - 1].join()) ring.push(ring[0].slice());
      out.push({ kind: "polygon", ring: unwrap(ring), derived: `text polygon, ${distinct} vertices` });
    } else if (distinct === 2) out.push({ kind: "line", line: ring, derived: "text line" });
    else out.push({ kind: "point", point: ring[0], derived: "text point" });
  }
  return { shapes: out, rejected };
}
function stamp(s) {
  const m = /^(\d{10})\s*(EST)?|^(PERM)/.exec((s || "").trim());
  if (!m) return null;
  if (m[3]) return "PERM";
  const d = m[1];
  return `20${d.slice(0, 2)}-${d.slice(2, 4)}-${d.slice(4, 6)}T${d.slice(6, 8)}:${d.slice(8, 10)}:00Z${m[2] ? " (estimated)" : ""}`;
}
function items(body) {
  const order = "ABCDEFG", out = {}, marks = [];
  let last = null;
  for (const m of body.matchAll(/(?:(?<=\s)|(?<=^)|(?<=\)))([A-G])\)\s*/g)) {
    if (last === null || order.indexOf(m[1]) > order.indexOf(last)) { marks.push(m); last = m[1]; }
  }
  marks.forEach((m, i) => { out[m[1]] = body.slice(m.index + m[0].length, i + 1 < marks.length ? marks[i + 1].index : body.length).trim(); });
  return out;
}
export function parse(raw) {
  const text = clean(raw), h = HEADER.exec(text), q = QLINE.exec(text);
  if (!h && !q) throw new Error("no NOTAM header and no Q-line");
  const out = { text: text.trim() };
  if (h) Object.assign(out, { number: `${h[1]}${h[2]}/${h[3]}`, type: { N: "new", R: "replace", C: "cancel" }[h[4]], refers_to: h[5] ? `${h[5]}${h[6]}/${h[7]}` : null });
  const body = q ? text.slice(q.index + q[0].length) : text.slice(h.index + h[0].length);
  if (q) {
    const lat = (+q[9] + +q[10] / 60) * (q[11] === "S" ? -1 : 1), lon = (+q[12] + +q[13] / 60) * (q[14] === "W" ? -1 : 1);
    out.q = { fir: q[1], code: `Q${q[2]}${q[3]}`, subject_text: SUBJECT[q[2]] || null, condition_text: CONDITION[q[3]] || null,
      lower_fl: +q[7], upper_fl: +q[8], centre: [lon, lat], radius_nm: q[15] ? +q[15] : null };
  }
  const it = items(body);
  Object.assign(out, { locations: (it.A || "").split(/\s+/).filter(Boolean), start: stamp(it.B), end: stamp(it.C),
    schedule: it.D || null, lower: it.F || null, upper: it.G || null, e_text: it.E || "" });
  const sh = shapes(out.e_text || body);
  if (!sh.shapes.some((s) => s.kind === "polygon" || s.kind === "circle") && out.q && out.q.radius_nm && out.q.radius_nm < 999) {
    sh.shapes.push({ kind: "circle", ring: circleRing(out.q.centre[1], out.q.centre[0], out.q.radius_nm),
      derived: "Q-line circle (approximate: the notice gives no coordinates for its own area)" });
  }
  out.shapes = sh.shapes;
  out.rejected = sh.rejected;
  return out;
}
export function splitMany(raw) {
  const t = clean(raw);
  return t.split(/(?=\b[A-Z]\d{4}\/\d{2}\s*NOTAM[NRC]\b)/).map((p) => p.trim()).filter((p) => HEADER.test(p) || QLINE.test(p));
}

const R_NM = 3440.065;
const rad = (d) => (d * Math.PI) / 180, deg = (r) => (r * 180) / Math.PI;

/* Great-circle lines for charted paths and closure-area rings. A charted path is stored as a few points, often
   thousands of miles apart, and Google My Maps draws each leg as a great circle; the edges between NOTAM vertices are
   great circles too. Joined straight on a Web Mercator map a long leg goes wrong: Vostochny's sun-synchronous paths
   (great-circle azimuth about 352 deg, north over the pole) would head west-south-west across Eurasia, a leg over the
   antimeridian would run the wrong way round the world, and closure-area edges strayed up to 316 NM from the great
   circle (measured 15 Nov 2026 on the 1,026 charted areas). So each leg is drawn as a great circle, a point every 25 NM,
   longitudes running on past 180 as in greatCircle() below. Near-antipodal legs (no single great circle) stay
   straight. */
export function geodesic(line) {
  const out = [];
  let prev = null;
  const push = (lon, lat) => {
    if (prev !== null) { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; }
    prev = lon;
    out.push([Math.round(lon * 1000) / 1000, Math.round(lat * 1000) / 1000]);
  };
  for (let i = 0; i < line.length - 1; i++) {
    const [lo1, la1] = line[i], [lo2, la2] = line[i + 1];
    const p1 = rad(la1), l1 = rad(lo1), p2 = rad(la2), l2 = rad(lo2);
    const d = 2 * Math.asin(Math.min(1, Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2)));
    if (i === 0) push(lo1, la1);
    const n = Math.ceil((d * R_NM) / 25);
    if (n > 1 && Math.sin(d) > 1e-6) {
      for (let k = 1; k < n; k++) {
        const a = Math.sin((1 - k / n) * d) / Math.sin(d), b = Math.sin((k / n) * d) / Math.sin(d);
        const x = a * Math.cos(p1) * Math.cos(l1) + b * Math.cos(p2) * Math.cos(l2);
        const y = a * Math.cos(p1) * Math.sin(l1) + b * Math.cos(p2) * Math.sin(l2);
        const z = a * Math.sin(p1) + b * Math.sin(p2);
        push(deg(Math.atan2(y, x)), deg(Math.atan2(z, Math.hypot(x, y))));
      }
    }
    push(lo2, la2);
  }
  return out;
}

/* An estimated flight path as the History map draws and the downloads export it: from the pad on `path.az` for
   `path.nm`; with `path.via` (the Cape's polar corridor), great circles from the pad to each turn point, then on
   `path.az` from the last for what is left of `path.nm`. */
export function estimatedLine(pad, path) {
  const via = path.via || [];
  if (!via.length) return greatCircle(pad[0], pad[1], path.az, path.nm);
  const pts = [pad, ...via];
  let done = 0;
  for (let i = 1; i < pts.length; i++) done += gcNm(pts[i - 1], pts[i]);
  const legs = geodesic(pts);
  const last = legs[legs.length - 1];
  const rest = greatCircle(last[0], last[1], path.az, Math.max(path.nm - done, 0)).slice(1);
  return legs.concat(rest);
}

function gcNm(a, b) {
  const p1 = rad(a[1]), p2 = rad(b[1]), dl = rad(b[0] - a[0]);
  const c = Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(dl);
  return Math.acos(Math.max(-1, Math.min(1, c))) * R_NM;
}

/* A great circle from (lon, lat) on azimuth `az` for `nm` nautical miles, a point every 25 NM (the History tab's
   estimated flight paths, drawn and exported). Longitudes run on past 180 so a path that crosses the antimeridian
   stays one line. */
export function greatCircle(lon, lat, az, nm) {
  const out = [];
  const p1 = rad(lat), l1 = rad(lon), th = rad(az);
  let prev = lon;
  for (let d = 0; d <= nm + 1e-6; d += Math.min(25, nm - d || 25)) {
    const dl = d / R_NM;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(dl) + Math.cos(p1) * Math.sin(dl) * Math.cos(th));
    const l2 = l1 + Math.atan2(Math.sin(th) * Math.sin(dl) * Math.cos(p1), Math.cos(dl) - Math.sin(p1) * Math.sin(p2));
    let x = deg(l2);
    while (x - prev > 180) x -= 360;
    while (x - prev < -180) x += 360;
    prev = x;
    out.push([Math.round(x * 1000) / 1000, Math.round(deg(p2) * 1000) / 1000]);
    if (d >= nm) break;
  }
  return out;
}
