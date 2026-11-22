/* Launch page: reads data/snapshot.json, data/history.json, data/launches.json, data/patterns.json and
   data/sources.json and draws them, one tab at a time (#live, #history, #patterns, #paste, #sources; the History
   tab is history.js). Times are stored UTC and shown in the viewer's zone through tic-time.js. No inline scripts (CSP). */
import { createMap } from "./map.js";
import * as N from "./notam.js";
import * as TR from "./traj.js";
import { initHistory } from "./history.js";
import * as SV from "./saved.js";
import * as LP from "./livepaths.js";

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
// Long tables fold with the hub's tic-fold.js at every width: the first 10 rows on a phone and 15 wider (each table
// lists the soonest or largest first), then "Show all"; a find box over 25 or more. It re-applies when a table is
// redrawn. The History tab's list has its own paging and is left.
const folds = (panel) => $(panel).querySelectorAll(".tbl-wrap > table").forEach((t) => {
  t.setAttribute("data-tic-fold", "");
  t.setAttribute("data-tic-fold-find", "");
});
const poly = (ring, props) => ({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [N.geodesic(ring)] } }); // edges as great circles

async function getJSON(p) { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }

let snap, hist, pat, srcs, ix, map, H = null, Hstart = null, liveM = null, openCard = null;
const byKey = new Map();
const upcomingRecs = () => ix.records.filter((r) => r.status === "upcoming");
const scheduled = (r) => ((snap.orbit || {}).upcoming || []).find((u) => u.id === r.ll2) || null;

function tiles() {
  const box = $("tiles"); box.textContent = "";
  const lv = {};
  (snap.matches || []).forEach((m) => { lv[m.level] = (lv[m.level] || 0) + 1; });
  const items = [
    ["Live closure areas", (snap.areas || []).length],
    ["FAA space-operations TFRs", (snap.tfr || []).length],
    ["Scheduled launches, 14 days", ((snap.orbit || {}).upcoming || []).length],
    ["Coincidences: time / time and place / grouped", `${lv.time || 0} / ${lv["time and place"] || 0} / ${lv.grouped || 0}`],
    [`Launches since ${(ix.ledger_since || "2012").slice(0, 4)}`, ix.records.filter((r) => r.status === "launched" && (r.time || "") >= (ix.ledger_since || "2012")).length],
    ["Recurring drop zones", pat.recurring.length],
  ];
  items.forEach(([k, v]) => { const t = el("div", "tile"); t.append(el("span", "k", k), el("span", "v", String(v))); box.appendChild(t); });
  $("asof").textContent = "Live areas read " + fmt(snap.generated_at) + ".";
  // Today's reading (tic-shell): this run's counts. A closure announces intent, so a coincidence is only that.
  const num = (v) => el("b", "", String(v));
  const areas = (snap.areas || []).length, tfr = (snap.tfr || []).length, up = ((snap.orbit || {}).upcoming || []).length, both = lv["time and place"] || 0;
  $("reading").replaceChildren(el("span", "tic-reading-k", "Today\u2019s reading"),
    num(areas), ` live closure area${areas === 1 ? "" : "s"}, `, num(tfr), ` FAA space-operations TFR${tfr === 1 ? "" : "s"} and `,
    num(up), ` launch${up === 1 ? "" : "es"} scheduled in the next 14 days. `, num(both),
    ` coincidence${both === 1 ? "" : "s"} between a scheduled launch and a closure, in both time and place.`);
}

function liveModel() {
  const live = { type: "FeatureCollection", features: [] };
  const tied = LP.tiedAreas(upcomingRecs());
  (snap.areas || []).forEach((a, i) => {
    const key = "live:" + (a.key || a.id) + ":" + i;
    const on = tied.get(i) || [];
    byKey.set(key, { kind: "live", a, launches: on });
    live.features.push(poly(a.ring, { key, tied: on.length ? 1 : 0, group: on.length ? group(on[0].actor) : a.source === "faa-tfr" ? "us" : "other" }));
  });
  const paths = { type: "FeatureCollection", features: LP.livePathRecords(upcomingRecs()).map((r) => {
    const key = "path:" + r.id;
    byKey.set(key, { kind: "launch", r });
    return { type: "Feature", properties: { key, group: group(r.actor) }, geometry: { type: "LineString", coordinates: N.estimatedLine(r.pad, r.path) } };
  }) };
  const pads = { type: "FeatureCollection", features: [] };
  ((snap.orbit || {}).upcoming || []).forEach((u) => {
    if (u.lat === null || u.lat === undefined) return;
    const key = "pad:" + u.id;
    byKey.set(key, { kind: "pad", u, r: upcomingRecs().find((x) => x.ll2 === u.id) || null });
    pads.features.push({ type: "Feature", properties: { key, group: group((u.provider_countries || [])[0]) }, geometry: { type: "Point", coordinates: [u.lon, u.lat] } });
  });
  return { live, paths, pads };
}

