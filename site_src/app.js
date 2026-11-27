/* Launch page: reads data/snapshot.json, data/history.json, data/launches.json, data/patterns.json and
   data/sources.json and draws them, one tab at a time (#live, #history, #patterns, #paste, #sources; the History
   tab is history.js). Times are stored UTC and shown in the viewer's zone through tic-time.js. No inline scripts (CSP). */
import { createMap } from "./map.js";
import * as N from "./notam.js";
import * as TR from "./traj.js";
import { initHistory } from "./history.js";
import * as SV from "./saved.js";
import * as LP from "./livepaths.js";
import * as LY from "./layers.js";
import * as BD from "./board.js";
import * as SM from "./same.js";

const T = window.TicTime;
const $ = (id) => document.getElementById(id);
const BIG = { US: "us", CN: "cn", RU: "ru" };
let REGION = null;
try { REGION = new Intl.DisplayNames(["en"], { type: "region" }); } catch { REGION = null; }
const countryName = (cc) => { try { return (REGION && REGION.of(cc)) || cc; } catch { return cc; } };
const group = (cc) => BIG[cc] || "other";

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
const fmt = (iso, o) => (!iso ? "" : T ? T.format(iso, o || {}) : iso.replace("T", " ").replace(":00Z", "Z"));
// A NET worded by its precision (board.js netWords): a clock time only when the schedule gives one.
const netText = (iso, precision) => BD.netWords(iso, precision, fmt);
// A window "start to end": the end's date is left off only when it falls on the start's day in the viewer's zone, so
// a window over midnight or over several days does not read as ending before it opens.
const span = (a, b) => fmt(a) + " to " + fmt(b, fmt(a, { time: false }) === fmt(b, { time: false }) ? { date: false } : {});
function mark(cc) {
  const s = el("span", "cc g-" + group(cc));
  if (!cc) { s.textContent = "?"; s.title = "Not known"; return s; }
  s.title = countryName(cc);
  const img = document.createElement("img");
  img.src = "flags/" + cc.toLowerCase() + ".svg"; img.alt = ""; img.width = 16; img.height = 12; img.loading = "lazy";
  img.onerror = () => img.remove();
  s.append(img, document.createTextNode(cc));
  return s;
}
function table(head, rows, onRow) {
  const t = el("table"), th = el("thead"), tr = el("tr");
  head.forEach((h) => tr.appendChild(el("th", h.num ? "num" : "", h.label || h)));
  th.appendChild(tr); t.appendChild(th);
  const tb = el("tbody");
  rows.forEach((r) => {
    const row = el("tr");
    r.cells.forEach((c, i) => {
      const td = el("td", head[i] && head[i].num ? "num" : "");
      if (c instanceof Node) td.appendChild(c); else td.textContent = c === null || c === undefined ? "" : String(c);
      row.appendChild(td);
    });
    if (onRow) { row.tabIndex = 0; row.className = "pickable"; row.addEventListener("click", () => onRow(r)); row.addEventListener("keydown", (e) => { if (e.key === "Enter") onRow(r); }); }
    tb.appendChild(row);
  });
  t.appendChild(tb);
  return t;
}
const put = (box, node) => { box.textContent = ""; box.appendChild(node); };
const muted = (t) => el("p", "muted small", t);
// Orbit (orbit.theintelligence.company) holds what launches put in orbit: its launch rows cover GCAT's last 7 days;
// its object search finds every piece of a launch by its COSPAR launch id (GCAT's tag), any year.
const ORBIT = {
  site: "https://orbit.theintelligence.company/",
  launchRow: (tag) => ORBIT.site + "launches.html#launch-" + encodeURIComponent(String(tag).replace(/ /g, "-")),
  objects: (tag) => ORBIT.site + "?q=" + encodeURIComponent(tag) + "#obj-search",
};
// Long tables fold with the hub's tic-fold.js at every width: the first 10 rows on a phone and 15 wider (each table
// lists the soonest or largest first), then "Show all"; a find box over 25 or more. It re-applies when a table is
// redrawn. The History tab's list has its own paging and is left.
const folds = (panel) => $(panel).querySelectorAll(".tbl-wrap > table").forEach((t) => {
  t.setAttribute("data-tic-fold", "");
  t.setAttribute("data-tic-fold-find", "");
});
const poly = (ring, props) => ({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [N.geodesic(ring)] } }); // edges as great circles

async function getJSON(p) { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }

let snap, hist, pat, srcs, ix, map, H = null, Hstart = null, liveM = null, openCard = null, sched = [];
const byKey = new Map();
const upcomingRecs = () => ix.records.filter((r) => r.status === "upcoming");
// Scheduled launches Launch Library 2 lists, from Launch's own schedule (snap.schedule.records), in the shape Orbit's
// `upcoming` lane had: `id` is the LL2 uuid. The same rows tools/launch.py ll2_upcoming() matches against the areas.
// (Orbit no longer publishes `upcoming`, so snap.orbit.upcoming is now always empty.)
const upcomingRows = () => ((snap.schedule || {}).records || []).filter((r) => (r.refs || {}).ll2 && (r.listed_by || ["ll2"]).includes("ll2")).map((r) => ({ ...r, id: r.refs.ll2, ll2_url: (r.links || {}).ll2 }));
const scheduled = (r) => upcomingRows().find((u) => u.id === r.ll2) || null;

function tiles() {
  const box = $("tiles"); box.textContent = "";
  const lv = {};   // one per launch and notice, as the list and the feed count them
  LP.groupMatches(snap.matches || [], snap.areas || []).forEach((m) => { lv[m.level] = (lv[m.level] || 0) + 1; });
  const items = [
    ["Live closure areas (NGA warnings, NOTAMs, TFRs; Orbit counts warnings)", (snap.areas || []).filter((a) => !a.off_live).length],
    ["FAA space-operations TFRs", (snap.tfr || []).length],
    ["Scheduled launches, 14 days", upcomingRows().length],
    ["Coincidences: time / time and place / grouped", `${lv.time || 0} / ${lv["time and place"] || 0} / ${lv.grouped || 0}`],
    [`Launches since ${(ix.ledger_since || "2012").slice(0, 4)}`, ix.records.filter((r) => r.status === "launched" && (r.time || "") >= (ix.ledger_since || "2012")).length],
    ["Recurring drop zones", pat.recurring.length],
  ];
  items.forEach(([k, v]) => { const t = el("div", "tile"); t.append(el("span", "k", k), el("span", "v", String(v))); box.appendChild(t); });
  $("asof").textContent = "Live areas read " + fmt(snap.generated_at) + ".";
  // Today's reading (tic-shell): this run's counts. A closure announces intent, so a coincidence is only that.
  const num = (v) => el("b", "", String(v));
  const areas = (snap.areas || []).filter((a) => !a.off_live).length, tfr = (snap.tfr || []).length, up = upcomingRows().length, both = lv["time and place"] || 0;
  $("reading").replaceChildren(el("span", "tic-reading-k", "Today\u2019s reading"),
    num(areas), ` live closure area${areas === 1 ? "" : "s"}, `, num(tfr), ` FAA space-operations TFR${tfr === 1 ? "" : "s"} and `,
    num(up), ` launch${up === 1 ? "" : "es"} scheduled in the next 14 days. `, num(both),
    ` coincidence${both === 1 ? "" : "s"} between a scheduled launch and a closure, in both time and place.`);
}

