/* Launch's History tab: every launch since 2012 (Launch's charted notices, GCAT, Launch Library 2) and Chinese launches from 2012
   with their notices (NotamForChina) on a map with flight paths,
   filters that combine (AND across filters, OR within one), a month timeline that sets the date range, a list and
   a detail card. State lives in the address (#history?...), so a view can be bookmarked or sent.
   Data: data/launches.json (catalog.py; NotamForChina's notices are on its records) and data/history.json (the charted
   notices, for the detail card).
   Times are stored UTC; dates and months are read in the viewer's zone (tic-time.js), like every time shown. */
import { createHistoryMap } from "./hmap.js";
import * as X from "./export.js";
import * as SV from "./saved.js";
import * as CH from "./chart.js";
import * as CMP from "./sidebyside.js";

const T = window.TicTime;
const BIG = { US: "us", CN: "cn", RU: "ru" };
const group = (cc) => BIG[cc] || "other";
let REGION = null;
try { REGION = new Intl.DisplayNames(["en"], { type: "region" }); } catch { REGION = null; }
const countryName = (cc) => { if (!cc) return "Not known"; try { return (REGION && REGION.of(cc)) || cc; } catch { return cc; } };
const fmt = (iso, o) => (!iso ? "" : T ? T.format(iso, o || {}) : iso.replace("T", " ").replace(":00Z", "Z"));
// "start to end", the end's date left off only on the start's day in the viewer's zone (app.js has the same).
const span = (a, b) => fmt(a) + " to " + fmt(b, fmt(a, { time: false }) === fmt(b, { time: false }) ? { date: false } : {});
const $ = (id) => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
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

const STATUS = { launched: "Launched", upcoming: "Scheduled (next 14 days)", notice: "Notices with no identified launch" };
const SOURCES = { chart: "Launch's charted notices", gcat: "GCAT launch record", ll2: "Launch Library 2", nfc: "NotamForChina", joey: "Joey0609/notams", wayback: "FAA and NGA notices (Internet Archive)", published: "Published notices (reviewed copies)", saved: "Saved in this browser" };
const OUTCOME = { success: "Success", failure: "Failure", "": "Not known" };
const NK = "Not known";
/* Launch kinds (catalog.py, from GCAT's launch code): the page's own list until data/launches.json gives its own. */
const KINDS = ["Orbital", "Suborbital rocket", "Crewed suborbital", "Atmospheric test", "Missile test", "Lofted missile test", "Combat launch", NK];
const kindSlug = (k) => (k || NK).toLowerCase().replace(/[^a-z]+/g, "-");

/* Facets: key in the address, label, how a record's values are read. */
const FACETS = [
  { k: "st", label: "Show", get: (r) => r.status, name: (v) => STATUS[v] || v, open: true, fixed: ["launched", "upcoming", "notice"] },
  { k: "kind", label: "Launch kind", get: (r) => r.kind || NK, open: true, fixed: KINDS, note: (v) => (IX.kind_notes || {})[v] },
  { k: "cc", label: "Country", get: (r) => r.actor || "", name: (v) => (v ? countryName(v) : NK), flag: true },
  { k: "veh", label: "Vehicle", get: (r) => r.vehicle || NK, search: true },
  { k: "site", label: "Launch site", get: (r) => r.site || NK, search: true },
  { k: "prog", label: "Programme", get: (r) => (r.programmes && r.programmes.length ? r.programmes : ["None found"]), search: true },
  { k: "mt", label: "Mission type", get: (r) => r.mtype },
  { k: "orb", label: "Orbit", get: (r) => r.orbit || NK },
  { k: "out", label: "Outcome", get: (r) => (r.status === "upcoming" ? "Scheduled" : r.outcome === "success" ? "Success" : r.outcome ? "Failure or partial" : NK) },
  { k: "src", label: "Source", get: (r) => r.sources, name: (v) => SOURCES[v] || v },
  { k: "path", label: "Flight path", get: (r) => (r.path ? "Estimated from an azimuth" : "None"), },
  // overfly.py: the countries the path's ground track crosses (land only).
  { k: "ovf", label: "Path crosses", get: (r) => { const cc = r.over ? [...new Set(r.over.flat().map((o) => o.cc))] : []; return !r.over ? ["nopath"] : cc.length ? cc : ["water"]; },
    name: (v) => (v === "nopath" ? "No flight path" : v === "water" ? "No land (water only)" : countryName(v)), flag: true, search: true },
];
/* Ranges: key in the address (lo-hi, either end open), label, unit, how a record's number is read, presets. A record
   without the number is left out while its range is set. Inclination bands follow the Paste tab's orbit types. */
const RANGES = [
  { k: "inc", label: "Inclination", unit: "°", step: "0.1", get: (r) => r.inc,
    about: "GCAT's payload inclination (launches GCAT lists)",
    presets: [["Near-equatorial", null, 10], ["Prograde 10-85", 10, 85], ["Near-polar 85-95", 85, 95], ["Sun-synchronous range", 96, 102], ["Retrograde", 90, null]] },
  { k: "far", label: "Farthest closure area", unit: "NM", step: "1", get: (r) => r.far_nm,
    about: "from the pad to the centre of the launch's farthest closure area; an area set aside as another event's does not count",
    presets: [["Under 500 NM", null, 500], ["500-2,500 NM", 500, 2500], ["Over 2,500 NM", 2500, null]] },
];
const num = (v) => (v === "" || v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v));
const rangeText = (g, [lo, hi]) => (lo !== null && hi !== null ? `${lo} to ${hi}` : lo !== null ? `${lo} or more` : `up to ${hi}`) + (g.unit === "°" ? "°" : " " + g.unit);
const DEFAULT = { st: ["launched"] };
const PAGE = 100;

let IX, HIST, map, byId = new Map(), chartById = new Map(), FIRST_YEAR = 2012;
let state = { f: {}, r: {}, q: "", from: "", to: "", sel: "", sort: "time", dir: -1, shown: PAGE, areas: true, cmp: [], chart: null };
let lastFiltered = [];

/* ---------- time keys in the viewer's zone ---------- */
let dayFmt = null;
function zoneDay(iso) {
  if (!iso) return "";
  try {
    if (!dayFmt) dayFmt = new Intl.DateTimeFormat("en-CA", { timeZone: T ? T.zone() : "UTC", year: "numeric", month: "2-digit", day: "2-digit" });
    return dayFmt.format(new Date(iso));
  } catch { return iso.slice(0, 10); }
}
function rekey() { dayFmt = null; IX.records.forEach((r) => { r._day = zoneDay(r.time); r._month = r._day.slice(0, 7); }); }
const zoneName = () => (T && T.zoneLabel ? T.zoneLabel() : "UTC");

/* ---------- the address ---------- */
/* Addresses written before 15 Nov 2026 used other words for the charted source (src=) and for its flight paths
   (path=). They are matched by a short string hash, so the old words are not spelled out in this public file, and
   read as the new ones. No current value shares either hash (tests/test_privacy.py checks). From 19 Nov 2026 no
   path is "as charted" (the charted lines are an analyst's guesses, not flight paths): an address asking for those
   paths reads as the estimated paths the same launches now have. */
