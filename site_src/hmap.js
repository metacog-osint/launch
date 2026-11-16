// The History tab's map: every launch site, and for the launches in the current filters their flight paths
// (as charted: solid; estimated from an inferred azimuth: dashed; scheduled: dotted) and, if asked, their
// closure areas. The selected launch is drawn on top with its pad. Same base map as map.js. Colours come from the
// style.css actor tokens through MapLibre paint (no inline styles, CSP).
import * as ml from "./vendor/maplibre-gl/maplibre-gl.mjs";
import { buildStyle, addProjectionToggle, collapseAttribution, fitCoords, worldZoom } from "./map.js";
import { geodesic, greatCircle } from "./notam.js";

const dark = matchMedia("(prefers-color-scheme: dark)");
const EMPTY = { type: "FeatureCollection", features: [] };
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const BIG = { US: "us", CN: "cn", RU: "ru" };
const group = (cc) => BIG[cc] || "other";
// NotamForChina's charted areas on a record (catalog.py leaves out the ring of a notice already charted).
const nfcRings = (r) => (r.nfc_notices || []).filter((n) => n.ring && n.ring.length >= 3).map((n) => n.ring)
  // Joey0609/notams' areas (catalog.py leaves out those already charted)
  .concat((r.joey_notices || []).flatMap((n) => (n.rings || []).filter((x) => x.length >= 3)))
  // FAA TFRs and NGA warnings from Internet Archive copies
  .concat((r.archive_notices || []).flatMap((n) => (n.rings || []).filter((x) => x.length >= 3)));

const lineCache = new Map();
const drawnCache = new WeakMap(); // a charted path or a closure ring (an array from the data) -> its great-circle line
const curved = (a) => { if (!drawnCache.has(a)) drawnCache.set(a, geodesic(a)); return drawnCache.get(a); };
function pathLines(r, chartEvents) {
  if (!r.path) return [];
  if (r.path.kind === "drawn") return chartEvents.flatMap((e) => e.paths || []).filter((p) => p.length >= 2).map((p) => {
    if (!drawnCache.has(p)) drawnCache.set(p, geodesic(p));
    return drawnCache.get(p);
  });
  if (!r.pad) return [];
  if (!lineCache.has(r.id)) lineCache.set(r.id, [greatCircle(r.pad[0], r.pad[1], r.path.az, r.path.nm)]);
  return lineCache.get(r.id);
}