// NOTAMs whose text says they are not a launch (nms.off_live: exercises, airdrops, missile firings...) are areas with
// `off_live`. They match no launch, and the map and the area list leave them out until the viewer turns them on
// ("off" in the layer choice). The layer choice (layers.js) decides what else the map draws; the lists stay complete.
let lay = LY.parse("");
const showOff = () => lay.show.includes("off");
const nowIso = () => new Date().toISOString();
const STACK_KM = 5;
function liveModel() {
  const now = nowIso(), fc = () => ({ type: "FeatureCollection", features: [] });
  const live = fc(), paths = fc(), pads = fc(), recent = fc(), marks = [];
  const tied = LP.tiedAreas(upcomingRecs());
  const only = LY.focus(lay, upcomingRecs(), snap.matches, snap.areas), picked = (id) => !only || only.launches.has(id);
  let areasAll = 0;
  (snap.areas || []).forEach((a, i) => {
    const key = "live:" + (a.key || a.id) + ":" + i;
    const on = tied.get(i) || [];
    byKey.set(key, { kind: "live", a, launches: on });
    if (!a.off_live || showOff()) areasAll += 1;
    if (!LY.areaShown(a, on, lay, now) || (only && !only.areas.has(i))) return;
    live.features.push(poly(a.ring, { key, tied: on.length ? 1 : 0, group: on.length ? group(on[0].actor) : a.source === "faa-tfr" ? "us" : "other" }));
  });
  LP.livePathRecords(upcomingRecs()).forEach((r) => {
    const key = "path:" + r.id;
    byKey.set(key, { kind: "launch", r });
    if (!lay.show.includes("paths") || !picked(r.ll2) || !LY.launchShown(r.actor, r.time, lay, now, r.net_precision)) return;
    paths.features.push({ type: "Feature", properties: { key, group: group(r.actor) }, geometry: { type: "LineString", coordinates: N.estimatedLine(r.pad, r.path) } });
  });
  const ups = upcomingRows();
  let launchesShown = 0;
  ups.forEach((u) => {
    const r = upcomingRecs().find((x) => x.ll2 === u.id) || null, cc = (r && r.actor) || (u.provider_countries || [])[0];
    const shown = picked(u.id) && LY.launchShown(cc, u.net, lay, now, u.net_precision);
    if (shown) launchesShown += 1;
    if (u.lat === null || u.lat === undefined) return;
    const key = "pad:" + u.id;
    byKey.set(key, { kind: "pad", u, r });
    if (!lay.show.includes("pads") || !shown) return;
    marks.push({ key, kind: "pad", group: group(cc), at: [u.lon, u.lat] });
  });
  LP.pastWeek(ix.records, snap.generated_at).forEach((r) => {
    if (!Array.isArray(r.pad)) return;
    const key = "recent:" + r.id;
    byKey.set(key, { kind: "recent", r });
    if (!LY.recentShown(r, lay)) return;
    marks.push({ key, kind: "recent", group: group(r.actor), at: r.pad });
  });
  // Markers within STACK_KM of each other (two launches from one pad, or a past-week launch from a scheduled pad)
  // are drawn as one, so none hides another: a ring when one is scheduled, with a dot inside when one has launched,
  // and the card lists each.
  LY.stacks(marks, STACK_KM).forEach((s, n) => {
    const pad = s.find((m) => m.kind === "pad"), first = pad || s[0];
    let key = first.key;
    if (s.length > 1) { key = "stack:" + n; byKey.set(key, { kind: "stack", keys: s.map((m) => m.key) }); }
    const f = { type: "Feature", properties: { key, group: first.group, recent: s.some((m) => m.kind === "recent") ? 1 : 0 }, geometry: { type: "Point", coordinates: first.at } };
    (pad ? pads : recent).features.push(f);
  });
  return { live, paths, pads, recent, counts: [live.features.length, areasAll, launchesShown, ups.length] };
}

const SRC_LABEL = { "faa-tfr": "FAA TFR", "faa-nms": "NOTAM (FAA NMS-API)", "cordon-navwarn": "NGA navigational warning (via Cordon)" };
const srcLabel = (a) => SRC_LABEL[a.source] || "Navigational warning (via Orbit)";
const KEPT = { words: "launch words in the text", "cn-area": "China's surface-to-unlimited danger area, short window",
  "unl-area": "surface-to-unlimited area, short window", "recurring-area": "near a closure area in Launch's history" };
// "If a launch from <site>, around <time>": the site's median minutes from closure opening to launch (history/timing.json).
const expectText = (x) => x ? `if a launch from ${x.site}, around ${fmt(x.at, { date: false })} (median ${x.median_min} min after opening, ${x.launches} launches; middle half ${x.q1_min}-${x.q3_min} min)` : "";