const strHash = (s) => [...s].reduce((h, c) => (Math.imul(h, 31) + c.charCodeAt(0)) | 0, 0);
const LEGACY = { src: { 115026: "chart" }, path: { "-1763747857": "Estimated from an azimuth" } };
const OLD_PATH = { "As charted": "Estimated from an azimuth" };
const legacy = (k, v) => (LEGACY[k] || {})[strHash(v)] || (k === "path" && OLD_PATH[v]) || v;
function readHash() {
  const h = location.hash.replace(/^#/, "");
  const [tab, qs] = h.split("?");
  const s = { f: {}, r: {}, q: "", from: "", to: "", sel: "", sort: "time", dir: -1, shown: PAGE, areas: true, cmp: [], chart: null };
  if (tab !== "history" || !qs) { s.f = JSON.parse(JSON.stringify(DEFAULT)); return s; }
  const p = new URLSearchParams(qs);
  FACETS.forEach((f) => { if (p.has(f.k)) s.f[f.k] = p.get(f.k).split("|").filter((x) => x !== "").map((x) => legacy(f.k, x)); });
  if (!p.has("st")) s.f.st = DEFAULT.st.slice();
  RANGES.forEach((g) => {
    const m = /^([\d.]*)-([\d.]*)$/.exec(p.get(g.k) || "");
    const lo = m ? num(m[1]) : null, hi = m ? num(m[2]) : null;
    if (lo !== null || hi !== null) s.r[g.k] = lo !== null && hi !== null && lo > hi ? [hi, lo] : [lo, hi];
  });
  s.q = p.get("q") || ""; s.from = p.get("from") || ""; s.to = p.get("to") || ""; s.sel = p.get("sel") || ""; if (byId.get(s.sel)) s.sel = byId.get(s.sel).id;
  if (p.get("areas") === "0") s.areas = false;
  s.cmp = [...new Set(CMP.parseIds(p.get("cmp")).filter((id) => byId.has(id)).map((id) => byId.get(id).id))];
  s.chart = CH.parseChart(p.get("chart"), CHART_BY.map((b) => b.k), CHART_SPLIT.map((b) => b.k));
  if (p.get("sort")) { s.sort = p.get("sort"); s.dir = p.get("dir") === "1" ? 1 : -1; }
  return s;
}
function writeHash() {
  const p = new URLSearchParams();
  Object.entries(state.f).forEach(([k, v]) => { if (v && v.length) p.set(k, v.join("|")); });
  if (!state.f.st || !state.f.st.length) p.set("st", "");
  RANGES.forEach((g) => { const v = state.r[g.k]; if (v) p.set(g.k, `${v[0] ?? ""}-${v[1] ?? ""}`); });
  if (state.q) p.set("q", state.q);
  if (state.from) p.set("from", state.from);
  if (state.to) p.set("to", state.to);
  if (state.sel) p.set("sel", state.sel);
  if (!state.areas) p.set("areas", "0");
  if (state.cmp.length) p.set("cmp", state.cmp.join("|"));
  if (state.chart) p.set("chart", CH.chartParam(state.chart));
  if (state.sort !== "time" || state.dir !== -1) { p.set("sort", state.sort); p.set("dir", String(state.dir)); }
  const url = "#history" + (p.toString() ? "?" + p.toString() : "");
  if (location.hash !== url) history.replaceState(null, "", url);
}

/* ---------- filtering ---------- */
const vals = (f, r) => [].concat(f.get(r));
function hay(r) {
  if (r._hay) return r._hay;
  const charted = (r.chart || []).flatMap((id) => chartById.get(id) || []);
  r._hay = [r.label, r.vehicle, r.gcat_vehicle, r.ll2_vehicle, r.payload, r.flight, r.site, r.pad_name, r.gcat, r.mtype, r.orbit,
    countryName(r.actor), r.actor, ...(r.programmes || []), ...((r.payloads || {}).names || []), ...(r.chart_labels || []),
    ...charted.flatMap((e) => [e.extra, ...e.notams.map((n) => (n.number || "") + " " + ((n.q || {}).fir || ""))]),
    ...(r.nfc_notices || []).map((n) => (n.number || "") + " " + (n.fir || "") + " " + (n.label || "")),
    ...(r.joey_notices || []).map((n) => (n.number || "") + " " + (n.fir || "") + " " + (n.locations || []).join(" ")),
    ...(r.archive_notices || []).map((n) => (n.number || n.id || "") + " " + (n.location || "")),
    ...(r.saved_notices || []).map((n) => (n.number || "") + " " + n.firs.join(" "))]
    .filter(Boolean).join(" ").toUpperCase();
  return r._hay;
}
function passes(r, skip) {
  for (const f of FACETS) {
    if (f.k === skip) continue;
    const want = state.f[f.k];
    if (!want || !want.length) { if (f.k === "st") return false; continue; }
    const have = vals(f, r);
    if (!have.some((v) => want.includes(v))) return false;
  }
  for (const g of RANGES) {
    const want = state.r[g.k];
    if (!want || skip === g.k) continue;
    const v = g.get(r);
    if (v === null || v === undefined) return false;
    if (want[0] !== null && v < want[0]) return false;
    if (want[1] !== null && v > want[1]) return false;
  }
  if (skip !== "date") {
    if (state.from && (!r._day || r._day < state.from)) return false;
    if (state.to && (!r._day || r._day > state.to)) return false;
  }
  if (state.q) {
    const h = hay(r);
    if (!state.q.toUpperCase().split(/\s+/).filter(Boolean).every((w) => h.includes(w))) return false;
  }
  return true;
}
const filtered = (skip) => IX.records.filter((r) => passes(r, skip));

/* ---------- the filter panel ---------- */
const facetOpen = {};
function renderFacets() {
  const box = $("h-facets"); box.textContent = "";
  FACETS.forEach((f) => {
    const counts = new Map();
    filtered(f.k).forEach((r) => vals(f, r).forEach((v) => counts.set(v, (counts.get(v) || 0) + 1)));
    const sel = state.f[f.k] || [];
    let opts = f.fixed ? f.fixed.slice() : [...new Set([...counts.keys(), ...sel])];
    if (!f.fixed) opts.sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0) || String(a).localeCompare(String(b)));
    const d = el("details", "facet");
    d.open = facetOpen[f.k] !== undefined ? facetOpen[f.k] : !!(f.open || sel.length);
    d.addEventListener("toggle", () => { facetOpen[f.k] = d.open; });
    const sum = el("summary", "", f.label);
    if (sel.length && f.k !== "st") sum.appendChild(el("span", "badge", String(sel.length)));
    d.appendChild(sum);
    let list = el("div", "opts");
    let needle = "";
    const draw = () => {
      list.textContent = "";
      const show = opts.filter((v) => !needle || (f.name ? f.name(v) : v).toUpperCase().includes(needle) || String(v).toUpperCase().includes(needle));
      const limit = facetOpen[f.k + ":all"] || needle ? show.length : 10;
      show.slice(0, limit).forEach((v) => {
        const n = counts.get(v) || 0;
        const lab = el("label", "opt" + (n ? "" : " zero"));
        const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = sel.includes(v);
        cb.addEventListener("change", () => {
          const cur = new Set(state.f[f.k] || []);
          cb.checked ? cur.add(v) : cur.delete(v);
          state.f[f.k] = [...cur];
          state.shown = PAGE; update(true);
        });
        lab.appendChild(cb);
        if (f.flag && /^[A-Z]{2}$/.test(v)) lab.appendChild(mark(v));
        lab.appendChild(el("span", "nm", f.name ? f.name(v) : v));
        lab.appendChild(el("span", "n", String(n)));
        if (f.note && f.note(v)) lab.title = `${v}: ${f.note(v)}`;
        list.appendChild(lab);
      });
      if (show.length > limit) {
        const b = el("button", "linkish small", `Show all ${show.length}`); b.type = "button";
        b.addEventListener("click", () => { facetOpen[f.k + ":all"] = true; draw(); });
        list.appendChild(b);
      }
      if (sel.length && f.k !== "st") {
        const c = el("button", "linkish small", "Clear"); c.type = "button";
        c.addEventListener("click", () => { state.f[f.k] = []; update(true); });
        list.appendChild(c);
      }
    };
    if (f.search && opts.length > 10) {
      const inp = document.createElement("input"); inp.type = "search"; inp.placeholder = "Find a " + f.label.toLowerCase();
      inp.setAttribute("aria-label", "Find a " + f.label.toLowerCase());
      inp.addEventListener("input", () => { needle = inp.value.trim().toUpperCase(); draw(); });
      d.appendChild(inp);
    }
    d.appendChild(list); draw();
    box.appendChild(d);
  });
}

/* ---------- the range panel (inclination and distances): built once so typing keeps its focus ---------- */
const rangeBox = {};
function setRange(k, lo, hi) {
  lo = num(lo); hi = num(hi);
  if (lo !== null && hi !== null && lo > hi) [lo, hi] = [hi, lo];
  if (lo === null && hi === null) delete state.r[k]; else state.r[k] = [lo, hi];
  state.shown = PAGE; update(true);
}
function buildRanges() {
  const box = $("h-ranges"); box.textContent = "";
  RANGES.forEach((g) => {
    const d = el("details", "facet range");
    d.open = !!state.r[g.k];
    const sum = el("summary", "", g.label);
    const badge = el("span", "badge", "1"); sum.appendChild(badge);
    d.appendChild(sum);
    d.appendChild(el("p", "small muted range-about", g.about + "."));
    const row = el("div", "date-row");
    const inp = (word) => {
      const lab = el("label", "", `${word} (${g.unit})`);
      const i = document.createElement("input"); i.type = "number"; i.min = "0"; i.step = g.step; i.inputMode = "decimal";
      i.addEventListener("change", () => setRange(g.k, rangeBox[g.k].lo.value, rangeBox[g.k].hi.value));
      lab.appendChild(i); row.appendChild(lab); return i;
    };
    const lo = inp("From"), hi = inp("To");
    d.appendChild(row);
    const pre = el("div", "presets");
    const btns = g.presets.map(([t, a, b]) => {
      const btn = el("button", "chip-btn", t); btn.type = "button";
      btn.addEventListener("click", () => { const v = state.r[g.k]; v && v[0] === a && v[1] === b ? setRange(g.k, null, null) : setRange(g.k, a, b); });
      pre.appendChild(btn); return [btn, a, b];
    });
    d.appendChild(pre);
    const n = el("p", "small muted range-n"); d.appendChild(n);
    rangeBox[g.k] = { d, lo, hi, badge, btns, n };
    box.appendChild(d);
  });
}
function rangesShow() {
  RANGES.forEach((g) => {
    const b = rangeBox[g.k]; if (!b) return;
    const v = state.r[g.k];
    if (document.activeElement !== b.lo) b.lo.value = v && v[0] !== null ? v[0] : "";
    if (document.activeElement !== b.hi) b.hi.value = v && v[1] !== null ? v[1] : "";
    if (v) b.d.open = true;
    b.badge.hidden = !v;
    b.btns.forEach(([btn, a, c]) => btn.classList.toggle("on", !!v && v[0] === a && v[1] === c));
    const base = filtered(g.k), have = base.filter((r) => { const x = g.get(r); return x !== null && x !== undefined; }).length;
    b.n.textContent = `${have} of ${base.length} in your other filters have one` + (v ? "; the rest are hidden while this is set." : ".");
  });
}

function setDates(from, to) {
  state.from = from || ""; state.to = to || "";
  if (state.from && state.to && state.from > state.to) [state.from, state.to] = [state.to, state.from];
  $("h-from").value = state.from; $("h-to").value = state.to;
  state.shown = PAGE; update(true);
}
function presets() {
  const box = $("h-presets"); box.textContent = "";
  const today = zoneDay(new Date().toISOString());
  const back = (days) => zoneDay(new Date(Date.now() - days * 864e5).toISOString());
  const yr = today.slice(0, 4);
  const items = [["Last 7 days", back(7), today], ["Last 30 days", back(30), today], ["Last 12 months", back(365), today]];
  for (let y = Number(yr); y >= FIRST_YEAR; y--) items.push([String(y), `${y}-01-01`, `${y}-12-31`]);
  items.push(["Any date", "", ""]);
  items.forEach(([t, a, b]) => {
    const btn = el("button", "chip-btn" + (state.from === a && state.to === b ? " on" : ""), t); btn.type = "button";
    btn.addEventListener("click", () => setDates(a, b));
    box.appendChild(btn);
  });
  $("h-zone").textContent = `Dates in ${zoneName()}. For one day, set both to it.`;
}

/* Active filters as chips above the map; each removes itself. */
function chips() {
  const box = $("h-chips"); box.textContent = "";
  const add = (text, fn) => {
    const b = el("button", "chip", text); b.type = "button"; b.title = "Remove this filter";
    b.appendChild(el("span", "x", "×")); b.addEventListener("click", fn); box.appendChild(b);
  };
  FACETS.forEach((f) => {
    const sel = state.f[f.k] || [];
    if (f.k === "st") return;
    if (f.k === "kind") {
      if (!sel.length) return;
      const hidden = KINDS.filter((k) => !sel.includes(k));
      add(hidden.length <= sel.length ? `Launch kinds: hiding ${hidden.join(", ")}` : `Launch kinds: only ${sel.join(", ")}`,
        () => { state.f.kind = []; update(true); });
      return;
    }
    sel.forEach((v) => add(`${f.label}: ${f.name ? f.name(v) : v}`, () => { state.f[f.k] = sel.filter((x) => x !== v); update(true); }));
  });
  RANGES.forEach((g) => { if (state.r[g.k]) add(`${g.label}: ${rangeText(g, state.r[g.k])}`, () => setRange(g.k, null, null)); });
  if (state.from || state.to) add(`Dates: ${state.from || "start"} to ${state.to || "now"}`, () => setDates("", ""));
  if (state.q) add(`Search: ${state.q}`, () => { state.q = ""; $("h-q").value = ""; update(true); });
  if (box.childNodes.length) {
    const c = el("button", "linkish small", "Clear all filters"); c.type = "button";
    c.addEventListener("click", () => { state.f = JSON.parse(JSON.stringify(DEFAULT)); state.r = {}; state.q = ""; $("h-q").value = ""; setDates("", ""); });
    box.appendChild(c);
  }
}