const SRC_LABEL = { "faa-tfr": "FAA TFR", "faa-nms": "NOTAM (FAA NMS-API)", "cordon-navwarn": "NGA navigational warning (via Cordon)" };
const srcLabel = (a) => SRC_LABEL[a.source] || "Navigational warning (via Orbit)";
const KEPT = { words: "launch words in the text", "cn-area": "China's surface-to-unlimited danger area, short window",
  "unl-area": "surface-to-unlimited area, short window", "recurring-area": "near a closure area in Launch's history" };
// "If a launch from <site>, around <time>": the site's median minutes from closure opening to launch (history/timing.json).
const expectText = (x) => x ? `if a launch from ${x.site}, around ${fmt(x.at, { date: false })} (median ${x.median_min} min after opening, ${x.launches} launches; middle half ${x.q1_min}-${x.q3_min} min)` : "";

function liveTables() {
  const ms = (snap.matches || []).slice().sort((a, b) => (a.net < b.net ? -1 : 1));
  const recOf = new Map(upcomingRecs().map((r) => [r.ll2, r]));
  const onPath = (m) => ((recOf.get(m.launch) || {}).live || { closures: [] }).closures.some((c) => c.i === m.area_i && c.role === "path");
  const lvlBadge = (m) => {
    const s = el("span", "lvl");
    s.append(el("span", "badge" + (m.level === "time" ? "" : " badge-warn"), m.level));
    if (m.named) { const n = el("span", "badge badge-warn", "names it"); n.title = `The notice's text has "${m.named}"`; s.append(n); }
    if (onPath(m)) s.append(el("span", "badge badge-path", "on path"));
    return s;
  };
  put($("match-table"), ms.length ? table(
    ["Scheduled launch", "NET", "Area", "Window (UTC shown in your zone)", "Level", { label: "Az / NM", num: true }, "Why"],
    ms.map((m) => ({ m, cells: [m.launch_name, fmt(m.net), m.area, span(m.window[0], m.window[1]),
      lvlBadge(m), `${m.azimuth}° / ${m.distance_nm}`, m.level === "grouped" ? "GCAT launch " + m.grouped_with.launch_tag : m.place_basis] })),
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
    }) : muted("No scheduled launch coincides with a live closure area."));
  const rows = (snap.areas || []).map((a, i) => ({ key: "live:" + (a.key || a.id) + ":" + i, cells: [
    srcLabel(a), a.key || a.id, a.label || (a.regions || []).join(", ") || "",
    ((a.windows || []).slice(0, 2).map((w) => span(w.start, w.end)).join("; ") + ((a.windows || []).length > 2 ? ` and ${(a.windows.length - 2)} more` : "") || "see the notice")
      + (a.expect ? "; " + expectText(a.expect) : "")] }));
  put($("area-table"), rows.length ? table(["Source", "Notice", "Where", "Windows"], rows, (r) => pickLive(r.key)) : muted("No live areas."));
  pastWeek();
  folds("live");
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
  put($("past-table"), rows.length ? table(["Launched", "Launch", "Site", "Country", "Orbit", "Outcome"],
    rows.map((r) => ({ cells: [fmt(r.time), name(r), r.site || "", mark(r.actor), r.orbit || "", result(r)] })))
    : muted("No launch is recorded in the past seven days."));
}