// Far time-only coincidences (LP.groupMatches `far`) fold away until the viewer asks for them.
let showFar = false;
const range = (lo, hi, f = (x) => x) => (lo === hi ? f(lo) : `${f(lo)}-${f(hi)}`);
function liveTables() {
  const matches = snap.matches || [];
  const all = LP.groupMatches(matches.filter((m) => LY.matchShown(m, lay)), snap.areas || []);
  const timeOnly = LP.groupMatches(matches, snap.areas || []).length - all.length;
  const farN = all.filter((m) => m.far).length, ms = all.filter((m) => showFar || !m.far);
  const recOf = new Map(upcomingRecs().map((r) => [r.ll2, r]));
  const onPath = (m) => ((recOf.get(m.launch) || {}).live || { closures: [] }).closures.some((c) => m.area_is.includes(c.i) && c.role === "path");
  const lvlBadge = (m) => {
    const s = el("span", "lvl");
    s.append(el("span", "badge" + (m.level === "time" ? "" : " badge-warn"), m.level));
    if (m.named) { const n = el("span", "badge badge-warn", "names it"); n.title = `The notice's text has "${m.named}"`; s.append(n); }
    if (onPath(m)) s.append(el("span", "badge badge-path", "on path"));
    return s;
  };
  put($("match-table"), ms.length ? table(
    ["Scheduled launch", "NET", "Area", "Window (UTC shown in your zone)", "Level", { label: "Az / NM", num: true }, "Why"],
    ms.map((m) => ({ m, cells: [m.launch_name, fmt(m.net), m.area + (m.parts.length ? ` (areas ${m.parts.join(", ")})` : ""),
      span(m.window[0], m.window[1]), lvlBadge(m), `${range(m.az[0], m.az[1], (x) => x + "°")} / ${range(m.nm[0], m.nm[1])}`,
      (m.level === "grouped" ? "GCAT launch " + m.grouped_with.launch_tag : m.place_basis)
        + (m.also.length ? `; the same notice also coincides in time and place with ${m.also.join(", ")}` : "")] })),
    (row) => {
      const rec = recOf.get(row.m.launch);
      if (rec) { // with no path, the card says why each closure is not on one, and the map shows the row's area
        launchCard(rec);
        const a = (snap.areas || [])[row.m.area_i];
        if (!LP.hasLivePath(rec) && a) map.fit({ type: "FeatureCollection", features: [poly(a.ring, {})] });
        return;
      }
      const k = row.m.area_i !== undefined ? `live:${row.m.area}:${row.m.area_i}` : [...byKey.keys()].find((x) => x.startsWith("live:" + row.m.area + ":"));
      if (k) pickLive(k);
    }) : muted(timeOnly ? "No scheduled launch coincides with a live closure area in time and place or grouped."
    : "No scheduled launch coincides with a live closure area."));
  if (timeOnly) $("match-table").append(muted(`${timeOnly} time-only coincidence${timeOnly === 1 ? " is" : "s are"} left out by "Hide time-only coincidences" under the map's layers and filters.`));
  if (farN) {
    const b = el("button", "linkish small", showFar ? `Fold away the ${farN} far time-only coincidence${farN === 1 ? "" : "s"}`
      : `Show ${farN} far time-only coincidence${farN === 1 ? "" : "s"}: over 1,500 NM from the pad, naming nothing and on no ground track`);
    b.type = "button";
    b.addEventListener("click", () => { showFar = !showFar; liveTables(); });
    const p = el("p", "small");
    p.append(b);
    $("match-table").append(p);
  }
  const rows = (snap.areas || []).map((a, i) => ({ a, key: "live:" + (a.key || a.id) + ":" + i, cells: [
    srcLabel(a), a.key || a.id, (a.off_live ? `Not a launch (${a.off_live}): ` : "") + (a.label || (a.regions || []).join(", ") || ""),
    ((a.windows || []).slice(0, 2).map((w) => span(w.start, w.end)).join("; ") + ((a.windows || []).length > 2 ? ` and ${(a.windows.length - 2)} more` : "") || "see the notice")
      + (a.expect ? "; " + expectText(a.expect) : "")] }));
  const off = (snap.areas || []).filter((a) => a.off_live).length, shown = rows.filter((r) => showOff() || !r.a.off_live);
  $("off-count").textContent = `(${off})`;
  put($("area-table"), shown.length ? table(["Source", "Notice", "Where", "Windows"], shown, (r) => pickLive(r.key)) : muted("No live areas."));
  if (off && !showOff()) $("area-table").append(muted(`${off} non-launch NOTAM${off === 1 ? " is" : "s are"} hidden (exercises, airdrops, missile firings and the like): turn them on with "Non-launch NOTAMs" under the map's layers and filters.`));
  unlistedTable();
  pastWeek();
  folds("live");
}

// Closure with no listing (launch/unlisted.py): a closure and a schedule that shows nothing for it, never a launch.
function unlistedTable() {
  const us = snap.unlisted || [];
  put($("unlisted-table"), us.length ? table(["Nearest site", { label: "NM", num: true }, "Window", "Notices", "Schedule"],
    us.map((u) => ({ u, cells: [u.site, u.expect.nm, fmt(u.start) + " to " + fmt(u.end, { date: false }) + (u.more_windows ? ` and ${u.more_windows} more` : ""),
      u.notices.map((n) => n.key).join(", "),
      u.maybe_listed.length ? "None in this window. Dated only roughly: " + u.maybe_listed.join(", ") : "None listed"] })),
    (r) => { const k = [...byKey.keys()].find((x) => x.startsWith("live:" + r.u.notices[0].key + ":")); if (k) pickLive(k); })
    : muted("No closure near a launch site is without a listed launch."));
}

// Launches of the seven days to the last data read, newest first, each a link to its History record.
function pastWeek() {
  const rows = LP.pastWeek(ix.records, snap.generated_at);
  const name = (r) => { const a = el("a", "", r.label || r.payload || r.id); a.href = LP.historyHref(r); return a; };
  const result = (r) => {
    const s = el("span", "", (r.outcome || r.ll2_status || "Not reported").replace(/^./, (c) => c.toUpperCase()));
    if (r.provisional) { s.append(" "); s.append(el("span", "badge", "provisional")); }
    return s;
  };
  // Payloads as GCAT lists them; what each reached, and its path, is Orbit's (its launch row, by GCAT tag).
  const payloads = (r) => {
    const p = r.payloads || {}, box = el("span", "");
    if (!LP.inOrbit(r)) return box;
    if (!p.count) { box.textContent = "Not yet cataloged"; return box; }
    box.textContent = p.names.slice(0, 3).join(", ") + (p.count > 3 ? ` and ${p.count - 3} more` : "") + " ";
    { const a = el("a", "", "On Orbit"); a.href = ORBIT.launchRow(r.gcat); a.rel = "noopener"; box.append(a); }
    return box;
  };
  put($("past-table"), rows.length ? table(["Launched", "Launch", "Site", "Country", "Orbit", "Payloads", "Outcome"],
    rows.map((r) => ({ cells: [fmt(r.time), name(r), r.site || "", mark(r.actor), r.orbit || "", payloads(r), result(r)] })))
    : muted("No launch is recorded in the past seven days."));
}