/* Launch kinds as one-click toggles above the map: pressed = shown. With none hidden there is no kind filter. */
function kindToggles() {
  const box = $("h-kinds"); if (!box) return; box.textContent = "";
  const counts = new Map();
  filtered("kind").forEach((r) => counts.set(r.kind || NK, (counts.get(r.kind || NK) || 0) + 1));
  const sel = state.f.kind || [];
  const shown = (k) => !sel.length || sel.includes(k);
  box.appendChild(el("span", "small muted", "Show kinds:"));
  KINDS.forEach((k) => {
    const n = counts.get(k) || 0;
    const on = shown(k);
    const b = el("button", "chip-btn kind-btn k-" + kindSlug(k) + (on ? " on" : ""));
    b.type = "button"; b.setAttribute("aria-pressed", on ? "true" : "false");
    b.title = `${on ? "Hide" : "Show"} ${k.toLowerCase()} launches` + ((IX.kind_notes || {})[k] ? ` (${IX.kind_notes[k]})` : "");
    b.append(el("span", "kind-sw"), document.createTextNode((k === NK ? "Kind not known" : k) + " "), el("span", "n", String(n)));
    b.addEventListener("click", () => {
      let next = KINDS.filter((x) => (x === k ? !on : shown(x)));
      if (next.length === KINDS.length) next = [];
      state.f.kind = next; state.shown = PAGE; update(true);
    });
    box.appendChild(b);
  });
  if (sel.length) {
    const all = el("button", "linkish small", "Show all kinds"); all.type = "button";
    all.addEventListener("click", () => { state.f.kind = []; update(true); });
    box.appendChild(all);
  }
}

/* ---------- the month timeline (stacked by country; bars set the date range) ---------- */
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs) => { const e = document.createElementNS(SVGNS, tag); Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v)); return e; };
const GROUPS = ["ru", "us", "cn", "other"]; // stacked bottom to top; this order keeps every adjacent pair apart in both themes
function timeline() {
  const box = $("h-timeline"); box.textContent = "";
  const recs = filtered("date").filter((r) => r._month);
  const now = zoneDay(new Date().toISOString()).slice(0, 7);
  // From the month GCAT's list here starts; earlier months only when the dates reach back.
  const since = (IX.ledger_since || "2012-01").slice(0, 7);
  let first = state.from && state.from.slice(0, 7) < since ? state.from.slice(0, 7) : since, last = now;
  recs.forEach((r) => { if (r._month > last) last = r._month; });
  const months = [];
  for (let y = Number(first.slice(0, 4)), m = Number(first.slice(5)); `${y}-${String(m).padStart(2, "0")}` <= last; m++) {
    if (m > 12) { m = 1; y++; }
    const key = `${y}-${String(m).padStart(2, "0")}`; if (key > last) break; months.push(key);
  }
  const bins = new Map(months.map((k) => [k, { us: 0, cn: 0, ru: 0, other: 0, n: 0 }]));
  let early = 0;
  recs.forEach((r) => { const b = bins.get(r._month); if (b) { b[group(r.actor)]++; b.n++; } else if (r._month < first) early++; });
  const max = Math.max(1, ...[...bins.values()].map((b) => b.n));
  const W = Math.max(320, box.clientWidth || 800), H = 92, padL = 30, padB = 18, plotH = H - padB - 6;
  const bw = (W - padL - 4) / months.length;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img",
    "aria-label": "Launches per month, stacked by country. Drag across months to set the date range; click one month to choose it." });
  // grid and y labels
  const ticks = [0, Math.round(max / 2), max];
  ticks.forEach((t) => {
    const y = 6 + plotH - (t / max) * plotH;
    svg.appendChild(svgEl("line", { x1: padL, x2: W - 4, y1: y, y2: y, class: "tl-grid" }));
    const tx = svgEl("text", { x: padL - 4, y: y + 3, class: "tl-ax", "text-anchor": "end" }); tx.textContent = String(t); svg.appendChild(tx);
  });
  const selFrom = state.from ? state.from.slice(0, 7) : null, selTo = state.to ? state.to.slice(0, 7) : null;
  months.forEach((k, i) => {
    const x = padL + i * bw, b = bins.get(k);
    const inSel = (!selFrom || k >= selFrom) && (!selTo || k <= selTo);
    const g = svgEl("g", { class: "tl-m" + (state.from || state.to ? (inSel ? " in" : " out") : "") + (k > now ? " future" : ""), "data-m": k });
    let y = 6 + plotH;
    const segs = GROUPS.filter((gr) => b[gr]);
    segs.forEach((gr, j) => {
      const h = (b[gr] / max) * plotH;
      const top = j === segs.length - 1;
      const hh = Math.max(1, h - (top ? 0 : 2)); // 2px surface gap between stacked segments
      y -= h;
      const w = Math.max(1, bw - 2);
      if (top && hh > 4) {
        // rounded data-end on the top segment only
        const r = Math.min(3, w / 2);
        svg.appendChild(g);
        g.appendChild(svgEl("path", { class: "tl-bar g-" + gr, d: `M${x + 1},${y + hh} V${y + r} Q${x + 1},${y} ${x + 1 + r},${y} H${x + 1 + w - r} Q${x + 1 + w},${y} ${x + 1 + w},${y + r} V${y + hh} Z` }));
      } else g.appendChild(svgEl("rect", { class: "tl-bar g-" + gr, x: x + 1, y: y + (top ? 0 : 2), width: w, height: hh }));
    });
    g.appendChild(svgEl("rect", { class: "tl-hit", x, y: 0, width: bw, height: H - padB + 4 }));
    const tip = svgEl("title"); tip.textContent = `${monthName(k)}: ${b.n} (US ${b.us}, China ${b.cn}, Russia ${b.ru}, others ${b.other})`; g.appendChild(tip);
    svg.appendChild(g);
    if (k.endsWith("-01") || i === 0) {
      const tx = svgEl("text", { x: x + 1, y: H - 4, class: "tl-ax" }); tx.textContent = k.slice(0, 4); svg.appendChild(tx);
    }
  });
  if (early) { const tx = svgEl("text", { x: W - 4, y: 12, class: "tl-ax", "text-anchor": "end" }); tx.textContent = `${early} before ${first.slice(0, 4)} not drawn: set an earlier year`; svg.appendChild(tx); }
  // brush: drag across months, or click one
  let start = null;
  const monthAt = (ev) => { const t = ev.target.closest && ev.target.closest(".tl-m"); return t ? t.getAttribute("data-m") : null; };
  svg.addEventListener("pointerdown", (ev) => { start = monthAt(ev); if (start) svg.setPointerCapture(ev.pointerId); });
  svg.addEventListener("pointerup", (ev) => {
    if (!start) return;
    const pt = document.elementFromPoint(ev.clientX, ev.clientY);
    const t = pt && pt.closest && pt.closest(".tl-m");
    let end = t ? t.getAttribute("data-m") : start;
    let a = start, b = end; if (a > b) [a, b] = [b, a];
    start = null;
    const lastDay = (m) => { const [y, mo] = m.split("-").map(Number); return `${m}-${String(new Date(Date.UTC(y, mo, 0)).getUTCDate()).padStart(2, "0")}`; };
    if (state.from === `${a}-01` && state.to === lastDay(b)) setDates("", ""); else setDates(`${a}-01`, lastDay(b));
  });
  box.appendChild(svg);
  const lg = el("p", "small muted tl-note", "Launches per month in your filters, by launching country (colours as on the map). Drag across months to set the dates; click a chosen month again to clear.");
  box.appendChild(lg);
}
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthName = (k) => `${MON[Number(k.slice(5)) - 1]} ${k.slice(0, 4)}`;

/* ---------- the list ---------- */
const COLS = [
  { k: "time", label: "When", sort: (r) => r.time || "" },
  { k: "kind", label: "Kind", sort: (r) => KINDS.indexOf(r.kind || NK) },
  { k: "actor", label: "Country", sort: (r) => r.actor || "" },
  { k: "vehicle", label: "Vehicle", sort: (r) => r.vehicle || "" },
  { k: "payload", label: "Payload or mission", sort: (r) => r.payload || r.label || "" },
  { k: "mtype", label: "Type", sort: (r) => r.mtype || "" },
  { k: "site", label: "Site", sort: (r) => r.site || "" },
  { k: "orbit", label: "Orbit", sort: (r) => r.orbit || "" },
];
function when(r) {
  if (!r.time) return "undated";
  if (r.time_basis === "time" || r.time_basis === "net" || r.time_basis === "from notam") return fmt(r.time, { year: true });
  return fmt(r.time, { year: true, time: false }) + (r.time_basis === "month" ? " (month)" : "");
}
function list(rows) {
  const box = $("h-list"); box.textContent = "";
  const col = COLS.find((c) => c.k === state.sort) || COLS[0];
  rows = rows.slice().sort((a, b) => { const x = col.sort(a), y = col.sort(b); return (x < y ? -1 : x > y ? 1 : 0) * state.dir || (a.time < b.time ? 1 : -1); });
  const t = el("table", "h-table"), th = el("thead"), tr = el("tr");
  COLS.forEach((c) => {
    const h = el("th"); const b = el("button", "th-sort", c.label + (state.sort === c.k ? (state.dir < 0 ? " ▾" : " ▴") : "")); b.type = "button";
    b.addEventListener("click", () => { if (state.sort === c.k) state.dir = -state.dir; else { state.sort = c.k; state.dir = c.k === "time" ? -1 : 1; } update(false); });
    h.setAttribute("aria-sort", state.sort === c.k ? (state.dir < 0 ? "descending" : "ascending") : "none");
    h.appendChild(b); tr.appendChild(h);
  });
  const ch = el("th", "h-cmp-col"); ch.appendChild(el("span", "th-plain", "Compare")); tr.appendChild(ch);
  th.appendChild(tr); t.appendChild(th);
  const tb = el("tbody");
  rows.slice(0, state.shown).forEach((r) => {
    const row = el("tr", "pickable" + (r.id === state.sel ? " sel" : "") + (r.status === "upcoming" ? " up" : ""));
    row.tabIndex = 0; row.dataset.id = r.id;
    const w = el("td"); w.appendChild(document.createTextNode(when(r)));
    if (r.status === "upcoming") w.appendChild(el("span", "badge badge-up", r.net_passed ? "NET passed" : "Scheduled"));
    if (r.provisional) w.appendChild(el("span", "badge badge-warn", "Provisional"));
    if (r.status === "notice") w.appendChild(el("span", "badge", "Notice"));
    if (r.cancelled) w.appendChild(el("span", "badge badge-warn", "Cancelled"));
    if (r.outcome && r.outcome !== "success") w.appendChild(el("span", "badge badge-warn", r.outcome === "failure" ? "Failure" : r.outcome));
    const c = el("td"); c.appendChild(mark(r.actor));
    const pay = el("td", "", r.payload || (r.status === "notice" ? r.label : "") || (r.sources[0] === "nfc" ? "not given" : ""));
    if ((r.programmes || []).length) pay.title = "Programme: " + r.programmes.join(", ");
    const kd = el("td"); kd.appendChild(el("span", "kind-tag k-" + kindSlug(r.kind), r.kind || NK));
    row.append(w, kd, c, el("td", "", r.vehicle || ""), pay, el("td", "", r.mtype), el("td", "", r.site || ""), el("td", "", r.orbit || ""));
    const cc = el("td", "h-cmp-col"); cc.appendChild(cmpButton(r, true)); row.appendChild(cc);
    row.addEventListener("click", () => select(r.id, true));
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") select(r.id, true); });
    tb.appendChild(row);
  });
  t.appendChild(tb); box.appendChild(t);
  const more = $("h-more"); more.hidden = rows.length <= state.shown;
  more.textContent = `Show ${Math.min(PAGE, rows.length - state.shown)} more of ${rows.length - state.shown}`;
}

