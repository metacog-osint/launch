/* The Live map's layers and filters (25 Nov 2026): which layers show, which sources' areas, which countries,
   how far ahead, one pad site or one scheduled launch, and whether time-only coincidences count. The choice lives in
   the Live tab's address (#live?show=...&src=...&cc=...&within=...&site=...&launch=...&match=place), so a view can be
   shared; only what differs from the default is written. Pure functions: app.js draws, tests/test_layers.py checks
   these in Node. The lists below the map stay complete whatever is chosen here, except that match=place leaves the
   time-only rows out of the coincidence list. */

export const SHOW = ["areas", "paths", "pads", "recent", "zones", "off"];
export const SRC = ["notam", "nga", "tfr"];
export const CC = ["us", "cn", "ru", "other"];
export const WITHIN = [0, 1, 3, 7, 14];   // days ahead; 0 is any time (an area can be announced weeks ahead)
export const MATCH = ["all", "place"];   // place: time-only coincidences left out
export const DEFAULT = Object.freeze({ show: ["areas", "paths", "pads"], src: [...SRC], cc: [...CC], within: 0,
  site: "", launch: "", match: "all" });

const BIG = { US: "us", CN: "cn", RU: "ru" };
export const group = (cc) => BIG[cc] || "other";
const list = (v, allowed) => [...new Set(String(v).split(",").map((s) => s.trim()).filter((s) => allowed.includes(s)))];
const same = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

/* The state from the part of the Live tab's address after "?". Unknown names are dropped; a list left empty by
   them falls back to the default, so a mistyped address never hides everything. "none" is an empty list on
   purpose. */
export function parse(query) {
  const p = new URLSearchParams(query || "");
  const pick = (k, allowed) => {
    if (!p.has(k)) return [...DEFAULT[k]];
    if (p.get(k) === "none") return [];
    const v = list(p.get(k), allowed);
    return v.length ? v : [...DEFAULT[k]];
  };
  const w = p.has("within") ? Number(p.get("within")) : NaN;
  return { show: pick("show", SHOW), src: pick("src", SRC), cc: pick("cc", CC), within: WITHIN.includes(w) ? w : DEFAULT.within,
    site: p.get("site") || "", launch: p.get("launch") || "", match: MATCH.includes(p.get("match")) ? p.get("match") : DEFAULT.match };
}

/* The address query for a state: "" when it is the default. Lists keep their canonical order. */
export function query(s) {
  const p = new URLSearchParams();
  const put = (k, allowed) => {
    if (same(s[k], DEFAULT[k])) return;
    p.set(k, s[k].length ? allowed.filter((x) => s[k].includes(x)).join(",") : "none");
  };
  put("show", SHOW); put("src", SRC); put("cc", CC);
  if (s.within !== DEFAULT.within) p.set("within", String(s.within));
  ["site", "launch", "match"].forEach((k) => { if (s[k] && s[k] !== DEFAULT[k]) p.set(k, s[k]); });
  return p.toString().replace(/%2C/g, ",");
}

/* A site or launch the page's data no longer has (a launch that has flown, a mistyped name) is dropped, so an old
   address never hides everything. */
export const settle = (s, sites, launches) => ({ ...s, site: sites.includes(s.site) ? s.site : "",
  launch: launches.includes(s.launch) ? s.launch : "" });

/* Coincidences the match choice keeps. */
export const matchShown = (m, s) => s.match !== "place" || m.level !== "time";

/* What a chosen site or launch narrows the map and the board to: null when neither is chosen. `launches` are the
   scheduled launches' ids (Launch Library 2); `areas` the indexes in the live areas of the closures that coincide
   with them and, for a site alone, of the areas whose launch-timing note names that site. */
export function focus(s, records, matches, areas) {
  if (!s.site && !s.launch) return null;
  const picked = (records || []).filter((r) => r.status === "upcoming" && (!s.launch || r.ll2 === s.launch) && (!s.site || r.site === s.site));
  const ids = new Set(picked.map((r) => r.ll2)), out = new Set();
  picked.forEach((r) => ((r.live || {}).closures || []).forEach((c) => { if (matchShown(c, s)) out.add(c.i); }));
  (matches || []).forEach((m) => { if (ids.has(m.launch) && m.area_i !== undefined && matchShown(m, s)) out.add(m.area_i); });
  if (!s.launch) (areas || []).forEach((a, i) => { if (a.expect && a.expect.site === s.site) out.add(i); });
  return { launches: ids, areas: out };
}