// Elsewhere today (tic-related.js from the hub): the countries of the pads with launches scheduled in the next 14
// days, strongest first: those with a launch that coincides with a live closure area, then by launches scheduled.
function related() {
  const box = $("tic-related");
  if (!box || !window.TicRelated) return;
  const up = upcomingRows();
  const matched = new Set((snap.matches || []).map((m) => m.launch));
  const score = new Map();
  up.forEach((u, i) => {
    const cc = u.pad_country || (u.provider_countries || [])[0];
    if (!cc) return;
    const s = score.get(cc) || { cc, m: 0, n: 0, i };
    s.m += matched.has(u.id) ? 1 : 0; s.n += 1;
    score.set(cc, s);
  });
  const ranked = [...score.values()].sort((a, b) => (b.m - a.m) || (b.n - a.n) || (a.i - b.i)).map((s) => s.cc);
  if (!ranked.length) return;
  const names = {};
  ranked.forEach((cc) => { names[cc] = countryName(cc); });
  window.TicRelated.render(box, { countries: ranked, here: "launch", names, level: 2 });
}

function pickLive(key) {
  const x = byKey.get(key);
  if (!x) return;
  if (x.kind === "launch" || (x.kind === "pad" && x.r)) { launchCard(x.r); return; }
  openCard = null;
  const box = $("map-info"); box.textContent = "";
  if (x.kind === "recent") {
    const r = x.r, a = el("a", "", "Open in History"); a.href = LP.historyHref(r);
    box.append(el("b", "", r.label || r.payload || r.id), document.createTextNode(` · launched ${fmt(r.time)} · ${[r.pad_name, r.site].filter(Boolean).join(", ")} · `),
      mark(r.actor), document.createTextNode(" · "), a);
    return;
  }
  if (x.kind === "stack") {
    box.append(el("b", "", `${x.keys.length} launches at this pad`));
    x.keys.forEach((k) => {
      const y = byKey.get(k); if (!y) return;
      const b = el("button", "linkish", y.kind === "recent" ? (y.r.label || y.r.payload || y.r.id) : ((y.r && y.r.label) || y.u.name)); b.type = "button";
      b.addEventListener("click", () => pickLive(k));
      box.append(el("br"), document.createTextNode(y.kind === "recent" ? `Launched ${fmt(y.r.time)}: ` : `Scheduled, NET ${netText(y.u.net, y.u.net_precision)}: `), b);
    });
    return;
  }
  if (x.kind === "pad") {
    box.append(el("b", "", x.u.name), document.createTextNode(` · NET ${netText(x.u.net, x.u.net_precision)} · ${x.u.pad || ""}, ${x.u.location || ""} · `), mark((x.u.provider_countries || [])[0]));
    return;
  }
  const a = x.a;
  box.append(el("b", "", (a.source === "faa-tfr" ? "FAA TFR " : a.source === "faa-nms" ? "NOTAM " : "") + (a.key || a.id)), document.createTextNode(" · " + (a.hazard || a.label || "") + ((a.detail || {}).activity ? " · " + a.detail.activity : "")));
  if (a.off_live) box.append(el("br"), document.createTextNode(`Not a launch notice (${a.off_live}): it matches no launch.`));
  if (a.source === "faa-nms") box.append(el("br"), document.createTextNode("Kept: " + (KEPT[a.kept] || a.kept) + (a.expect ? "; " + expectText(a.expect) : "") + ". " + ((snap.nms || {}).source_note || "")));
  (x.launches || []).forEach((r) => {
    const b = el("button", "linkish", r.label); b.type = "button";
    b.addEventListener("click", () => launchCard(r));
    box.append(el("br"), document.createTextNode("On the estimated path of "), b);
  });
  // Same closures (same.js): History's past launches with a notice area centred within SIG_NM of this one's centre.
  if (a.ring && a.ring.length >= 3) {
    const h = el("a", "", "Past launches with notices here");
    h.href = "#history?" + new URLSearchParams({ st: "launched", near: SM.write([SM.centroid(a.ring)]) }).toString();
    h.title = `Launches in History with a notice area whose centre lies within ${SM.SIG_NM} NM of this area's centre`;
    box.append(el("br"), h);
  }
  map.fit({ type: "FeatureCollection", features: [poly(a.ring, {})] });
}

/* The card for a scheduled launch: what is scheduled, how the path was estimated, and each closure that coincides. */
function launchCard(r, fit = true) {
  openCard = r;
  const box = $("map-info"), u = scheduled(r) || {}, card = el("div", "launch-card"), dl = el("dl");
  const fact = (k, v) => { if (v === null || v === undefined || v === "") return; const d = el("dd"); if (v instanceof Node) d.appendChild(v); else d.textContent = v; dl.append(el("dt", "", k), d); };
  const head = el("h3", "", r.label); head.append(" ", mark(r.actor));
  card.appendChild(head);
  fact("Vehicle", r.ll2_vehicle || r.vehicle);
  fact("Payload", r.payload);
  fact("NET", netText(r.time, r.net_precision) + (r.ll2_status ? ` · ${r.ll2_status}` : ""));
  if (u.window_start && u.window_end) fact("Window", span(u.window_start, u.window_end));
  fact("Pad", [r.pad_name, r.site].filter(Boolean).join(", "));
  const cl = (r.live || {}).closures || [];
  const sourceNames = [...new Set(cl.map((c) => SRC_LABEL[c.source] || c.source))];
  fact("Sources", ["Schedule: Launch Library 2", ...(sourceNames.length ? ["closures: " + sourceNames.join(", ")] : [])].join("; "));
  fact("Path", !LP.hasLivePath(r) ? "None drawn on this map: no live closure area lies on this launch's expected ascent."
    : `Estimated: ${r.path.via && r.path.via.length ? `through ${r.path.via.length} point${r.path.via.length === 1 ? "" : "s"}, then on ${r.path.az}°` : `azimuth ${r.path.az}°`}, drawn ${whole(r.path.nm)} NM. Basis: ${r.path.basis}.`);
  if (cl.length) {
    const ul = el("ul", "plain lc-areas");
    cl.forEach((c) => {
      const a = (snap.areas || [])[c.i];
      const li = el("li"), b = el("button", "linkish", c.area + (a && /^[A-Z]$/.test(a.label || "") ? ` area ${a.label}` : "")); b.type = "button";
      if (a) b.addEventListener("click", () => map.fit({ type: "FeatureCollection", features: [poly(a.ring, {})] }));
      const role = c.role === "path" ? "on the path" : c.role === "pad" ? "at the pad" : "not on the path: " + c.why;
      li.append(b, document.createTextNode(` · ${c.level} · ${c.azimuth}° / ${whole(c.nm)} NM · ${span(c.window[0], c.window[1])} · ${role}`));
      ul.appendChild(li);
    });
    fact("Closures", ul);
  }
  card.appendChild(dl);
  const more = el("a", "", "Open in History"); more.href = LP.historyHref(r);
  card.append(el("p", "small muted", "A closure on the path coincides with the launch in time and place. That does not show it is for this launch. "));
  card.lastChild.appendChild(more);
  box.textContent = ""; box.appendChild(card);
  if (fit && map && LP.hasLivePath(r)) {
    const onPath = cl.filter((c) => c.role === "path" && (snap.areas || [])[c.i]).map((c) => poly(snap.areas[c.i].ring, {}));
    map.fit({ type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: N.estimatedLine(r.pad, r.path) } }, ...onPath] });
  }
}