/* ---------- the detail card ---------- */
function fact(dl, k, v) { if (v === null || v === undefined || v === "") return; dl.append(el("dt", "", k), v instanceof Node ? (() => { const d = el("dd"); d.appendChild(v); return d; })() : el("dd", "", String(v))); }
function quick(label, k, v) {
  const b = el("button", "chip-btn", label); b.type = "button"; b.title = "Show only launches with this " + k;
  b.addEventListener("click", () => { state.f[k] = [v]; state.sel = ""; update(true); });
  return b;
}
/* How a charted event joined its launch (catalog.py build_index: passes 1, 0, 2, 4 in that order). */
function joinText(j) {
  if (!j) return "joined";
  const off = j.hours > 1 ? `; the charted time is ${j.hours >= 8000 ? "about a year" : j.hours + " h"} out` : "";
  if (j.pass === 0) return (j.via === "nfc" ? "by a NOTAM NotamForChina lists for this launch" : "by a NOTAM Joey0609/notams' copy places in this launch's window") + " (same number and FIR)" + off;
  if (j.pass === 4) return `no pad was charted: the same ${j.by === "programme" ? "programme" : "vehicle"}, nearest in time (${j.hours} h from the charted window)`;
  return `${j.hours} h apart` + (j.nm !== null && j.nm !== undefined ? `, ${j.nm} NM apart` : "") + (j.same ? ", same vehicle or programme" : "")
    + (j.pass === 2 ? " (matched by vehicle and place; the charted time differs)" : "");
}
function detail(r) {
  const box = $("h-detail"); box.textContent = "";
  if (!r) { box.hidden = true; return; }
  box.hidden = false;
  const head = el("div", "d-head");
  head.appendChild(el("h3", "", r.payload && r.vehicle && r.vehicle !== NK ? `${r.vehicle} · ${r.payload}` : r.label || r.payload || "Launch"));
  const x = el("button", "linkish d-close", "Close"); x.type = "button"; x.addEventListener("click", () => select("", false));
  const acts = el("span", "d-acts"); acts.append(cmpButton(r, false), x);
  head.appendChild(acts); box.appendChild(head);
  const meta = el("p", "small who"); meta.appendChild(mark(r.actor));
  meta.appendChild(document.createTextNode(`${countryName(r.actor)} · ${STATUS[r.status] || r.status}` + (r.provisional ? " · provisional: Launch Library 2 reports it flown; GCAT has not listed it yet" : "")));
  box.appendChild(meta);
  const dl = el("dl", "facts");
  if (r.notice_set) fact(dl, "Launch", r.notice_set === "later" ? "none identified yet: no launch is joined to these charted notices"
    : "none followed, or not identified: no GCAT launch joins these charted notices (a scrub, a slip of more than 72 h, a cancellation, or a launch never identified)");
  fact(dl, r.status === "upcoming" ? "NET" : "When", when(r) + (r.status === "upcoming" && r.net_precision ? ` (precision: ${r.net_precision})` : ""));
  if (r.chart_time) fact(dl, "Charted time", `${fmt(r.chart_time, { year: true })}: the time in the charted name; GCAT's launch time is shown above`);
  fact(dl, r.notice_set ? "Charted vehicle" : "Vehicle", [r.vehicle, r.gcat_vehicle && r.gcat_vehicle !== r.vehicle ? `(GCAT: ${r.gcat_vehicle})` : "", r.ll2_vehicle && r.ll2_vehicle !== r.vehicle ? `(LL2: ${r.ll2_vehicle})` : ""].filter(Boolean).join(" "));
  fact(dl, "Kind", (r.kind || NK) + ((IX.kind_notes || {})[r.kind || NK] ? `: ${IX.kind_notes[r.kind || NK]}` : "") + (r.gcat_category ? ` · GCAT category: ${r.gcat_category}` : ""));
  fact(dl, "Site", [r.site, r.pad_name].filter(Boolean).join(" · ") + (r.pad ? ` (${r.pad[1].toFixed(2)}, ${r.pad[0].toFixed(2)}${r.pad_basis === "site" ? ", site position" : r.pad_basis === "region" ? ": a region GCAT gives, not a pad" : ""})` : "")
    + (r.site_uncertain ? " · GCAT gives this site with a question mark" : "")
    + (r.site_fix ? ` · corrected: GCAT gives ${[r.site_fix.gcat_site, r.site_fix.gcat_pad].filter(Boolean).join(" ")}; ${r.site_fix.publisher}${r.site_fix.date ? ` (${r.site_fix.date})` : ""} reports this site` : ""));
  if (r.apogee_km != null || r.range_km != null) fact(dl, "Apogee and range", [r.apogee_km != null ? `apogee about ${r.apogee_km.toLocaleString("en-US")} km` : "", r.range_km != null ? `range about ${r.range_km.toLocaleString("en-US")} km` : ""].filter(Boolean).join(", ") + " (GCAT)");
  fact(dl, r.notice_set ? "Charted payload" : "Payload", r.payload);
  if (r.payloads && r.payloads.count) fact(dl, "Payloads (GCAT)", `${r.payloads.count}: ${r.payloads.names.join(", ")}${r.payloads.more ? ` and ${r.payloads.more} more` : ""}`);
  const notes = (r.programmes || []).map((p) => IX.programme_notes[p] ? `${p} (${IX.programme_notes[p]})` : p);
  fact(dl, "Type", r.mtype + (notes.length ? ` · ${notes.join(", ")}` : ""));
  fact(dl, "Orbit", r.orbit + (r.inc ? ` · payload inclination ${r.inc}° (GCAT)` : ""));
  if (r.outcome) fact(dl, "Outcome", r.outcome);
  if (r.far_nm !== undefined) fact(dl, "Farthest closure area", `${r.far_nm.toLocaleString("en-US")} NM from the pad`);
  if (r.path) fact(dl, "Flight path", (r.path.via && r.path.via.length
    ? `estimated: through ${r.path.via.length} point${r.path.via.length === 1 ? "" : "s"}, then on ${r.path.az}°, drawn ${r.path.nm} NM in all`
    : `estimated: azimuth ${r.path.az}°, drawn ${r.path.nm} NM`) + ` · ${r.path.basis}`);
  else if (r.notice_set) fact(dl, "Flight path", "none: a set of notices, not a launch");
  else if (r.kind && r.kind !== "Orbital" && r.kind !== NK) fact(dl, "Flight path", "none: a suborbital flight's path is drawn only towards its closure areas, and this one has none");
  else fact(dl, "Flight path", r.pad ? "none: no closure area, inclination or corridor history to infer an azimuth from" : "none: no pad position");
  if (r.over) {
    const one = (p) => (p.length ? p.map((o) => `${countryName(o.cc)} ${o.from.toLocaleString("en-US")}–${o.to.toLocaleString("en-US")} NM`).join(", ") : "no land");
    fact(dl, "Path crosses", one(r.over[0])
      + ". Land under the ground track, NM from the path's start (Natural Earth's de facto borders). Not airspace: a few hundred NM out the vehicle is in space.");
  }
  if (r.chart_joins) fact(dl, "Charted notices joined", r.chart.map((id, i) => `${(chartById.get(id) || [{}])[0].label || id}: ${joinText(r.chart_joins[i])}`).join("; "));
  else if (r.join && r.gcat) fact(dl, "Charted notices joined", joinText(r.join));
  if (r.gcat) fact(dl, "GCAT", r.gcat);
  if (r.ll2_url) { const a = el("a", "", "Launch Library 2 record (JSON)"); a.href = r.ll2_url; a.rel = "noopener"; fact(dl, "Schedule", a); }
  fact(dl, "Sources", r.sources.map((s) => SOURCES[s] || s).join(" · "));
  box.appendChild(dl);
  const q = el("p", "quick small"); q.appendChild(document.createTextNode("Show only: "));
  if (r.kind && r.kind !== NK) q.appendChild(quick(`Kind: ${r.kind}`, "kind", r.kind));
  if (r.vehicle && r.vehicle !== NK) q.appendChild(quick(r.vehicle, "veh", r.vehicle));
  if (r.site) q.appendChild(quick(r.site, "site", r.site));
  (r.programmes || []).forEach((p) => q.appendChild(quick(p, "prog", p)));
  if (r.actor) q.appendChild(quick(countryName(r.actor), "cc", r.actor));
  box.appendChild(q);
  [...new Map((r.closures || []).map((c) => [`${c.area}|${(c.window || []).join()}`, c])).values()].forEach((c) => box.appendChild(el("p", "small", `Closure area ${c.area} coincided in ${c.level}` + (c.window ? ` (${span(c.window[0], c.window[1])})` : "") + ". Coincidence, not proof the area was for this launch.")));
  const evs = (r.chart || []).flatMap((id) => chartById.get(id) || []);
  const nfcN = r.nfc_notices || [];
  const nfcFor = (num) => nfcN.find((x) => x.chart && x.number === num);
  const joeyN = r.joey_notices || [];
  const joeyFor = (num) => joeyN.find((x) => x.chart && x.number === num);
  if (evs.length) {
    box.appendChild(el("h4", "", `Charted: ${r.areas} closure area${r.areas === 1 ? "" : "s"}, ${evs.reduce((n, e) => n + e.notams.length, 0)} notice(s)`));
    if (r.chart_labels) box.appendChild(el("p", "small muted", "Charted as: " + r.chart_labels.join("; ")));
    const seen = new Set();
    evs.forEach((e) => {
      e.notams.forEach((n) => {
        if (seen.has(n.number + n.text.slice(0, 40))) return; seen.add(n.number + n.text.slice(0, 40));
        const d = el("details", "notam");
        d.appendChild(el("summary", "", (n.number || "Notice") + (n.q ? ` · ${n.q.fir} · ${n.q.code}` : "") + (n.start ? ` · ${fmt(n.start)} to ${fmt(n.end)}` : "")));
        if (n.relayed) d.appendChild(el("p", "small badge-warn", `Relayed: issued by ${countryName(n.issuing_state)} for ${n.named_states.map(countryName).join(", ")}.`));
        (n.checks || []).forEach((c) => d.appendChild(el("p", "small muted", "Check: " + c)));
        const x = n.number && nfcFor(n.number);
        if (x) d.appendChild(el("p", "small muted", "Check: " + nfcCheck(x)));
        const jx = n.number && joeyFor(n.number);
        if (jx) d.appendChild(el("p", "small muted", "Check: " + joeyCheck(jx)));
        d.appendChild(el("pre", "", n.text));
        box.appendChild(d);
      });
      e.texts.forEach((t) => { const d = el("details", "notam"); d.append(el("summary", "", "Warning or note"), el("pre", "", t)); box.appendChild(d); });
    });
    const links = [...new Set(evs.flatMap((e) => e.links))];
    if (links.length) {
      const p = el("p", "small"); p.appendChild(document.createTextNode("Sources: "));
      links.forEach((u, i) => { try { const a = el("a", "", new URL(u).hostname); a.href = u; a.rel = "noopener"; if (i) p.appendChild(document.createTextNode(" · ")); p.appendChild(a); } catch { /* bad link */ } });
      box.appendChild(p);
    }
    const wh = evs.reduce((n, e) => n + (e.withheld_notes || 0), 0);
    if (wh) box.appendChild(el("p", "muted small", `${wh} note(s) on the source map are not public notices and are not shown.`));
  }
  if ((r.forum || []).length) {
    const p = el("p", "small"); p.appendChild(document.createTextNode(`Forum thread${r.forum.length > 1 ? "s" : ""}: `));
    r.forum.forEach((f, i) => { const a = el("a", "", f.title); a.href = f.url; a.rel = "noopener"; if (i) p.appendChild(document.createTextNode(" · ")); p.appendChild(a); });
    p.appendChild(document.createTextNode(" (NASASpaceflight forum, from NotamForChina's list of its threads; linked, not read)"));
    box.appendChild(p);
  }
  if (joeyN.some((x) => !x.chart)) joeySection(box, r, joeyN, nfcN);
  if ((r.archive_notices || []).length) archiveSection(box, r.archive_notices);
  if ((r.published_notices || []).length) publishedSection(box, r.published_notices);
  if (r.nfc) nfcSection(box, r, nfcN);
  if ((r.saved_notices || []).length) savedSection(box, r);
}