export async function createHistoryMap(container, IX, { onPick, onSite }) {
  const first = await buildStyle();
  const map = new ml.Map({
    container, style: first.style, center: [100, 30], zoom: worldZoom(container),
    dragRotate: false, pitchWithRotate: false, cooperativeGestures: true,
    attributionControl: { compact: true, customAttribution: "Land: Natural Earth · Launches: GCAT (J. McDowell, CC BY 4.0), Launch Library 2, Launch's charted notices · Chinese notices: NotamForChina (mikezang, Apache-2.0), Joey0609/notams (MIT)" },
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
  addProjectionToggle(map);
  collapseAttribution(map);
  map.getCanvas().setAttribute("aria-label", "Map of launch sites and flight paths for the launches in your filters. Every launch on it is also in the list below.");
  const chartById = new Map();
  const featCache = new Map(); // per launch: its path and area features, built once
  let data = { sites: EMPTY, loose: EMPTY, paths: EMPTY, areas: EMPTY, selpath: EMPTY, selarea: EMPTY, selpad: EMPTY };
  let opacity = 0.6;
  const byId = new Map(IX.records.map((r) => [r.id, r]));

  const tip = document.createElement("div"); tip.className = "map-tip"; tip.hidden = true; container.appendChild(tip);
  const pop = document.createElement("div"); pop.className = "map-pop"; pop.hidden = true; container.appendChild(pop);
  const closePop = () => { pop.hidden = true; pop.textContent = ""; };

  function addLayers() {
    const g = { us: css("--g-us"), cn: css("--g-cn"), ru: css("--g-ru"), other: css("--g-other") };
    const ink = css("--text"), panel = css("--panel"), muted = css("--muted");
    const actor = ["match", ["get", "group"], "us", g.us, "cn", g.cn, "ru", g.ru, g.other];
    for (const [k, v] of Object.entries(data)) map.addSource("h_" + k, { type: "geojson", data: v });
    map.addLayer({ id: "h-areas-fill", type: "fill", source: "h_areas", paint: { "fill-color": actor, "fill-opacity": 0.06 } });
    map.addLayer({ id: "h-areas-line", type: "line", source: "h_areas", paint: { "line-color": actor, "line-width": 0.7, "line-opacity": 0.5 } });
    map.addLayer({ id: "h-paths-drawn", type: "line", source: "h_paths", filter: ["==", ["get", "k"], "drawn"],
      layout: { "line-cap": "round" }, paint: { "line-color": actor, "line-width": 1.4, "line-opacity": opacity } });
    map.addLayer({ id: "h-paths-est", type: "line", source: "h_paths", filter: ["==", ["get", "k"], "est"],
      paint: { "line-color": actor, "line-width": 1.4, "line-opacity": opacity, "line-dasharray": [3, 2] } });
    map.addLayer({ id: "h-paths-up", type: "line", source: "h_paths", filter: ["==", ["get", "k"], "up"],
      layout: { "line-cap": "round" }, paint: { "line-color": actor, "line-width": 2.6, "line-opacity": 0.95, "line-dasharray": [0.3, 1.8] } });
    map.addLayer({ id: "h-sel-area-fill", type: "fill", source: "h_selarea", paint: { "fill-color": actor, "fill-opacity": 0.28 } });
    map.addLayer({ id: "h-sel-area-line", type: "line", source: "h_selarea", paint: { "line-color": actor, "line-width": 2 } });
    map.addLayer({ id: "h-sel-casing", type: "line", source: "h_selpath", layout: { "line-cap": "round" }, paint: { "line-color": panel, "line-width": 6 } });
    map.addLayer({ id: "h-sel-path", type: "line", source: "h_selpath", layout: { "line-cap": "round" }, paint: { "line-color": actor, "line-width": 3 } });
    map.addLayer({ id: "h-loose", type: "circle", source: "h_loose", paint: { "circle-radius": 3, "circle-color": actor, "circle-stroke-color": panel, "circle-stroke-width": 1 } });
    map.addLayer({ id: "h-sites", type: "circle", source: "h_sites", paint: {
      "circle-radius": ["case", ["==", ["get", "n"], 0], 3, ["min", 16, ["+", 4, ["*", 1.6, ["sqrt", ["get", "n"]]]]]],
      "circle-color": ["case", ["==", ["get", "n"], 0], panel, actor],
      "circle-opacity": ["case", ["==", ["get", "n"], 0], 0.9, 0.85],
      "circle-stroke-color": ["case", ["==", ["get", "n"], 0], muted, panel], "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "h-sel-pad", type: "circle", source: "h_selpad", paint: { "circle-radius": 7, "circle-color": panel, "circle-stroke-color": actor, "circle-stroke-width": 3.5 } });
    map.addLayer({ id: "h-sel-pad-ring", type: "circle", source: "h_selpad", paint: { "circle-radius": 11, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": ink, "circle-stroke-width": 1 } });
  }
  map.on("style.load", addLayers);
  dark.addEventListener("change", async () => { const n = await buildStyle(); map.setStyle(n.style, { diff: false }); });
  await new Promise((res) => (map.loaded() ? res() : map.once("load", res)));

  const PATHS = ["h-paths-drawn", "h-paths-est", "h-paths-up", "h-sel-path"];
  const near = (pt, layers, px = 5) => map.queryRenderedFeatures([[pt.x - px, pt.y - px], [pt.x + px, pt.y + px]], { layers: layers.filter((l) => map.getLayer(l)) });
  map.on("mousemove", (e) => {
    const s = near(e.point, ["h-sites"], 4);
    const p = s.length ? [] : near(e.point, PATHS.concat(["h-loose"]));
    map.getCanvas().style.cursor = s.length || p.length ? "pointer" : "";
    if (!s.length && !p.length) { tip.hidden = true; return; }
    if (s.length) tip.textContent = `${s[0].properties.name}: ${s[0].properties.n} in your filters`;
    else {
      const ids = [...new Set(p.map((f) => f.properties.id))];
      const r = byId.get(ids[0]);
      tip.textContent = (r ? r.label || r.payload : "") + (ids.length > 1 ? ` and ${ids.length - 1} more here` : "");
    }
    tip.hidden = false;
    const x = Math.min(e.point.x + 12, container.clientWidth - 260);
    tip.style.left = x + "px"; tip.style.top = e.point.y + 12 + "px";
  });
  map.getCanvas().addEventListener("mouseleave", () => { tip.hidden = true; });
  map.on("click", (e) => {
    closePop();
    const s = near(e.point, ["h-sites"], 4);
    if (s.length) {
      const pr = s[0].properties;
      pop.append(Object.assign(document.createElement("b"), { textContent: pr.name }), document.createTextNode(` · ${pr.n} in your filters`));
      const b = document.createElement("button"); b.type = "button"; b.className = "chip-btn"; b.textContent = "Show only this site";
      b.addEventListener("click", () => { closePop(); onSite(pr.name); });
      const c = document.createElement("button"); c.type = "button"; c.className = "linkish small"; c.textContent = "Close";
      c.addEventListener("click", closePop);
      const row = document.createElement("p"); row.append(b, document.createTextNode(" "), c); pop.appendChild(row);
      place(e.point); return;
    }
    const p = near(e.point, PATHS.concat(["h-loose"]));
    const ids = [...new Set(p.map((f) => f.properties.id))].filter((id) => byId.has(id));
    if (ids.length === 1) { onPick(ids[0]); return; }
    if (ids.length > 1) {
      pop.appendChild(Object.assign(document.createElement("b"), { textContent: `${ids.length} launches here` }));
      const ul = document.createElement("ul"); ul.className = "plain pop-list";
      ids.sort((a, b) => ((byId.get(b).time || "") < (byId.get(a).time || "") ? -1 : 1)).slice(0, 12).forEach((id) => {
        const r = byId.get(id); const li = document.createElement("li");
        const b = document.createElement("button"); b.type = "button"; b.className = "linkish";
        b.textContent = `${(r.time || "").slice(0, 10)} · ${r.vehicle || ""} · ${r.payload || r.label || ""}`;
        b.addEventListener("click", () => { closePop(); onPick(id); });
        li.appendChild(b); ul.appendChild(li);
      });
      pop.appendChild(ul);
      if (ids.length > 12) pop.appendChild(Object.assign(document.createElement("p"), { className: "small muted", textContent: "Zoom in or narrow the filters for the rest." }));
      place(e.point);
    }
  });
  function place(pt) {
    pop.hidden = false;
    pop.style.left = Math.max(4, Math.min(pt.x + 10, container.clientWidth - 300)) + "px";
    pop.style.top = Math.max(4, Math.min(pt.y + 10, container.clientHeight - 200)) + "px";
  }

  function set(name, fc) {
    data[name] = fc || EMPTY;
    const s = map.getSource("h_" + name);
    if (s) s.setData(data[name]);
  }
  const fit = (coords, maxZoom = 6, padding = 50) => fitCoords(map, coords, { padding, maxZoom, duration: 600 });
  // From 1100 px wide the detail card (style.css .h-detail: 380 px, 52 px from the right) lies over the map, so a
  // selected launch is fitted into the part of the map the card leaves clear.
  const besideCard = () => matchMedia("(min-width: 1100px)").matches && container.clientWidth - 482 >= 200
    ? { top: 50, bottom: 50, left: 50, right: 482 } : 50;

  function show(rows, withAreas, refit) {
    closePop();
    const counts = new Map();
    rows.forEach((r) => { if (r.site) counts.set(r.site, (counts.get(r.site) || 0) + 1); });
    const siteCC = new Map(IX.sites.map((s) => [s.name, s.country]));
    set("sites", { type: "FeatureCollection", features: IX.sites.map((s) => ({ type: "Feature",
      properties: { name: s.name, n: counts.get(s.name) || 0, group: group(siteCC.get(s.name)) },
      geometry: { type: "Point", coordinates: [s.lon, s.lat] } })).sort((a, b) => b.properties.n - a.properties.n) });
    set("loose", { type: "FeatureCollection", features: rows.filter((r) => !r.site && r.pad).map((r) => ({ type: "Feature",
      properties: { id: r.id, group: group(r.actor) }, geometry: { type: "Point", coordinates: r.pad } })) });
    const feats = [], areas = [], ends = [];
    rows.forEach((r) => {
      let f = featCache.get(r.id);
      if (!f) {
        const evs = (r.chart || []).flatMap((id) => chartById.get(id) || []);
        const k = r.status === "upcoming" ? "up" : r.path && r.path.kind === "drawn" ? "drawn" : "est";
        const props = { id: r.id, group: group(r.actor) };
        const lines = pathLines(r, evs);
        f = {
          lines: lines.map((line) => ({ type: "Feature", properties: { ...props, k }, geometry: { type: "LineString", coordinates: line } })),
          ends: lines.flatMap((line) => [line[0], line[line.length - 1]]).concat(r.pad ? [r.pad] : []),
          areas: evs.flatMap((e) => e.areas.map((a) => a.ring)).concat((r.closures || []).map((c) => c.ring), nfcRings(r))
            .map((ring) => ({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [curved(ring)] } })),
        };
        featCache.set(r.id, f);
      }
      feats.push(...f.lines); ends.push(...f.ends);
      if (withAreas) areas.push(...f.areas);
    });
    set("paths", { type: "FeatureCollection", features: feats });
    set("areas", { type: "FeatureCollection", features: areas });
    opacity = rows.length <= 40 ? 0.9 : rows.length <= 200 ? 0.6 : 0.32;
    ["h-paths-drawn", "h-paths-est"].forEach((l) => map.getLayer(l) && map.setPaintProperty(l, "line-opacity", opacity));
    if (refit) {
      if (rows.length > 600 || !ends.length) map.easeTo({ center: [100, 30], zoom: worldZoom(container), duration: 600 });
      else fit(ends, rows.length === 1 ? 6 : 5);
    }
  }

  function select(r, evs, fly) {
    if (!r) { set("selpath", null); set("selarea", null); set("selpad", null); return; }
    const gp = group(r.actor);
    const lines = pathLines(r, evs);
    set("selpath", { type: "FeatureCollection", features: lines.map((l) => ({ type: "Feature", properties: { group: gp }, geometry: { type: "LineString", coordinates: l } })) });
    const rings = evs.flatMap((e) => e.areas.map((a) => a.ring)).concat((r.closures || []).map((c) => c.ring), nfcRings(r)).map(curved);
    set("selarea", { type: "FeatureCollection", features: rings.map((ring) => ({ type: "Feature", properties: { group: gp }, geometry: { type: "Polygon", coordinates: [ring] } })) });
    set("selpad", r.pad ? { type: "FeatureCollection", features: [{ type: "Feature", properties: { group: gp }, geometry: { type: "Point", coordinates: r.pad } }] } : null);
    if (fly) fit([...(r.pad ? [r.pad] : []), ...lines.flat(), ...rings.flat()], 6, besideCard());
  }

  return {
    show, select, resize: () => map.resize(),
    setCharted: (events) => { events.forEach((e) => { if (!chartById.has(e.id)) chartById.set(e.id, []); chartById.get(e.id).push(e); }); },
  };
}