/* The upcoming-launch board (board.js): the map's country, how-far-ahead, site and launch choices apply. */
function board() {
  const now = nowIso(), only = LY.focus(lay, upcomingRecs(), snap.matches, snap.areas), all = BD.boardRows(ix.records, sched);
  const rows = all.filter((x) => (!only || only.launches.has(x.r.ll2)) && LY.launchShown(x.actor, x.net, lay, now, x.precision));
  const moved = (x) => {
    const s = el("span", "", BD.moveText(x));
    if (x.lastMove) s.append(el("br"), el("span", "muted small", BD.seenText(x.lastMove, fmt)));
    return s;
  };
  put($("board-table"), rows.length ? table(["NET", "Launch", "Country", "Site", "Status", "NET moved", "Live closures"],
    rows.map((x) => ({ x, cells: [netText(x.net, x.precision), x.r.label, mark(x.actor), x.site, x.status, moved(x), BD.closureText(x)] })),
    (row) => { launchCard(row.x.r); const c = $("map-card"); if (c.scrollIntoView) c.scrollIntoView({ block: "start" }); })
    : muted(all.length ? "No scheduled launch matches the map's filters." : "No launch is scheduled in the next 14 days."));
  if (rows.length && rows.length < all.length) $("board-table").append(muted(`${all.length - rows.length} more hidden by the map's filters.`));
}

/* Layers and filters (layers.js): the controls show `lay`; a change redraws the map and the board and rewrites the
   Live tab's address. A bare #live (the tab link) keeps the current choice. */
const siteNames = () => [...new Set([...upcomingRecs().map((r) => r.site), ...LP.pastWeek(ix.records, snap.generated_at).map((r) => r.site),
  ...(snap.areas || []).map((a) => (a.expect || {}).site)].filter(Boolean))].sort((a, b) => a.localeCompare(b));
// The site and launch lists come from this run's data, and the launch times follow the viewer's time zone.
function pickOptions() {
  const fill = (id, first, opts, value) => { $(id).replaceChildren(new Option(first, ""), ...opts.map(([v, t]) => new Option(t, v))); $(id).value = value; };
  fill("layers-site", "every site", siteNames().map((n) => [n, n]), lay.site);
  fill("layers-launch", "every launch", upcomingRecs().filter((r) => r.ll2).sort((a, b) => ((a.time || "") < (b.time || "") ? -1 : 1))
    .map((r) => [r.ll2, `${netText(r.time, r.net_precision)}: ${r.label}`]), lay.launch);
}
function layersUi() {
  lay = LY.settle(lay, siteNames(), upcomingRecs().map((r) => r.ll2));
  pickOptions();
  $("layers-place").checked = lay.match === "place";
  const box = $("layers");
  box.querySelectorAll("[data-layer]").forEach((i) => { i.checked = lay.show.includes(i.dataset.layer); });
  box.querySelectorAll("[data-src]").forEach((i) => { i.checked = lay.src.includes(i.dataset.src); });
  box.querySelectorAll("[data-cc]").forEach((i) => { i.checked = lay.cc.includes(i.dataset.cc); });
  $("layers-within").value = String(lay.within);
  if (LY.query(lay)) box.open = true;
}
function layersRead() {
  const box = $("layers"), on = (attr) => [...box.querySelectorAll(`[data-${attr}]`)].filter((i) => i.checked).map((i) => i.dataset[attr]);
  return { show: on("layer"), src: on("src"), cc: on("cc"), within: Number($("layers-within").value) || 0,
    site: $("layers-site").value, launch: $("layers-launch").value, match: $("layers-place").checked ? "place" : "all" };
}
function writeAddress() {
  if (document.body.dataset.tab !== "live") return;
  const q = LY.query(lay), want = "#live" + (q ? "?" + q : "");
  if (location.hash === want || (!q && !location.hash)) return;
  try { history.replaceState(null, "", want); } catch { /* address not kept; the view still changes */ }
}
const zonesFc = () => (lay.show.includes("zones") ? { type: "FeatureCollection", features: pat.recurring.map((z, i) => poly(z.ring, { key: "zone:" + i })) } : null);
let zonesDrawn = false;
function redraw() {
  liveM = liveModel();
  ["live", "pads", "recent"].forEach((k) => map.set(k, liveM[k]));
  map.set("paths", document.body.dataset.tab === "live" ? liveM.paths : null);
  const z = lay.show.includes("zones");
  if (z || zonesDrawn) map.set("zones", zonesFc());
  zonesDrawn = z;
  $("layers-sum").textContent = "· " + LY.summary(...liveM.counts);
  liveTables(); board();
}