/* Notices pasted on the Paste tab and saved in this browser (saved.js). Only this browser has them. */
function savedSection(box, r) {
  const all = r.saved_notices;
  box.appendChild(el("h4", "", `Saved in this browser: ${all.length} notice${all.length === 1 ? "" : "s"}`));
  all.forEach((n) => {
    const d = el("details", "notam");
    d.appendChild(el("summary", "", (n.number || "Notice") + (n.firs.length ? ` · ${n.firs.join(" ")}` : "") + (n.q_code ? ` · ${n.q_code}` : "") + (n.start ? ` · ${fmt(n.start)} to ${n.end ? fmt(n.end) : "?"}` : "")));
    if (n.join) d.appendChild(el("p", "small muted", "Its launch: " + joeyJoin(n.join) + "."));
    else d.appendChild(el("p", "small muted", "No launch here fits its window and area: a notice with no identified launch."));
    if (!n.rings.length && !n.points.length) d.appendChild(el("p", "small muted", "No area read from its text."));
    d.appendChild(el("pre", "", n.text));
    const p = el("p", "small"); const b = el("button", "linkish", "Remove from this browser"); b.type = "button";
    b.addEventListener("click", () => { SV.store(SV.load().filter((x) => x.id !== n.id)); savedChanged(); window.dispatchEvent(new Event("launch:saved")); });
    p.appendChild(b); d.appendChild(p);
    box.appendChild(d);
  });
  box.appendChild(el("p", "small muted", "Saved from the Paste tab, kept in this browser's storage only: nobody else sees them, and clearing site data removes them. The Paste tab can export them to a file."));
}

/* Saved notices: undo the last application, then join the current ones (saved.js). Returns the join counts. */
let savedOwn = [], savedOn = [];
const recNumbers = (r) => [
  ...(r.chart || []).flatMap((id) => chartById.get(id) || []).flatMap((e) => e.notams.map((n) => ({ number: n.number, firs: [(n.q || {}).fir].filter(Boolean) }))),
  ...(r.joey_notices || []).map((n) => ({ number: n.number, firs: [n.fir, ...(n.locations || [])].filter(Boolean) })),
  ...(r.nfc_notices || []).map((n) => ({ number: n.number, firs: (n.fir || "").split("/").filter(Boolean) })),
];
function applySaved() {
  const touched = savedOwn.map((r) => r.id).concat(savedOn.map((r) => r.id));
  if (savedOwn.length) { const gone = new Set(savedOwn.map((r) => r.id)); IX.records = IX.records.filter((r) => !gone.has(r.id)); gone.forEach((id) => byId.delete(id)); }
  savedOn.forEach((r) => { delete r.saved_notices; r.sources = r.sources.filter((s) => s !== "saved"); r._hay = null; });
  const notices = SV.load().map(SV.read).filter(Boolean);
  const { byRecord, own } = SV.join(notices, IX.records, recNumbers);
  savedOn = [];
  byRecord.forEach((xs, id) => { const r = byId.get(id); if (!r) return; r.saved_notices = xs; if (!r.sources.includes("saved")) r.sources.push("saved"); r._hay = null; savedOn.push(r); });
  savedOwn = own;
  own.forEach((r) => { r._day = zoneDay(r.time); r._month = r._day.slice(0, 7); IX.records.push(r); byId.set(r.id, r); });
  if (map) map.forget(touched.concat(savedOn.map((r) => r.id), own.map((r) => r.id)));
  return { saved: notices.length, joined: notices.length - own.length, own: own.length };
}
function savedChanged() { const c = applySaved(); update(false); return c; }

/* Joey0609/notams' notices on a record: the NOTAM's own text, FIRs, window and area. One also charted is a check
   under the charted notice; NotamForChina's copy of one is a check under it. */
function joeyCheck(x) {
  const agree = IX.joey ? IX.joey.agree_nm : 5;
  if (x.gap_nm === undefined) return "Joey0609/notams lists this notice too.";
  return x.gap_nm <= agree ? `Joey0609/notams holds this notice too; its area lies within ${x.gap_nm} NM of the charted one.`
    : `Joey0609/notams holds this notice too, its area up to ${x.gap_nm} NM from the charted one: one of the two may be drawn for another notice.`;
}
function joeyJoin(j) {
  if (!j) return "";
  if (j.by === "notam") return "joined by its NOTAM (same number and FIR) on this launch's charted or NotamForChina notices";
  const t = j.after_start_h;
  return `joined by window and place: the launch came ${Math.abs(t)} h ${t < 0 ? "before the window opened" : "after it opened"}`
    + (j.nm !== null && j.nm !== undefined ? `, ${j.nm} NM from the pad` : "") + (j.candidates > 1 ? ` (nearest of ${j.candidates} launches in the window)` : "");
}
/* FAA space-operations TFRs and NGA warnings read from Internet Archive copies, each linked to its capture. */
function archiveSection(box, all) {
  box.appendChild(el("h4", "", `From Internet Archive copies: ${all.length} notice${all.length === 1 ? "" : "s"}`));
  all.forEach((n) => {
    const d = el("details", "notam");
    const when = n.kind === "faa-tfr" ? (n.start ? ` · ${fmt(n.start)} to ${fmt(n.end)}` : "")
      : ((n.windows || [])[0] ? ` · ${span(n.windows[0].start, n.windows[0].end)}` + (n.windows.length > 1 ? ` (+${n.windows.length - 1} more)` : "") : "");
    d.appendChild(el("summary", "", (n.kind === "faa-tfr" ? `FAA TFR ${n.number || ""}` : `NGA ${n.id}`) + when));
    if (n.join) d.appendChild(el("p", "small muted", "Its launch: " + joeyJoin(n.join) + "."));
    if (n.location) d.appendChild(el("p", "small", n.location + (n.reason ? ` · ${n.reason}` : "")));
    if (n.chart) d.appendChild(el("p", "small muted", "Check: the charted notices hold this warning too."));
    if (n.text) d.appendChild(el("pre", "", n.text));
    if (n.source) { const p = el("p", "small"); const a = el("a", "", "Archived copy"); a.href = n.source; a.rel = "noopener"; p.appendChild(a); d.appendChild(p); }
    box.appendChild(d);
  });
  box.appendChild(el("p", "small muted", "Read from the Internet Archive's copies of tfr.faa.gov and msi.nga.mil: samples, not a complete record."));
}
/* Closure areas no other source carries, each copied from a published copy of its notice (history/published_notices.json). */
function publishedSection(box, all) {
  box.appendChild(el("h4", "", `Published notices: ${all.length} area${all.length === 1 ? "" : "s"}`));
  all.forEach((n) => {
    const d = el("details", "notam");
    const w = (n.windows || [])[0];
    d.appendChild(el("summary", "", `${n.number} · ${n.issuer}` + (n.stage ? ` · ${n.stage}` : "") + (w ? ` · ${fmt(w[0])} to ${fmt(w[1])}` : "")));
    if (n.schedule) d.appendChild(el("p", "small", `Daily ${n.schedule} UTC.`));
    if (n.note) d.appendChild(el("p", "small muted", n.note));
    const s = n.source || {};
    if (s.url) { const p = el("p", "small"); p.appendChild(document.createTextNode("Copied from: ")); const a = el("a", "", `${s.publisher}, ${s.title}` + (s.date ? ` (${s.date})` : "")); a.href = s.url; a.rel = "noopener"; p.appendChild(a); d.appendChild(p); }
    box.appendChild(d);
  });
  box.appendChild(el("p", "small muted", "Checked against the published copy " + (all[0].reviewed || "") + "; the notice's own text is the record."));
}
function joeySection(box, r, all, nfcN) {
  const own = all.filter((x) => !x.chart);
  box.appendChild(el("h4", "", `From Joey0609/notams: ${own.length} notice${own.length === 1 ? "" : "s"}` + (all.length > own.length ? ` (and ${all.length - own.length} charted above)` : "")));
  own.forEach((n) => {
    const d = el("details", "notam");
    const firs = [...new Set([n.fir, ...(n.locations || [])].filter((f) => f && f !== "ZXXX"))].join(" ");
    d.appendChild(el("summary", "", (n.number || "Notice") + (n.part ? ` (${n.part})` : "") + (firs ? ` · ${firs}` : "") + (n.q_code ? ` · ${n.q_code}` : "") + (n.start ? ` · ${fmt(n.start)} to ${fmt(n.end)}` : "")));
    if (n.join) d.appendChild(el("p", "small muted", "Its launch: " + joeyJoin(n.join) + "."));
    if (n.named_states && n.named_states.length && n.issuing_state && !n.named_states.includes(n.issuing_state)) d.appendChild(el("p", "small badge-warn", `Relayed: issued by ${countryName(n.issuing_state)} for ${n.named_states.map(countryName).join(", ")}.`));
    if (n.schedule) d.appendChild(el("p", "small", "Schedule: " + n.schedule));
    const x = n.number && nfcN.find((y) => y.joey && y.number === n.number);
    if (x) d.appendChild(el("p", "small muted", "Check: " + nfcCheck(x)));
    if (!(n.rings || []).length) d.appendChild(el("p", "small muted", "No area read from its text."));
    d.appendChild(el("pre", "", n.text || ""));
    box.appendChild(d);
  });
  box.appendChild(el("p", "small muted", "Joey0609/notams (MIT) keeps the NOTAMs as the FAA's NOTAM search returned them; Launch keeps the launch-related ones and reads their areas. Credit on the Sources tab."));
}