/* Which source filter an area answers to: FAA NOTAMs (NMS), FAA space-operations TFRs, or a navigational warning
   (NGA's via Cordon, or the ones Orbit reads). */
export const srcKind = (a) => (a.source === "faa-tfr" ? "tfr" : a.source === "faa-nms" ? "notam" : "nga");

/* An area's country group: the country of the first scheduled launch whose path it lies on, else the issuing state
   (a TFR is the United States'), else "other". */
export function areaGroup(a, launches) {
  if (launches && launches.length && launches[0].actor) return group(launches[0].actor);
  if (a.source === "faa-tfr") return "us";
  return group(a.state);
}

const ms = (iso) => { const t = Date.parse(iso || ""); return Number.isFinite(t) ? t : null; };
const horizon = (now, days) => (days ? ms(now) + days * 86400000 : Infinity);

/* An area shows when its layer, source and country are on and, with a horizon chosen, one of its windows is open
   before the horizon and has not closed. With "any time" every live area shows, as the map drew them before the
   filters. One with no readable window shows (the list says "see the notice"). */
export function areaShown(a, launches, s, now) {
  if (!s.show.includes("areas")) return false;
  if (a.off_live && !s.show.includes("off")) return false;
  if (!s.src.includes(srcKind(a))) return false;
  if (!s.cc.includes(areaGroup(a, launches))) return false;
  if (!s.within) return true;
  const t0 = ms(now), t1 = horizon(now, s.within), ws = (a.windows || []).filter((w) => ms(w.start) !== null && ms(w.end) !== null);
  return !ws.length || t0 === null || ws.some((w) => ms(w.start) <= t1 && ms(w.end) >= t0);
}

/* NET precisions finer than a week: the how-far-ahead choice can test these against the horizon. A coarser NET (a
   week, month, quarter or year) is a placeholder instant, so it shows only with "any time". */
const FINE = ["", "second", "minute", "hour", "morning", "afternoon", "day", "closure window"];
export const coarseNet = (precision) => !FINE.includes(String(precision || "").toLowerCase());

/* A scheduled launch shows when its country is on and its NET is before the horizon. A NET already passed (a launch
   that slipped without word) still shows, as the schedule does, until the schedule drops it. */
export function launchShown(actor, net, s, now, precision) {
  if (!s.cc.includes(group(actor))) return false;
  if (s.within && coarseNet(precision)) return false;
  const t = ms(net), t1 = horizon(now, s.within);
  return t === null || ms(now) === null || t <= t1;
}

/* Markers ({at: [lon, lat], ...}) in groups: each joins the first group holding a marker within `km` of it. */
export function stacks(marks, km) {
  const rad = Math.PI / 180, near = (a, b) => {
    const dl = (b[1] - a[1]) * rad, dn = (b[0] - a[0]) * rad;
    const h = Math.sin(dl / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dn / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h))) <= km;
  };
  const out = [];
  marks.forEach((m) => { const g = out.find((s) => s.some((x) => near(x.at, m.at))); if (g) g.push(m); else out.push([m]); });
  return out;
}

/* A launch of the past seven days shows on the map when that layer and its country are on. */
export const recentShown = (r, s) => s.show.includes("recent") && s.cc.includes(group(r.actor))
  && !s.launch && (!s.site || r.site === s.site);

/* "Showing 12 of 65 areas and 4 of 10 scheduled launches" for the line under the controls. */
export function summary(nAreas, ofAreas, nLaunches, ofLaunches) {
  const pl = (n, w) => `${n} ${w}${n === 1 ? "" : w.endsWith("h") ? "es" : "s"}`;
  return `Showing ${nAreas} of ${pl(ofAreas, "area")} and ${nLaunches} of ${pl(ofLaunches, "scheduled launch")} on the map.`;
}