/* ---------- patterns ---------- */
function patterns() {
  put($("corridor-table"), table(["Pad", { label: "Events", num: true }, "Azimuth bands: events (implied inclination)"],
    pat.corridors.filter((c) => c.events >= 3).slice(0, 40).map((c) => ({ c, cells: [c.site || `${c.pad[1].toFixed(2)}, ${c.pad[0].toFixed(2)}`, c.events,
      c.bands.filter((b) => b.events >= 2).map((b) => `${b.from}–${b.to}°: ${b.events} (≈${b.inclination_median}°)`).join("; ") || "no band with two or more events"] }))));
  const zoneRows = pat.recurring.map((z, i) => ({ z, cells: [i + 1, z.events, Object.entries(z.actors).map(([a, n]) => `${a} ${n}`).join(", "),
    z.first.label, z.latest.time ? fmt(z.latest.time, { time: false }) : "", `${z.centre[1].toFixed(2)}, ${z.centre[0].toFixed(2)}`] }));
  put($("zone-table"), table(["#", { label: "Events", num: true }, "Country", "First seen", "Latest", "Centre"], zoneRows.slice(0, 60), (r) => {
    map.set("zones", { type: "FeatureCollection", features: [poly(r.z.ring, { key: "zone" })] });
    map.fit({ type: "FeatureCollection", features: [poly(r.z.ring, {})] });
    $("show-zones").checked = false;
    lay = { ...lay, show: lay.show.filter((x) => x !== "zones") }; zonesDrawn = false;
  }));
  const years = [...new Set(pat.firs.flatMap((f) => Object.keys(f.by_year)))].sort();
  put($("fir-table"), table(["FIR", "State", ...years.map((y) => ({ label: y, num: true })), { label: "Total", num: true }],
    pat.firs.slice(0, 25).map((f) => ({ cells: [f.fir, f.state ? mark(f.state) : "", ...years.map((y) => f.by_year[y] || ""), f.total] }))));
  put($("window-table"), table(["Layer", { label: "Notices", num: true }, { label: "Median h", num: true }, { label: "90% under h", num: true }],
    Object.entries(pat.windows).map(([k, w]) => ({ cells: [k, w.notams, w.median_h, w.p90_h] }))));
  put($("hour-table"), table(["Country", "00–05", "06–11", "12–17", "18–23"], Object.entries(pat.hours).map(([a, h]) => ({ cells: [
    a === "other" ? "Other" : mark(a), ...[0, 6, 12, 18].map((s) => h.slice(s, s + 6).reduce((x, y) => x + y, 0))] }))));
  folds("patterns");
}

/* ---------- paste ---------- */
function paste() {
  const out = $("paste-out");
  $("paste-go").addEventListener("click", () => {
    out.textContent = "";
    const parts = N.splitMany($("paste-text").value);
    if (!parts.length) { out.appendChild(muted("No NOTAM header or Q-line found.")); map.set("paste", null); return; }
    const feats = [];
    trajAreas = [];
    parts.forEach((p, k) => {
      let n;
      try { n = N.parse(p); } catch (err) { out.appendChild(muted("Could not read: " + err.message)); return; }
      const d = el("div", "paste-item");
      d.appendChild(el("p", "small", `${n.number || "Notice"}${n.q ? ` · ${n.q.fir} · ${n.q.code}` : ""}${n.q && n.q.subject_text ? ` (${n.q.subject_text}${n.q.condition_text ? ", " + n.q.condition_text : ""})` : ""}` +
        ` · ${n.start ? fmt(n.start.slice(0, 20)) : "?"} to ${n.end && n.end !== "PERM" ? fmt(n.end.slice(0, 20)) : n.end || "?"}` + (n.lower ? ` · ${n.lower} to ${n.upper}` : "")));
      const areaShapes = n.shapes.filter((s) => s.ring || s.point);
      n.shapes.forEach((s) => {
        d.appendChild(el("p", "small muted", "Shape: " + s.derived));
        if (s.ring || s.point) {
          const label = (n.number || `Notice ${k + 1}`) + (areaShapes.length > 1 ? ` area ${areaShapes.indexOf(s) + 1}` : "");
          trajAreas.push(s.ring ? { label, ring: s.ring } : { label, point: s.point });
        }
        if (s.ring) feats.push(poly(s.ring, { key: "paste" }));
        if (s.line) feats.push({ type: "Feature", properties: { key: "paste" }, geometry: { type: "LineString", coordinates: s.line } });
      });
      n.rejected.forEach((r) => d.appendChild(el("p", "small badge-warn", `Not read: ${r.token} (${r.reason})`)));
      const sp = el("p", "small"), sb = el("button", "linkish", "Save to History (this browser)"); sb.type = "button";
      sb.addEventListener("click", () => { saveNotices([p]); sb.disabled = true; sb.textContent = "Saved"; });
      sp.appendChild(sb); d.appendChild(sp);
      out.appendChild(d);
    });
    if (parts.length > 1) {
      const sp = el("p", "small"), sb = el("button", "", `Save all ${parts.length} to History (this browser)`); sb.type = "button";
      sb.addEventListener("click", () => { saveNotices(parts); out.querySelectorAll(".paste-item button.linkish").forEach((b) => { b.disabled = true; b.textContent = "Saved"; }); sb.disabled = true; });
      sp.appendChild(sb); out.appendChild(sp);
    }
    pasteFc = { type: "FeatureCollection", features: feats };
    map.set("paste", pasteFc); if (feats.length) map.fit(pasteFc);
    trajRun(true);
  });
  $("paste-clear").addEventListener("click", () => { $("paste-text").value = ""; out.textContent = ""; map.set("paste", null); pasteFc = null; trajAreas = []; trajRun(false); });
}

/* ---------- notices saved in this browser (saved.js), shown on the History tab ---------- */
function savedMsg(t) { $("saved-msg").textContent = t; }
function saveNotices(texts) {
  const before = SV.load(), after = SV.add(before, texts.map((t) => SV.entry(t)));
  if (!SV.store(after)) { savedMsg("This browser would not save: its storage is off or full."); return; }
  savedRender(after.length - before.length);
}
function savedRender(added, fromHistory) {
  const list = SV.load(), ul = $("saved-list"); ul.textContent = "";
  list.map(SV.read).filter(Boolean).forEach((n) => {
    const li = el("li");
    li.appendChild(el("b", "", n.number || "Notice"));
    li.appendChild(document.createTextNode(" · " + [n.firs.join(" "), n.q_code, n.start ? `${fmt(n.start)} to ${n.end ? fmt(n.end) : "?"}` : "no window read",
      n.rings.length + n.points.length ? `${n.rings.length + n.points.length} area${n.rings.length + n.points.length === 1 ? "" : "s"}` : "no area read"].filter(Boolean).join(" · ") + " "));
    const b = el("button", "linkish", "Remove"); b.type = "button";
    b.addEventListener("click", () => { SV.store(SV.load().filter((x) => x.id !== n.id)); savedRender(); });
    li.appendChild(b); ul.appendChild(li);
  });
  if (!list.length) ul.appendChild(el("li", "muted", "None saved yet."));
  $("saved-export").disabled = $("saved-clear").disabled = !list.length;
  let msg = added === undefined ? "" : added ? `Saved ${added} notice${added === 1 ? "" : "s"}.` : "Already saved.";
  if (H && !fromHistory) {
    const c = H.savedChanged();
    if (added !== undefined) msg += ` On the History tab: ${c.joined} of ${c.saved} on a launch, ${c.own} with no identified launch.`;
  }
  if (added !== undefined) savedMsg(msg);
}
function savedSetup() {
  $("saved-export").addEventListener("click", () => {
    const a = el("a"); a.href = URL.createObjectURL(new Blob([SV.toFile(SV.load())], { type: "application/json" }));
    a.download = "launch-saved-notices.json"; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  });
  $("saved-import").addEventListener("change", async (ev) => {
    const f = ev.target.files && ev.target.files[0]; ev.target.value = "";
    if (!f) return;
    try {
      const before = SV.load(), after = SV.add(before, SV.fromFile(await f.text()));
      if (!SV.store(after)) { savedMsg("This browser would not save: its storage is off or full."); return; }
      savedRender(after.length - before.length);
    } catch (err) { savedMsg("Could not read that file: " + err.message); }
  });
  $("saved-clear").addEventListener("click", () => {
    if (!confirm("Remove every saved notice from this browser? Export them first to keep a copy.")) return;
    SV.store([]); savedRender(); savedMsg("Removed.");
  });
  window.addEventListener("launch:saved", () => savedRender(undefined, true));
  savedRender();
}