/* NotamForChina's notices on a record: numbers, FIRs, windows and charted areas (it carries no NOTAM text). Those
   also charted are shown under the charted notice, as a check. */
const NFC_JOIN = {
  tag: (r) => `joined to GCAT ${r.gcat} by NotamForChina`,
  vehicle: (r, j) => `joined to GCAT ${r.gcat}: same vehicle, ${j.hours} h apart`,
  slip: (r, j) => `joined to GCAT ${r.gcat}: same vehicle and site, ${j.hours} h apart (NotamForChina's time may be the planned one)`,
  notam: () => "joined by a NOTAM charted for this launch (same number and FIR)",
  chart: (r, j) => `joined to a charted event: ${j.hours} h apart`,
};
function nfcCheck(x) {
  if (x.joey) return x.gap_nm !== undefined
    ? `NotamForChina lists this notice too; its charted area lies ${x.gap_nm <= (IX.nfc ? IX.nfc.agree_nm : 5) ? "within" : "up to"} ${x.gap_nm} NM of the area read from the text.`
    : "NotamForChina lists this notice too" + (x.start ? ` (${span(x.start, x.end)})` : "") + ".";
  if (x.gap_nm !== undefined) {
    const agree = IX.nfc ? IX.nfc.agree_nm : 5;
    return x.gap_nm <= agree ? `NotamForChina charts this notice too; its corners lie within ${x.gap_nm} NM of the charted area.`
      : `NotamForChina charts this notice up to ${x.gap_nm} NM from the charted area: one of the two may be drawn for another notice.`;
  }
  if (x.ring) return "NotamForChina charts this notice; Launch has no charted area for it, so NotamForChina's is drawn.";
  return "NotamForChina lists this notice" + (x.start ? ` (${span(x.start, x.end)})` : "") + ".";
}
function nfcSection(box, r, all) {
  const own = all.filter((x) => !x.chart && !x.joey);
  const charted = own.filter((x) => x.ring).length;
  box.appendChild(el("h4", "", `From NotamForChina: ${own.length} notice${own.length === 1 ? "" : "s"}, ${charted} charted` + (all.length > own.length ? ` (and ${all.length - own.length} shown above)` : "")));
  const j = r.nfc_join;
  if (j && NFC_JOIN[j.by]) box.appendChild(el("p", "small muted", "Its launch record is " + NFC_JOIN[j.by](r, j) + "."));
  else if (r.nfc_unmatched) box.appendChild(el("p", "small badge-warn", "GCAT lists no launch of this vehicle near this time, so these notices have no identified launch: an attempt that was scrubbed or moved, or a sheet entry made ahead of a launch."));
  else if (r.sources[0] === "nfc") box.appendChild(el("p", "small muted", `GCAT's list on this page starts in ${(IX.ledger_since || "2012").slice(0, 4)}, so this launch stands on NotamForChina's record: its time, vehicle and site.`));
  if (own.length) {
    const ul = el("ul", "plain nfc-list small");
    own.forEach((x) => {
      const li = el("li");
      li.appendChild(el("b", "", x.number || "Notice"));
      const bits = [x.fir, x.label, x.start ? `${span(x.start, x.end)}` : "", x.ring ? "charted" : "no area"].filter(Boolean);
      li.appendChild(document.createTextNode(" · " + bits.join(" · ") + (x.folded ? " (window from the sheet, area from the map)" : "")));
      ul.appendChild(li);
    });
    box.appendChild(ul);
  }
  box.appendChild(el("p", "small muted", "NotamForChina (Apache-2.0) gives numbers, FIRs, windows and the areas as charted; it carries no NOTAM text. Credit on the Sources tab."));
}

