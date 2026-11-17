/* Notices pasted on the Paste tab and saved in this browser, and how the History tab joins them to its launches.
   Nothing leaves the browser: the page has no server, so a saved notice lives in this browser's storage only
   (localStorage "launch.saved"; a private window or cleared site data loses it). The Paste tab can export the saved
   notices to a JSON file and import one back. Pure functions apart from load() and store(); tested in Node
   (tests/test_saved.py).

   Join, first that applies (the rules of Joey0609/notams and the archived notices in catalog.py):
   1. by NOTAM: a launch already holding a notice with the same number and a shared FIR;
   2. by window and place: a launched record (not a missile fired in combat) whose time lies inside the notice's
      window, TOL_H either side, with its pad within MAX_NM of the notice's nearest area; the nearest pad, then the
      nearest time; a window over WIDE_DAYS joins only when one launch qualifies;
   3. else the notice is its own record, status "notice": a notice with no identified launch. */
import * as N from "./notam.js";
import { distNm, areaCentre } from "./traj.js";

export const KEY = "launch.saved";
export const TOL_H = 2, MAX_NM = 5000, WIDE_DAYS = 7, LIMIT = 500;
const H = 3600e3;

export function load(storage) {
  try { const v = JSON.parse((storage || localStorage).getItem(KEY) || "[]"); return Array.isArray(v) ? v.filter(ok) : []; } catch { return []; }
}
export function store(list, storage) {
  try { (storage || localStorage).setItem(KEY, JSON.stringify(list.slice(-LIMIT))); return true; } catch { return false; }
}
const ok = (x) => x && typeof x.text === "string" && x.text.length < 20000 && typeof x.id === "string";

/* A stable id for a notice's text (whitespace ignored). */
export function idOf(text) {
  const t = N.clean(text).replace(/\s+/g, " ").trim();
  let h = 2166136261;
  for (let i = 0; i < t.length; i++) h = Math.imul(h ^ t.charCodeAt(i), 16777619);
  return "saved:" + (h >>> 0).toString(36);
}
export function entry(text, now) {
  return { id: idOf(text), text: N.clean(text).trim(), saved: now || new Date().toISOString().slice(0, 19) + "Z" };
}
/* Add entries, newest last, without duplicates; returns the new list. */
export function add(list, entries) {
  const have = new Set(list.map((x) => x.id));
  return list.concat(entries.filter((e) => ok(e) && !have.has(e.id) && have.add(e.id)));
}
/* Read an exported file: a list of entries, or {saved: [...]}. Entries are re-keyed from their text. */
export function fromFile(json) {
  const v = typeof json === "string" ? JSON.parse(json) : json;
  const xs = Array.isArray(v) ? v : (v && v.saved) || [];
  return xs.filter((x) => x && typeof x.text === "string" && x.text.length < 20000).map((x) => ({ ...entry(x.text, x.saved), saved: x.saved || entry(x.text).saved }));
}
export const toFile = (list) => JSON.stringify({ format: "launch-saved-notices/1", note: "Notices saved on Launch's Paste tab (launch.theintelligence.company).", saved: list }, null, 1);

const iso = (s) => (s && s !== "PERM" ? s.replace(" (estimated)", "") : null);
/* A saved entry read for the page: the parser's fields, its areas and points. */
export function read(e) {
  let n;
  try { n = N.parse(e.text); } catch { return null; }
  const rings = n.shapes.filter((s) => s.ring && s.ring.length >= 3).map((s) => s.ring);
  const points = n.shapes.filter((s) => s.point).map((s) => s.point);
  const firs = [...new Set([n.q && n.q.fir, ...(n.locations || [])].filter((f) => f && /^[A-Z]{4}$/.test(f)))];
  return { id: e.id, saved: e.saved, text: n.text, number: n.number || null, type: n.type || null, fir: (n.q && n.q.fir) || firs[0] || null,
    firs, q_code: n.q ? n.q.code : null, start: iso(n.start), end: iso(n.end), estimated: /estimated/.test(n.end || ""),
    lower: n.lower, upper: n.upper, schedule: n.schedule, rings, points };
}

function targets(x) {
  return x.rings.map((r) => areaCentre(r)).concat(x.points.map((p) => ({ centre: p, radius: 0 })));
}
/* Join read notices to records. `numbers(r)` gives a record's notices as [{number, firs}]. Returns
   {byRecord: Map(record id -> [notice with .join]), own: [records made for notices that joined nothing]}. */
export function join(notices, records, numbers) {
  const byNum = new Map();
  records.forEach((r) => (numbers(r) || []).forEach((k) => {
    if (!k.number) return;
    if (!byNum.has(k.number)) byNum.set(k.number, []);
    byNum.get(k.number).push({ r, firs: k.firs || [] });
  }));
  const timed = records.filter((r) => r.status === "launched" && r.time && r.pad && r.kind !== "Combat launch")
    .map((r) => ({ r, t: Date.parse(r.time) })).filter((x) => Number.isFinite(x.t)).sort((a, b) => a.t - b.t);
  const byRecord = new Map(), own = [];
  const put = (r, x) => { if (!byRecord.has(r.id)) byRecord.set(r.id, []); byRecord.get(r.id).push(x); };
  notices.forEach((x) => {
    const hit = x.number && (byNum.get(x.number) || []).find((h) => !x.firs.length || !h.firs.length || h.firs.some((f) => x.firs.includes(f)));
    if (hit) { put(hit.r, { ...x, join: { by: "notam" } }); return; }
    const s = Date.parse(x.start), e = Date.parse(x.end), ts = targets(x);
    if (Number.isFinite(s) && Number.isFinite(e) && e >= s && ts.length) {
      const c = timed.filter((y) => y.t >= s - TOL_H * H && y.t <= e + TOL_H * H)
        .map((y) => ({ ...y, nm: Math.min(...ts.map((a) => Math.max(0, distNm(y.r.pad, a.centre) - a.radius))) }))
        .filter((y) => y.nm <= MAX_NM)
        .sort((a, b) => a.nm - b.nm || Math.abs(a.t - s) - Math.abs(b.t - s));
      if (c.length && (e - s <= WIDE_DAYS * 24 * H || c.length === 1)) {
        put(c[0].r, { ...x, join: { by: "window", after_start_h: Math.round((c[0].t - s) / H * 10) / 10, nm: Math.round(c[0].nm), candidates: c.length } });
        return;
      }
    }
    own.push(record(x));
  });
  return { byRecord, own };
}
/* A notice that joined no launch, as a record of its own. */
export function record(x) {
  const pts = x.rings.flat().concat(x.points);
  const pad = x.points[0] || (x.rings[0] ? areaCentre(x.rings[0]).centre : null);
  return { id: x.id, status: "notice", time: x.start, time_basis: "notice window", label: [x.number || "Saved notice", x.fir].filter(Boolean).join(" · "),
    vehicle: "Not known", payload: null, programmes: [], mtype: "Not classified", orbit: "Not known", kind: "Not known",
    actor: null, site: null, pad: pts.length ? pad : null, pad_basis: "area", areas: 0, sources: ["saved"],
    saved_notices: [{ ...x, join: null }], cancelled: false };
}