/* ---------- trajectory from a pad (traj.js has the maths and its limits) ---------- */
let pasteFc = null, trajAreas = [], trajPad = null, picking = false;
const whole = (x) => Math.round(x).toLocaleString("en-US");
const latLon = (lon, lat) => `${Math.abs(lat).toFixed(3)}° ${lat < 0 ? "S" : "N"}, ${Math.abs(lon).toFixed(3)}° ${lon < 0 ? "W" : "E"}`;
const azText = (az) => `${az.toFixed(1)}° ${TR.compass(az)}`;
function trajSetup() {
  const sel = $("traj-pad"), btn = $("traj-click");
  sel.append(new Option("Choose a launch site", ""));
  [...ix.sites].sort((a, b) => a.name.localeCompare(b.name)).forEach((s) => sel.append(new Option(`${s.name} (${countryName(s.country)})`, s.name)));
  const choose = (s) => { trajPad = s ? { name: s.name, lon: s.lon, lat: s.lat } : null; sel.value = s ? s.name : ""; trajRun(true); };
  trajSetup.choose = choose;
  sel.addEventListener("change", () => {
    if (sel.value === "__point") return;
    sel.querySelectorAll('option[value="__point"]').forEach((o) => o.remove());
    choose(ix.sites.find((x) => x.name === sel.value));
  });
  const stop = () => { picking = false; btn.textContent = "or click the map"; map.pickPoint(null); };
  btn.addEventListener("click", () => {
    if (picking) { stop(); return; }
    picking = true; btn.textContent = "Click the pad's position on the map (or here to cancel)";
    map.pickPoint(([lon, lat]) => {
      stop();
      trajPad = { name: "Point clicked on the map", lon, lat };
      sel.querySelectorAll('option[value="__point"]').forEach((o) => o.remove());
      sel.append(new Option("Point: " + latLon(lon, lat), "__point")); sel.value = "__point";
      trajRun(true);
    });
  });
}
function trajRun(fit) {
  const out = $("traj-out");
  $("traj").hidden = !trajAreas.length;
  out.textContent = "";
  map.set("traj", null); map.set("trajpad", null);
  if (!trajAreas.length) return;
  if (!trajPad) {
    const centres = trajAreas.map((a) => (a.ring ? TR.areaCentre(a.ring).centre : a.point));
    const near = ix.sites.map((s) => {
      const p = [s.lon, s.lat];
      const c = centres.reduce((best, x) => (TR.distNm(p, x) < TR.distNm(p, best) ? x : best));
      const az = TR.bearing(p, c);
      return { s, nm: TR.distNm(p, c), az, inc: TR.inclination(s.lat, az) };
    }).sort((a, b) => a.nm - b.nm).slice(0, 5);
    out.append(muted("No pad chosen. The launch sites nearest the pasted areas; choose one, or pick a pad above:"),
      table(["Launch site", { label: "To the nearest area, NM", num: true }, "Azimuth", { label: "Implied inclination", num: true }],
        near.map((r) => ({ r, cells: [r.s.name, whole(r.nm), azText(r.az), r.inc.toFixed(1) + "°"] })), (row) => trajSetup.choose(row.r.s)));
    return;
  }
  const pad = [trajPad.lon, trajPad.lat];
  const res = TR.analyse(pad, trajAreas), d = res.dogleg;
  const say = !d.tested ? "One area: the dog-leg test needs two or more."
    : !d.flagged ? `No sign of a dog-leg: every area lies on the great circle from the pad through ${d.farthest.label} (within ${TR.OFF_LINE_NM} NM).`
    : `Possible dog-leg: ${d.worst.label} ${d.worst.line.behind ? "lies behind the pad" : `lies ${whole(d.worst.line.off)} NM outside the great circle from the pad through ${d.farthest.label}`}. It can also mean the areas are from different events.`;
  out.append(el("p", "small", `${trajPad.name} (${latLon(pad[0], pad[1])}). `), el("p", d.flagged ? "small badge-warn" : "small", say));
  const lineText = (r) => (!r.line ? "not tested" : r === d.farthest ? "sets the line" : r.line.behind ? "behind the pad" : r.line.on ? "on it" : `${whole(r.line.off)} NM off`);
  out.append(el("div", "tbl-wrap"));
  out.lastChild.append(table(["Area", "Azimuth", { label: "Distance NM", num: true }, { label: "km", num: true },
    { label: "Implied inclination", num: true }, "Orbit type", "Mirrored azimuth", "On the line"],
    res.rows.map((r) => ({ cells: [r.label, azText(r.az), whole(r.nm), whole(r.nm * 1.852), r.inc.toFixed(1) + "°", r.type, azText(r.mirror), lineText(r)] }))));
  map.set("traj", { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: N.geodesic(res.path) } }] });
  const padFeat = { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: pad } };
  map.set("trajpad", { type: "FeatureCollection", features: [padFeat] });
  if (fit) map.fit({ type: "FeatureCollection", features: [...((pasteFc && pasteFc.features) || []), padFeat] });
}