function select(id, fly) {
  state.sel = id || "";
  const r = byId.get(state.sel) || null;
  if (map) map.select(r, (r && (r.chart || []).flatMap((x) => chartById.get(x) || [])) || [], fly);
  document.querySelectorAll("#h-list tr.sel").forEach((t) => t.classList.remove("sel"));
  if (r) { const row = document.querySelector(`#h-list tr[data-id="${CSS.escape(r.id)}"]`); if (row) row.classList.add("sel"); }
  detail(r);
  writeHash();
  if (r && window.matchMedia("(max-width: 1099px)").matches) $("h-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------- compare (sidebyside.js): up to four launches side by side ---------- */
const kmNum = (v) => (v === null || v === undefined ? "" : v.toLocaleString("en-US"));
const CMP_FIELDS = [
  { label: "When", get: (r) => when(r) },
  { label: "Kind", get: (r) => r.kind || NK },
  { label: "Country", get: (r) => countryName(r.actor) },
  { label: "Vehicle", get: (r) => r.vehicle },
  { label: "Payload or mission", get: (r) => r.payload || r.label },
  { label: "Payloads (GCAT)", get: (r) => (r.payloads && r.payloads.count ? r.payloads.count : "") },
  { label: "Mission type", get: (r) => r.mtype },
  { label: "Programme", get: (r) => (r.programmes || []).join(", ") },
  { label: "Site", get: (r) => [r.site, r.pad_name].filter(Boolean).join(" · ") },
  { label: "Orbit", get: (r) => r.orbit },
  { label: "Inclination (GCAT)", get: (r) => (r.inc !== null && r.inc !== undefined ? `${r.inc}°` : "") },
  { label: "Apogee (GCAT)", get: (r) => (r.apogee_km !== null && r.apogee_km !== undefined ? `about ${kmNum(r.apogee_km)} km` : "") },
  { label: "Outcome", get: (r) => (r.status === "upcoming" ? "Scheduled" : r.outcome ? r.outcome.replace(/^./, (c) => c.toUpperCase()) : NK) },
  { label: "Charted closure areas", get: (r) => r.areas || 0 },
  { label: "Farthest closure area", get: (r) => (r.far_nm !== undefined ? `${kmNum(r.far_nm)} NM` : "") },
  { label: "Flight path", get: (r) => (r.path ? `estimated, azimuth ${r.path.az}°` + (r.path.borrowed ? " (from an earlier launch)" : "") : "None") },
  { label: "Path crosses", get: (r) => (!r.over ? "" : [...new Set(r.over.flat().map((o) => o.cc))].map(countryName).join(", ") || "No land") },
  { label: "Sources", get: (r) => (r.sources || []).map((x) => SOURCES[x] || x).join(", ") },
];
let cmpNote = "";
function cmpToggle(id) {
  const t = CMP.toggle(state.cmp, id);
  state.cmp = t.ids;
  cmpNote = t.full ? `The tray holds ${CMP.MAX}: take one out to add another.` : "";
  cmpTray();
  document.querySelectorAll("[data-cmp]").forEach((b) => cmpLabel(b));
  writeHash();
}
function cmpLabel(b) {
  const on = state.cmp.includes(b.dataset.cmp);
  b.textContent = b.dataset.short ? (on ? "✓" : "+") : on ? "Remove from compare" : "Add to compare";
  b.setAttribute("aria-pressed", on ? "true" : "false");
  b.setAttribute("aria-label", (on ? "Remove " : "Add ") + b.dataset.name + (on ? " from compare" : " to compare"));
  b.title = on ? "In the compare tray: click to take it out" : "Add to the compare tray (up to four)";
}
function cmpButton(r, short) {
  const b = el("button", short ? "chip-btn cmp-btn" : "linkish"); b.type = "button";
  b.dataset.cmp = r.id; if (short) b.dataset.short = "1";
  b.dataset.name = r.label || r.payload || r.id;
  cmpLabel(b);
  b.addEventListener("click", (ev) => { ev.stopPropagation(); cmpToggle(r.id); });
  b.addEventListener("keydown", (ev) => ev.stopPropagation());
  return b;
}
let cmpKey = null;
function cmpTray() {
  const recs = state.cmp.map((id) => byId.get(id)).filter(Boolean);
  const key = recs.map((r) => r.id).join(",") + "|" + cmpNote;
  if (key === cmpKey) return;
  cmpKey = key;
  const st = $("h-cmp-status");
  if (st) st.textContent = cmpNote || (recs.length ? `Compare (${recs.length} of ${CMP.MAX})` : "Compare tray empty");
  const box = $("h-cmp"); box.textContent = "";
  box.hidden = !recs.length && !cmpNote;
  if (box.hidden) return;
  const head = el("div", "cmp-head");
  head.appendChild(el("b", "", `Compare (${recs.length} of ${CMP.MAX})`));
  const clear = el("button", "linkish small", "Clear"); clear.type = "button";
  clear.addEventListener("click", () => { state.cmp = []; cmpNote = ""; cmpTray(); document.querySelectorAll("[data-cmp]").forEach(cmpLabel); writeHash(); });
  head.appendChild(clear);
  box.appendChild(head);
  if (cmpNote) box.appendChild(el("p", "small warn-text", cmpNote));
  if (recs.length < 2) { box.appendChild(el("p", "small muted", "Add another launch with + in the list or \"Add to compare\" on its card to see them side by side.")); }
  const t = el("table", "cmp-table"), tr = el("tr");
  tr.appendChild(el("th", "", ""));
  recs.forEach((r) => {
    const h = el("th"); h.scope = "col";
    const name = el("button", "linkish", r.label || r.payload || r.id); name.type = "button";
    name.addEventListener("click", () => select(r.id, true));
    const x = el("button", "linkish small", "Remove"); x.type = "button";
    x.setAttribute("aria-label", `Remove ${r.label || r.payload || r.id} from compare`);
    x.addEventListener("click", () => cmpToggle(r.id));
    h.append(mark(r.actor), " ", name, el("br"), x);
    tr.appendChild(h);
  });
  const thead = el("thead"); thead.appendChild(tr); t.appendChild(thead);
  const tb = el("tbody");
  CMP.rows(recs, CMP_FIELDS).forEach((row) => {
    const rtr = el("tr", row.differ ? "differ" : "");
    const rh = el("th", "", row.label); rh.scope = "row"; rtr.appendChild(rh);
    row.cells.forEach((c) => rtr.appendChild(el("td", "", c)));
    tb.appendChild(rtr);
  });
  t.appendChild(tb);
  const wrap = el("div", "tbl-wrap"); wrap.appendChild(t);
  box.appendChild(wrap);
  if (recs.length > 1) box.appendChild(el("p", "small muted", "Rows where the launches differ are marked. Facts are as the list gives them: GCAT's for inclination and apogee, Launch's estimates for the flight path."));
}

/* ---------- the chart builder (chart.js): the launches in the filters, counted and split ---------- */
const facetGet = (k) => FACETS.find((f) => f.k === k).get;
const facetName = (k) => (FACETS.find((f) => f.k === k) || {}).name || ((v) => v);
const CHART_BY = [
  { k: "year", label: "Year", time: "year", get: (r) => (r._day || "").slice(0, 4) },
  { k: "month", label: "Month", time: "month", get: (r) => r._month || "" },
  { k: "cc", label: "Country", facet: true },
  { k: "veh", label: "Vehicle", facet: true },
  { k: "site", label: "Launch site", facet: true },
  { k: "orb", label: "Orbit", facet: true },
  { k: "kind", label: "Launch kind", facet: true },
  { k: "mt", label: "Mission type", facet: true },
  { k: "out", label: "Outcome", facet: true },
  { k: "prog", label: "Programme", facet: true },
  { k: "ovf", label: "Path crosses", facet: true },
];
const OUT_ORDER = ["Success", "Failure or partial", "Scheduled", NK];
const CHART_SPLIT = [
  { k: "", label: "Nothing" },
  { k: "cc", label: "Country (US, China, Russia, others)", get: (r) => group(r.actor), order: ["us", "cn", "ru", "other"], name: (v) => ({ us: "US", cn: "China", ru: "Russia", other: "Others" })[v] || v, cls: (v) => "g-" + v },
  { k: "kind", label: "Launch kind", get: (r) => r.kind || NK, order: KINDS },
  { k: "out", label: "Outcome", get: (r) => facetGet("out")(r), order: OUT_ORDER },
  { k: "orb", label: "Orbit", get: (r) => r.orbit || NK },
];
const DEFAULT_CHART = { by: "year", split: "cc" };
function chartSetup() {
  const by = $("h-chart-by"), sp = $("h-chart-split");
  CHART_BY.forEach((b) => by.appendChild(new Option(b.label, b.k)));
  CHART_SPLIT.forEach((b) => sp.appendChild(new Option(b.label, b.k)));
  const box = $("h-chart");
  box.open = !!state.chart;
  box.addEventListener("toggle", () => {
    if (box.open && !state.chart) state.chart = { ...DEFAULT_CHART };
    if (!box.open) state.chart = null;
    chartView(); writeHash();
  });
  const changed = () => { state.chart = { by: by.value, split: sp.value }; chartView(); writeHash(); };
  by.addEventListener("change", changed); sp.addEventListener("change", changed);
}
function chartView() {
  const box = $("h-chart-out");
  if (!box) return;
  $("h-chart").open = !!state.chart;
  if (!state.chart) { box.textContent = ""; return; }
  const by = CHART_BY.find((b) => b.k === state.chart.by) || CHART_BY[0], sp = CHART_SPLIT.find((b) => b.k === state.chart.split) || CHART_SPLIT[0];
  $("h-chart-by").value = by.k; $("h-chart-split").value = sp.k;
  const get = by.facet ? facetGet(by.k) : by.get, nameOf = by.facet ? facetName(by.k) : by.time === "month" ? monthName : (v) => v;
  const agg = CH.aggregate(lastFiltered, { x: get, split: sp.get || null, time: by.time || null, top: 15, splitTop: 6, order: sp.order || null });
  const label = (k) => (k === CH.OTHER ? `${agg.folded} others` : String(nameOf(k)));
  const sName = (s) => (s === CH.OTHER ? "Others" : sp.name ? sp.name(s) : s || "Launches");
  const sCls = (s, i) => (s === CH.OTHER ? "g-other" : sp.cls ? sp.cls(s) : !sp.get ? "cs-1" : "cs-" + (i + 1));
  box.textContent = "";
  if (!agg.cats.length) { box.appendChild(el("p", "small muted", "No launch in the filters has this field.")); return; }
  const series = agg.series.map((s, i) => ({ s, cls: sCls(s, i) }));
  const max = Math.max(1, ...agg.cats.map((c) => c.total)), tk = CH.ticks(max), top = tk[tk.length - 1];
  const W = Math.max(320, box.clientWidth || 760);
  const svg = svgEl("svg", { width: "100%", role: "img", class: "ch-svg",
    "aria-label": `Launches in your filters by ${by.label.toLowerCase()}` + (sp.get ? `, split by ${sp.label.toLowerCase()}` : "") + ". The table below gives every number." });
  const tip = (c) => `${label(c.key)}: ${c.total}` + (sp.get ? " (" + series.filter((x) => c.parts[x.s]).map((x) => `${sName(x.s)} ${c.parts[x.s]}`).join(", ") + ")" : "");
  const keyPick = (g, c) => {
    if (c.key === CH.OTHER || !c.total) return;
    g.setAttribute("tabindex", "0"); g.setAttribute("role", "button"); g.setAttribute("aria-label", tip(c) + ". Show only these.");
    g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(c); } });
  };
  const pick = (c) => {
    if (c.key === CH.OTHER || !c.total) return;
    if (by.time === "year") setDates(`${c.key}-01-01`, `${c.key}-12-31`);
    else if (by.time === "month") { const [y, m] = c.key.split("-").map(Number); setDates(`${c.key}-01`, `${c.key}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`); }
    else { state.f[by.k] = [c.key]; state.sel = ""; update(true); }
  };
  if (by.time) { // columns over time
    const H = 200, padL = 34, padB = 20, plotH = H - padB - 8, bw = (W - padL - 4) / agg.cats.length;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H);
    tk.forEach((t) => {
      const y = 8 + plotH - (t / top) * plotH;
      svg.appendChild(svgEl("line", { x1: padL, x2: W - 4, y1: y, y2: y, class: "tl-grid" }));
      const tx = svgEl("text", { x: padL - 4, y: y + 3, class: "tl-ax", "text-anchor": "end" }); tx.textContent = String(t); svg.appendChild(tx);
    });
    const every = Math.ceil(agg.cats.length / Math.max(1, Math.floor((W - padL) / (by.time === "month" ? 60 : 46))));
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const monthLabel = (k) => `${MON[Number(k.slice(5, 7)) - 1]} ${k.slice(0, 4)}`;
    agg.cats.forEach((c, i) => {
      const x = padL + i * bw, g = svgEl("g", { class: "ch-m" + (c.total ? " pickable" : "") });
      let y = 8 + plotH;
      const segs = series.filter((x2) => c.parts[x2.s]);
      segs.forEach((x2, j) => {
        const h = (c.parts[x2.s] / top) * plotH, gap = j < segs.length - 1 && h >= 4 ? 2 : 0;
        y -= h;
        g.appendChild(svgEl("rect", { class: "ch-bar " + x2.cls, x: x + 1, y: y + gap, width: Math.max(1, bw - 2), height: h - gap, rx: j === segs.length - 1 ? Math.min(3, bw / 3, h / 2) : 0 }));
      });
      g.appendChild(svgEl("rect", { class: "tl-hit", x, y: 0, width: bw, height: H - padB }));
      const t = svgEl("title"); t.textContent = tip(c); g.appendChild(t);
      g.addEventListener("click", () => pick(c));
      keyPick(g, c);
      svg.appendChild(g);
      if (i % every === 0) { const tx = svgEl("text", { x: x + bw / 2, y: H - 5, class: "tl-ax", "text-anchor": "middle" }); tx.textContent = by.time === "month" ? monthLabel(c.key) : c.key; svg.appendChild(tx); }
    });
  } else { // bars, largest first
    const rowH = 22, labW = Math.min(200, Math.round(W * 0.34)), numW = 44, H = agg.cats.length * rowH + 22;
    const plotW = W - labW - numW - 8;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H);
    tk.forEach((t) => {
      const x = labW + (t / top) * plotW;
      svg.appendChild(svgEl("line", { x1: x, x2: x, y1: 0, y2: H - 18, class: "tl-grid" }));
      const tx = svgEl("text", { x, y: H - 5, class: "tl-ax", "text-anchor": "middle" }); tx.textContent = String(t); svg.appendChild(tx);
    });
    agg.cats.forEach((c, i) => {
      const y = i * rowH + 3, g = svgEl("g", { class: "ch-m" + (c.key !== CH.OTHER ? " pickable" : "") });
      const lt = svgEl("text", { x: labW - 6, y: y + 12, class: "ch-lab", "text-anchor": "end" });
      const lab = label(c.key); lt.textContent = lab.length > 28 ? lab.slice(0, 27) + "…" : lab; g.appendChild(lt);
      let x = labW;
      const segs = series.filter((x2) => c.parts[x2.s]);
      segs.forEach((x2, j) => {
        const w = (c.parts[x2.s] / top) * plotW, gap = j < segs.length - 1 && w >= 4 ? 2 : 0;
        g.appendChild(svgEl("rect", { class: "ch-bar " + x2.cls, x, y, width: w - gap, height: rowH - 6, rx: j === segs.length - 1 ? Math.min(3, w / 2) : 0 }));
        x += w;
      });
      const nt = svgEl("text", { x: x + 5, y: y + 12, class: "ch-num" }); nt.textContent = String(c.total); g.appendChild(nt);
      g.appendChild(svgEl("rect", { class: "tl-hit", x: 0, y: y - 2, width: W, height: rowH }));
      const t = svgEl("title"); t.textContent = tip(c); g.appendChild(t);
      g.addEventListener("click", () => pick(c));
      keyPick(g, c);
      svg.appendChild(g);
    });
  }
  box.appendChild(svg);
  if (sp.get) {
    const lg = el("p", "legend small muted");
    series.forEach((x2) => { const sp2 = el("span"); sp2.append(el("span", "sw " + x2.cls), sName(x2.s)); lg.appendChild(sp2); });
    box.appendChild(lg);
  }
  const notes = [`${lastFiltered.length.toLocaleString("en-US")} launches in your filters`];
  if (agg.skipped) notes.push(`${agg.skipped} without this field left out`);
  if (agg.multi) notes.push("a launch with more than one value counts once in each");
  if (agg.folded) notes.push(`the ${agg.folded} smallest are one "others" bar`);
  notes.push(by.time ? "click a column to set the dates" : "click a bar to filter by it");
  box.appendChild(el("p", "small muted", notes.join("; ") + "."));
  const det = el("details", "small"); det.appendChild(el("summary", "", "Show the numbers"));
  const head = [by.label, ...(sp.get ? series.map((x2) => sName(x2.s)) : []), "Total"];
  const t = el("table"), thead = el("thead"), htr = el("tr");
  head.forEach((h, i) => htr.appendChild(el("th", i ? "num" : "", h))); thead.appendChild(htr); t.appendChild(thead);
  const tb = el("tbody");
  agg.cats.forEach((c) => {
    const tr = el("tr"); tr.appendChild(el("td", "", label(c.key)));
    if (sp.get) series.forEach((x2) => tr.appendChild(el("td", "num", String(c.parts[x2.s] || 0))));
    tr.appendChild(el("td", "num", String(c.total))); tb.appendChild(tr);
  });
  t.appendChild(tb);
  const wrap = el("div", "tbl-wrap"); wrap.appendChild(t); det.appendChild(wrap);
  box.appendChild(det);
}