// Elsewhere today (tic-related.js from the hub): the countries of the pads with launches scheduled in the next 14
// days, strongest first: those with a launch that coincides with a live closure area, then by launches scheduled.
function related() {
  const box = $("tic-related");
  if (!box || !window.TicRelated) return;
  const up = (snap.orbit || {}).upcoming || [];
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
  if (x.kind === "pad") {
    box.append(el("b", "", x.u.name), document.createTextNode(` · NET ${fmt(x.u.net)} · ${x.u.pad || ""}, ${x.u.location || ""} · `), mark((x.u.provider_countries || [])[0]));
    return;
  }
  const a = x.a;
  box.append(el("b", "", (a.source === "faa-tfr" ? "FAA TFR " : a.source === "faa-nms" ? "NOTAM " : "") + (a.key || a.id)), document.createTextNode(" · " + (a.hazard || a.label || "") + ((a.detail || {}).activity ? " · " + a.detail.activity : "")));
  if (a.source === "faa-nms") box.append(el("br"), document.createTextNode("Kept: " + (KEPT[a.kept] || a.kept) + (a.expect ? "; " + expectText(a.expect) : "") + ". " + ((snap.nms || {}).source_note || "")));
  (x.launches || []).forEach((r) => {
    const b = el("button", "linkish", r.label); b.type = "button";
    b.addEventListener("click", () => launchCard(r));
    box.append(el("br"), document.createTextNode("On the estimated path of "), b);
  });
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
  fact("NET", fmt(r.time) + (r.net_precision && !["Second", "Minute"].includes(r.net_precision) ? ` (to the ${r.net_precision.toLowerCase()})` : "") + (r.ll2_status ? ` · ${r.ll2_status}` : ""));
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
  }));
  const years = [...new Set(pat.firs.flatMap((f) => Object.keys(f.by_year)))].sort();
  put($("fir-table"), table(["FIR", "State", ...years.map((y) => ({ label: y, num: true })), { label: "Total", num: true }],
    pat.firs.slice(0, 25).map((f) => ({ cells: [f.fir, f.state ? mark(f.state) : "", ...years.map((y) => f.by_year[y] || ""), f.total] }))));
  put($("window-table"), table(["Layer", { label: "Notices", num: true }, { label: "Median h", num: true }, { label: "90% under h", num: true }],
    Object.entries(pat.windows).map(([k, w]) => ({ cells: [k, w.notams, w.median_h, w.p90_h] }))));
  put($("hour-table"), table(["Country", "00–05", "06–11", "12–17", "18–23"], Object.entries(pat.hours).map(([a, h]) => ({ cells: [
    a === "other" ? "Other" : mark(a), ...[0, 6, 12, 18].map((s) => h.slice(s, s + 6).reduce((x, y) => x + y, 0))] }))));
  folds("patterns");
  $("show-zones").addEventListener("change", (ev) => {
    map.set("zones", ev.target.checked ? { type: "FeatureCollection", features: pat.recurring.map((z, i) => poly(z.ring, { key: "zone:" + i })) } : null);
  });
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
  TABS.forEach((t) => {
    $(t).hidden = t !== tab;
    const a = $("tab-" + t); a.setAttribute("aria-selected", t === tab ? "true" : "false");
    if (t === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (MAP_TABS[tab]) {
    const card = $("map-card"), panel = $(tab);
    if (tab === "live") { if (card.parentElement !== panel) panel.querySelector(".hero").after(card); }
    else if (card.parentElement !== panel) panel.prepend(card);
    if (map) map.resize();
  }
  if (map && liveM) map.set("paths", tab === "live" ? liveM.paths : null); // the launch paths belong to the Live tab
  if (tab === "history") {
    if (!H) H = await (Hstart = Hstart || initHistory(ix, hist));
    else { H.resize(); H.refresh(); }
  }
}

async function main() {
  [snap, hist, pat, srcs, ix] = await Promise.all(["data/snapshot.json", "data/history.json", "data/patterns.json", "data/sources.json", "data/launches.json"].map(getJSON));
  if (T && T.mountSettings) T.mountSettings($("time-settings"));
  tiles(); liveTables(); sourcesBox(); related();
  // Address changes (tab links, a pasted or hand-edited History address) are taken from the start: waiting for the
  // maps to load left every tab link dead until then, and for good where a map never loads.
  window.addEventListener("hashchange", () => {
    const t = location.hash.replace(/^#/, "").split("?")[0];
    if (t === "history" && H && document.body.dataset.tab === "history") H.fromHash(); else showTab();
  });
  const shown = showTab();
  const model = liveM = liveModel();
  try {
    map = await createMap($("map"), model, { onPick: (k) => { if (k.startsWith("live:") || k.startsWith("pad:") || k.startsWith("path:")) pickLive(k); } });
  } catch (err) { // no map (no WebGL 2, or the map failed): every tab still works, and every area is in the tables
    $("map").textContent = "The map could not load: " + err.message + ". Every area and launch is listed on this page.";
    map = { set() {}, fit() {}, pickPoint() {}, resize() {} };
  }
  if (document.body.dataset.tab !== "live") map.set("paths", null);
  patterns(); paste(); trajSetup(); savedSetup();
  map.resize();
  await shown;
  if (T && T.onChange) T.onChange(() => { tiles(); liveTables(); sourcesBox(); if (openCard) launchCard(openCard, false); });
}
main().catch((err) => { document.querySelector("main").prepend(el("p", "notice", "Launch could not load its data: " + err.message)); });