function sourcesBox() {
  const box = $("source-list"); box.textContent = "";
  const ul = el("ul", "plain");
  (srcs.sources || []).forEach((s) => {
    const li = el("li");
    const a = el("a", "", s.name); a.href = s.url; a.rel = "noopener";
    li.append(a, document.createTextNode(` · ${s.use === "ingest" ? "read" : s.use === "link" ? "linked, not collected" : "not read yet"}` + (s.grade ? ` · grade ${s.grade} (${s.reliability}; ${s.credibility})` : "") + ` · ${s.licence}`));
    ul.appendChild(li);
  });
  box.appendChild(ul);
  // NotamForChina's credit, from the data it came in (data/launches.json, from history/nfc.json), with its licence.
  const n = ix && ix.nfc;
  if (n) {
    const p = el("p", "nfc-credit");
    const a = el("a", "", "NotamForChina"); a.href = `https://${n.source}/tree/${n.commit}`; a.rel = "noopener";
    const lic = el("a", "", "licence text"); lic.href = n.licence_file;
    p.append(el("b", "", "Chinese launches and their NOTAMs: "), a, document.createTextNode(` (commit ${n.commit.slice(0, 7)}) · ${n.licence} · `), lic, el("br"), document.createTextNode(n.attribution));
    box.appendChild(p);
  }
  // Joey0609/notams' credit, from the data it came in (data/launches.json, from history/joey.json), with its licence.
  const j = ix && ix.joey;
  if (j) {
    const p = el("p", "nfc-credit");
    const a = el("a", "", "Joey0609/notams"); a.href = `https://${j.source}/tree/${j.commit}`; a.rel = "noopener";
    const lic = el("a", "", "licence text"); lic.href = j.licence_file;
    p.append(el("b", "", "Launch NOTAMs with their text, mostly China's, from December 2020: "), a, document.createTextNode(` (commit ${j.commit.slice(0, 7)}) · ${j.licence} · `), lic, el("br"), document.createTextNode(j.attribution));
    box.appendChild(p);
  }
  $("lane-list").textContent = "Lanes: " + Object.entries(snap.lanes || {}).map(([k, v]) => `${k} ${v.status}` + (v.fetched_at ? " (" + fmt(v.fetched_at) + ")" : "") + (v.from_previous ? ", last good copy" : "")).join("; ") + ".";
}

/* ---------- tabs ---------- */
const TABS = ["live", "history", "patterns", "paste", "sources"];
const MAP_TABS = { live: "live", patterns: "patterns", paste: "paste" }; // tabs that show the shared map
async function showTab() {
  const name = (location.hash.replace(/^#/, "").split("?")[0]) || "live";
  const tab = TABS.includes(name) ? name : "live";
  document.body.dataset.tab = tab;
  document.title = (tab === "live" ? "" : $("tab-" + tab).textContent + " · ") + "Launch · The Intelligence Company";
  TABS.forEach((t) => {
    $(t).hidden = t !== tab;
    const a = $("tab-" + t); a.setAttribute("aria-selected", t === tab ? "true" : "false");
    if (t === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (tab === "live") {
    const q = location.hash.includes("?") ? location.hash.slice(location.hash.indexOf("?") + 1) : null;
    if (q !== null && q !== LY.query(lay)) { lay = LY.parse(q); if (map && liveM) { layersUi(); redraw(); } }
    writeAddress();
  }
  if (MAP_TABS[tab]) {
    const card = $("map-card"), panel = $(tab);
    if (tab === "live") { if (card.parentElement !== panel) panel.querySelector(".hero").after(card); }
    else if (card.parentElement !== panel) panel.prepend(card);
    if (map) map.resize();
  }
  if (map && liveM) map.set("paths", tab === "live" ? liveM.paths : null); // the launch paths belong to the Live tab
  if (tab === "history") {
    if (!H) H = await (Hstart = Hstart || initHistory(ix, hist));
    // A History address with filters (a link from Live, a bookmark) takes that view; the bare tab link keeps the last one.
    else { H.resize(); if (location.hash.includes("?")) H.fromHash(); else H.refresh(); }
  }
}

async function main() {
  // data/upcoming.json is the schedule's own record, for the board's NET moves. Without it the board still lists
  // every launch.
  [snap, hist, pat, srcs, ix, sched] = await Promise.all([...["data/snapshot.json", "data/history.json", "data/patterns.json", "data/sources.json", "data/launches.json"].map(getJSON),
    getJSON("data/upcoming.json").then((d) => d.records || []).catch(() => [])]);
  const hq = location.hash.match(/^#live\?(.*)$/);
  if (hq) lay = LY.parse(hq[1]);
  if (T && T.mountSettings) T.mountSettings($("time-settings"));
  tiles(); liveTables(); board(); sourcesBox(); related();
  // Address changes (tab links, a pasted or hand-edited History address) are taken from the start: waiting for the
  // maps to load left every tab link dead until then, and for good where a map never loads.
  window.addEventListener("hashchange", () => {
    const t = location.hash.replace(/^#/, "").split("?")[0];
    if (t === "history" && H && document.body.dataset.tab === "history") H.fromHash(); else showTab();
  });
  const shown = showTab();
  const model = liveM = liveModel();
  try {
    map = await createMap($("map"), model, { onPick: (k) => { if (/^(live|pad|path|recent|stack):/.test(k)) pickLive(k); } });
  } catch (err) { // no map (no WebGL 2, or the map failed): every tab still works, and every area is in the tables
    $("map").textContent = "The map could not load: " + err.message + ". Every area and launch is listed on this page.";
    map = { set() {}, fit() {}, pickPoint() {}, resize() {} };
  }
  if (document.body.dataset.tab !== "live") map.set("paths", null);
  patterns(); paste(); trajSetup(); savedSetup();
  layersUi(); redraw();
  $("layers").addEventListener("change", (e) => {
    // A site and a launch replace each other, so the two never cancel out; the map moves to what was chosen.
    const id = (e.target || {}).id, moved = id === "layers-site" || id === "layers-launch";
    if (id === "layers-site") $("layers-launch").value = "";
    if (id === "layers-launch") $("layers-site").value = "";
    lay = layersRead(); redraw(); writeAddress();
    const found = [...liveM.live.features, ...liveM.paths.features, ...liveM.pads.features];
    if (moved && (lay.site || lay.launch) && found.length) map.fit({ type: "FeatureCollection", features: found });
  });
  $("layers-reset").addEventListener("click", () => { lay = LY.parse(""); layersUi(); redraw(); writeAddress(); });
  map.resize();
  await shown;
  if (T && T.onChange) T.onChange(() => { tiles(); pickOptions(); liveTables(); board(); sourcesBox(); if (openCard) launchCard(openCard, false); });
}
main().catch((err) => { document.querySelector("main").prepend(el("p", "notice", "Launch could not load its data: " + err.message)); });