/* ---------- downloads (export.js): the launches in the current filters ---------- */
const TYPES = { csv: "text/csv;charset=utf-8", geojson: "application/geo+json", kml: "application/vnd.google-earth.kml+xml" };
function download(kind) {
  writeHash();
  const generated = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const link = (id) => location.origin + location.pathname + "#history?" + new URLSearchParams({ st: "launched|upcoming|notice", sel: id }).toString();
  const o = { eventsFor: (r) => (r.chart || []).flatMap((id) => chartById.get(id) || []), withAreas: state.areas, countryName,
    link, view: location.href, generated, zone: T ? T.zone() : "UTC", when };
  const text = kind === "csv" ? X.toCSV(lastFiltered, o) : kind === "geojson" ? JSON.stringify(X.toGeoJSON(lastFiltered, o)) : X.toKML(lastFiltered, o);
  const url = URL.createObjectURL(new Blob([text], { type: TYPES[kind] }));
  const a = document.createElement("a");
  a.href = url; a.download = X.fileName(kind, generated); a.hidden = true;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

/* ---------- one update for every change ---------- */
let fitNext = true;
function update(refit) {
  const rows = filtered();
  lastFiltered = rows;
  const total = IX.records.length;
  const up = rows.filter((r) => r.status === "upcoming").length;
  $("h-count").textContent = `${rows.length} of ${total} shown` + (up ? ` (${up} scheduled)` : "") + (rows.length > state.shown ? `; the list shows ${state.shown}` : "");
  renderFacets(); rangesShow(); presets(); kindToggles(); chips(); timeline(); chartView(); cmpTray(); list(rows);
  if (map) map.show(rows, state.areas, refit || fitNext);
  fitNext = false;
  if (state.sel && !byId.get(state.sel)) state.sel = "";
  detail(byId.get(state.sel) || null);
  writeHash();
}

// Redraw the timeline and the chart when their box changes width (a rotated tablet, a resized window): both are laid
// out in pixels at the box's width.
function watchWidth(id, draw) {
  const box = $(id);
  if (!box || !window.ResizeObserver) return;
  let w = box.clientWidth, t = null;
  new ResizeObserver(() => {
    const now = box.clientWidth;
    if (!now || Math.abs(now - w) < 2) return;
    w = now; clearTimeout(t); t = setTimeout(draw, 120);
  }).observe(box);
}

export async function initHistory(ix, hist) {
  IX = ix; HIST = hist;
  watchWidth("h-timeline", () => timeline());
  watchWidth("h-chart-out", () => chartView());
  if (Array.isArray(IX.kinds) && IX.kinds.length) KINDS.splice(0, KINDS.length, ...IX.kinds);
  IX.records.forEach((r) => byId.set(r.id, r));
  // A record later folded into another by a join (a GCAT launch a charted event joined, a second charted placemark of
  // one launch) keeps its address: sel=gcat:<tag> or sel=<charted id> opens the record that holds it.
  IX.records.forEach((r) => [r.gcat && "gcat:" + r.gcat, ...(r.chart || [])].forEach((k) => { if (k && !byId.has(k)) byId.set(k, r); }));
  HIST.events.forEach((e) => { if (!chartById.has(e.id)) chartById.set(e.id, []); chartById.get(e.id).push(e); });
  rekey();
  applySaved();
  state = readHash();
  buildRanges();
  $("h-q").value = state.q; $("h-from").value = state.from; $("h-to").value = state.to; $("h-areas").checked = state.areas;
  let qt = null;
  $("h-q").addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(() => { state.q = $("h-q").value.trim(); state.shown = PAGE; update(true); }, 200); });
  $("h-from").addEventListener("change", () => setDates($("h-from").value, $("h-to").value));
  $("h-to").addEventListener("change", () => setDates($("h-from").value, $("h-to").value));
  $("h-areas").addEventListener("change", () => { state.areas = $("h-areas").checked; update(false); });
  $("h-more").addEventListener("click", () => { state.shown += PAGE; list(lastFiltered); });
  chartSetup();
  $("h-fit").addEventListener("click", () => map && map.show(lastFiltered, state.areas, true));
  $("h-copy").addEventListener("click", async () => {
    writeHash();
    try { await navigator.clipboard.writeText(location.href); $("h-copy").textContent = "Link copied"; } catch { $("h-copy").textContent = "Copy the address bar"; }
    setTimeout(() => { $("h-copy").textContent = "Copy link to this view"; }, 2500);
  });
  document.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => download(b.dataset.dl)));
  $("h-toggle").addEventListener("click", () => {
    const side = $("h-side"); side.classList.toggle("open");
    $("h-toggle").setAttribute("aria-expanded", side.classList.contains("open") ? "true" : "false");
  });
  const c = IX.counts;
  FIRST_YEAR = Math.min(Number((IX.ledger_since || "2012").slice(0, 4)), ...IX.records.filter((r) => r.time).map((r) => Number(r.time.slice(0, 4))));
  const gk = c.gcat_kinds || {}, gn = (k) => (gk[k] || 0).toLocaleString("en-US");
  const sub = ["Suborbital rocket", "Crewed suborbital", "Atmospheric test"].reduce((n, k) => n + (gk[k] || 0), 0);
  $("h-about").textContent = (c.gcat_kinds
    ? `${c.gcat.toLocaleString("en-US")} launches GCAT lists since ${IX.ledger_since.slice(0, 4)}: ${gn("Orbital")} orbital, ${sub.toLocaleString("en-US")} suborbital (sounding rockets, crewed flights, atmospheric tests), ${gn("Missile test")} missile tests, ${gn("Lofted missile test")} lofted missile tests and ${gn("Combat launch")} missiles fired in combat`
    : `${c.gcat} orbital launches GCAT lists since ${IX.ledger_since.slice(0, 4)}`)
    + `; ${c.chart} events in Launch's charted notices (on ${c.gcat_joined} GCAT launches; ${c.chart_notice_sets ?? 0} with no identified launch), and Launch Library 2's schedule.`
    + (c.nfc ? ` NotamForChina adds the notices of ${c.nfc.records - c.nfc.own_records} of those launches` + (c.nfc.own_launched ? `, and ${c.nfc.own_launched} Chinese launches from ${FIRST_YEAR} to ${Number((IX.ledger_since || "2012").slice(0, 4)) - 1}.` : ".") : "")
    + (c.joey ? ` Joey0609/notams adds NOTAM texts to ${c.joey.records} launches (${c.joey.notices - c.joey.unjoined} of its ${c.joey.notices} launch-related notices; the rest match no launch here).` : "")
    + ` Updated ${fmt(IX.generated_at)}.`;
  update(true); // filters and list first; the map follows when its base has loaded
  createHistoryMap($("hmap"), IX, { onPick: (id) => select(id, false), onSite: (name) => { state.f.site = [name]; update(true); } })
    .then((m) => {
      map = m;
      map.setCharted(HIST.events);
      map.show(lastFiltered, state.areas, true);
      if (state.sel && byId.get(state.sel)) select(state.sel, true);
    })
    .catch((err) => { $("hmap").textContent = "The map could not load: " + err.message + ". The filters and the list still work."; });
  if (T && T.onChange) T.onChange(() => { rekey(); update(false); });
  return {
    resize: () => map && map.resize(), refresh: () => { cmpKey = null; update(false); }, savedChanged,
    // The address changed by hand or by a link (not by this page): take the view it names.
    fromHash: () => {
      const want = location.hash, before = state.sel;
      writeHash();
      if (location.hash === want) return;
      history.replaceState(null, "", want);
      state = readHash();
      $("h-q").value = state.q; $("h-from").value = state.from; $("h-to").value = state.to; $("h-areas").checked = state.areas;
      update(true);
      if (state.sel && state.sel !== before && byId.get(state.sel)) select(state.sel, true);
    },
  };
}
