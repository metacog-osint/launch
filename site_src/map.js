// Launch's map, on the suite's stack (Orbit, COP, Blackout): vendored MapLibre GL JS 6.14.0, Natural Earth land
// from this site at world zoom, OpenFreeMap's vector map past DETAIL_ZOOM, Natural Earth alone if OpenFreeMap
// can't be reached. Colours come from style.css tokens through MapLibre paint (no inline styles, CSP).
// Layers: live closure areas (Orbit's navigational warnings, FAA space-operations TFRs), scheduled launches' estimated
// paths through them, scheduled launch pads, launches of the past seven days,
// recurring drop zones, pasted notices. The History tab has its own map (hmap.js).
import * as ml from "./vendor/maplibre-gl/maplibre-gl.mjs";

const dark = matchMedia("(prefers-color-scheme: dark)");
const DETAIL_ZOOM = 3.5;
const BASE = {
  light: { style: "https://tiles.openfreemap.org/styles/positron", land: "#F2F3F0", water: "#C2C8CA", border: "#B9BEC2" },
  dark: { style: "https://tiles.openfreemap.org/styles/dark", land: "#1A1D22", water: "#0C0F14", border: "#3A3F46" },
};
const EMPTY = { type: "FeatureCollection", features: [] };
const theme = () => (dark.matches ? "dark" : "light");
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const worldSource = () => ({ type: "geojson", data: new URL("data/world.geojson", location.href).href, maxzoom: 5, tolerance: 1 });
const worldLayers = (b, maxzoom) => [
  { id: "la-land", type: "fill", source: "la_world", ...(maxzoom ? { maxzoom } : {}), paint: { "fill-color": b.land } },
  { id: "la-borders", type: "line", source: "la_world", ...(maxzoom ? { maxzoom } : {}), paint: { "line-color": b.border, "line-width": 0.6 } },
];
// MapLibre draws with WebGL 2. Some browsers have it off or lack it (a locked-down machine, an old phone, a remote
// desktop): the page then says so and every tab but the map still works.
export const NO_WEBGL2 = "this browser cannot draw maps (WebGL 2 is off or not supported)";
export function hasWebGL2() {
  try { return !!document.createElement("canvas").getContext("webgl2"); } catch { return false; }
}

export async function buildStyle() {
  const b = BASE[theme()];
  try {
    const r = await fetch(b.style);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const s = await r.json();
    s.layers = s.layers.filter((l) => l.source !== "ne2_shaded");
    delete s.sources.ne2_shaded;
    for (const l of s.layers) {
      if (l.type === "background") l.paint = { ...l.paint, "background-color": ["step", ["zoom"], b.water, DETAIL_ZOOM, (l.paint && l.paint["background-color"]) || b.land] };
      else if (l.source) l.minzoom = Math.max(l.minzoom || 0, DETAIL_ZOOM);
    }
    s.sources.la_world = worldSource();
    s.layers.splice(s.layers.findIndex((l) => l.type === "background") + 1, 0, ...worldLayers(b, DETAIL_ZOOM));
    s.projection = { type: projection };
    return { style: s, fellBack: false };
  } catch {
    return { style: { version: 8, projection: { type: projection }, sources: { la_world: worldSource() },
      layers: [{ id: "bg", type: "background", paint: { "background-color": b.water } }, ...worldLayers(b)] }, fellBack: true };
  }
}

/* Flat map or globe, one choice for both maps, saved in this browser. The flat map stays the default: on the
   globe a polar path (Vostochny, Plesetsk) runs over the pole instead of off the top of the map. The choice goes
   into every style buildStyle() makes (the first one and the light/dark switch's), and the button switches maps
   already drawn. */
const PROJ_KEY = "launch.projection";
let projection = "mercator";
try { if (localStorage.getItem(PROJ_KEY) === "globe") projection = "globe"; } catch { /* storage blocked: flat */ }
const projMaps = new Set(); // { map, ctl, atWorld, pending } per map
const sized = (c) => c.clientWidth > 0 && c.clientHeight > 0;
const nearWorld = (m) => m.map.getZoom() <= worldZoom(m.map.getContainer(), m.map.getCenter().lat) + 0.05;
class ProjectionToggle {
  onAdd(map) {
    this._map = map;
    this._el = document.createElement("div");
    this._el.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this._btn = document.createElement("button");
    this._btn.type = "button";
    this._btn.appendChild(Object.assign(document.createElement("span"), { className: "maplibregl-ctrl-icon" }));
    this._btn.addEventListener("click", () => {
      // A map at (or out past) its world view goes to the other projection's world view: the flat map's leaves
      // the globe a small disc, the globe's leaves the flat map zoomed in on one region. A map in a hidden tab has
      // no size, so it catches up the next time it has one.
      projMaps.forEach((m) => { if (sized(m.map.getContainer())) m.atWorld = nearWorld(m); });
      projection = projection === "globe" ? "mercator" : "globe";
      try { localStorage.setItem(PROJ_KEY, projection); } catch { /* not saved; still switches */ }
      projMaps.forEach((m) => {
        m.map.setProjection({ type: projection }); m.ctl.sync();
        if (!m.atWorld) return;
        if (sized(m.map.getContainer())) m.map.easeTo({ zoom: worldZoom(m.map.getContainer(), m.map.getCenter().lat), duration: 400 });
        else m.pending = true;
      });
    });
    this._el.appendChild(this._btn);
    this.sync();
    return this._el;
  }
  sync() {
    const on = projection === "globe";
    this._btn.className = on ? "maplibregl-ctrl-globe-enabled" : "maplibregl-ctrl-globe";
    const t = on ? "Show the flat map" : "Show as a globe";
    this._btn.title = t; this._btn.setAttribute("aria-label", t); this._btn.setAttribute("aria-pressed", String(on));
  }
  onRemove() { this._el.remove(); }
}
export const isGlobe = () => projection === "globe";
/* MapLibre's world is 512 px around at zoom 0, and its globe keeps the flat map's scale at the centre latitude, so
   the globe's radius is 512 * 2^zoom / (2pi cos lat): the same zoom draws a bigger globe over Plesetsk than over
   the equator. The camera's perspective draws the disc somewhat smaller than that radius (about 0.8 of it,
   measured in the preview 15 Nov 2026), so a fit made with the radius alone leaves a margin. */
const globeZoom = (halfPx, sinTheta, lat) => Math.log2((2 * Math.PI * Math.max(halfPx, 40) * Math.max(Math.cos((lat * Math.PI) / 180), 0.087))
  / (512 * Math.max(sinTheta, 1e-4)));
/* The whole-world zoom: flat, the map's width; a globe, about 85% of the map's shorter side once drawn. */
export function worldZoom(container, lat = 30) {
  const w = container.clientWidth, h = container.clientHeight;
  return isGlobe() ? globeZoom(0.52 * Math.min(w, h), 1, lat) : Math.max(0, Math.log2(w / 512));
}
/* Fit [lon, lat] points. Flat: their bounds. Globe: a bounding box picks the wrong side of the world for a path
   over the pole (Plesetsk to the South Pacific centred on the Atlantic, both ends out of sight), so centre on the
   midpoint of the two points farthest apart (found from the first point, then from the farthest; not the mean,
   which a curved closure ring's hundreds of vertices would pull) and zoom until every point is in view. Points
   that no hemisphere holds (Plesetsk to a South Pacific drop zone, 167 degrees) can't all be seen on a globe, and
   the short way between the two ends may not be the path's way: then centre on the first point (the pad, for a
   selected launch) and show the whole globe; the flat map shows such a launch whole. `padding` is a number or
   {top, bottom, left, right}; it shifts the centre, not the map's padding. */
export function fitCoords(map, coords, { padding = 50, maxZoom = 6, duration = 600 } = {}) {
  if (!coords.length) return;
  if (!isGlobe()) {
    const b = new ml.LngLatBounds();
    coords.forEach((c) => b.extend(c));
    map.fitBounds(b, { padding, maxZoom, duration });
    return;
  }
  const r = (d) => (d * Math.PI) / 180;
  const v = coords.map(([lon, lat]) => [Math.cos(r(lat)) * Math.cos(r(lon)), Math.cos(r(lat)) * Math.sin(r(lon)), Math.sin(r(lat))]);
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const farthest = (from) => v.reduce((best, a) => (dot(a, from) < dot(best, from) ? a : best), from);
  const a = farthest(v[0]), b = farthest(a);
  let [x, y, z] = [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const n = Math.hypot(x, y, z);
  if (n < 1e-6) [x, y, z] = a; else { x /= n; y /= n; z /= n; }
  let cosMin = Math.min(...v.map((p) => dot(p, [x, y, z])));
  if (cosMin <= 0) { [x, y, z] = v[0]; cosMin = 0; }
  const sinT = cosMin <= 0 ? 1 : Math.sqrt(1 - cosMin * cosMin);
  const p = typeof padding === "number" ? { top: padding, bottom: padding, left: padding, right: padding } : padding;
  const c = map.getContainer();
  const half = Math.min(c.clientWidth - p.left - p.right, c.clientHeight - p.top - p.bottom) / 2;
  const lat = (Math.asin(z) * 180) / Math.PI;
  map.easeTo({ center: [(Math.atan2(y, x) * 180) / Math.PI, lat],
    zoom: Math.min(maxZoom, globeZoom(half, sinT, lat)), offset: [(p.left - p.right) / 2, (p.top - p.bottom) / 2], duration });
}

/* The globe button, and each map's world view kept right: a map made in a hidden tab has no size, so its world
   zoom is wrong (a globe the size of a coin) until it has one. resize() fires moveend too, so "at world view" is
   only read while the map has a size and nothing is pending. */
/* On a narrow map (a phone) MapLibre opens its compact credit box over the map; start it closed, behind its (i)
   button: now (Launch's own credits open it when the map is made) and again at the load, in case the style's credits
   opened it. The credits are also on the Sources tab. */
export function collapseAttribution(map) {
  const close = () => {
    if (map.getContainer().offsetWidth > 640) return;
    map.getContainer().querySelectorAll(".maplibregl-ctrl-attrib.maplibregl-compact-show").forEach((e) => e.classList.remove("maplibregl-compact-show"));
  };
  close();
  map.once("load", close);
}

export function addProjectionToggle(map) {
  const ctl = new ProjectionToggle();
  map.addControl(ctl, "top-right");
  const c = map.getContainer();
  const m = { map, ctl, atWorld: true, pending: !sized(c) };
  projMaps.add(m);
  map.on("moveend", () => { if (sized(c) && !m.pending) m.atWorld = nearWorld(m); });
  map.on("resize", () => {
    if (!m.pending || !sized(c)) return;
    m.pending = false;
    if (m.atWorld) map.jumpTo({ zoom: worldZoom(c, map.getCenter().lat) });
  });
}

export async function createMap(container, model, { onPick }) {
  if (!hasWebGL2()) throw new Error(NO_WEBGL2);
  const first = await buildStyle();
  const map = new ml.Map({
    container, style: first.style, center: [110, 20], zoom: worldZoom(container, 20),
    dragRotate: false, pitchWithRotate: false, cooperativeGestures: true,
    attributionControl: { compact: true, customAttribution: "Land: Natural Earth · Areas: FAA, NGA via Orbit, Launch's charted notices" },
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
  addProjectionToggle(map);
  collapseAttribution(map);
  map.getCanvas().setAttribute("aria-label", "Map of launch and reentry closure areas. Every item on it is also listed on this page.");
  const data = { live: model.live, paths: model.paths || EMPTY, pads: model.pads, recent: model.recent || EMPTY, zones: EMPTY, paste: EMPTY, traj: EMPTY, trajpad: EMPTY };
  const note = (on) => {
    container.parentElement.querySelectorAll(".fallback-note").forEach((e) => e.remove());
    if (on) { const p = document.createElement("p"); p.className = "fallback-note small muted"; p.textContent = "Detailed base map unavailable: showing outline land."; container.parentElement.append(p); }
  };
  note(first.fellBack);

  function addLayers() {
    const g = { us: css("--g-us"), cn: css("--g-cn"), ru: css("--g-ru"), other: css("--g-other") };
    const ink = css("--text"), panel = css("--panel"), accent = css("--accent"), warn = css("--warn");
    const actor = ["match", ["get", "group"], "us", g.us, "cn", g.cn, "ru", g.ru, g.other];
    for (const [k, v] of Object.entries(data)) map.addSource("la_" + k, { type: "geojson", data: v });
    map.addLayer({ id: "zones-fill", type: "fill", source: "la_zones", paint: { "fill-color": warn, "fill-opacity": 0.14 } });
    map.addLayer({ id: "zones-line", type: "line", source: "la_zones", paint: { "line-color": warn, "line-width": 1, "line-dasharray": [2, 2] } });
    // A live area on a scheduled launch's estimated path takes that launch's country colour; any other stays grey.
    const tied = ["==", ["get", "tied"], 1];
    map.addLayer({ id: "live-fill", type: "fill", source: "la_live", paint: { "fill-color": ["case", tied, actor, ink], "fill-opacity": ["case", tied, 0.24, 0.07] } });
    map.addLayer({ id: "live-line", type: "line", source: "la_live", paint: { "line-color": ["case", tied, actor, ink], "line-width": ["case", tied, 1.8, 1.3], "line-opacity": 0.85 } });
    // Scheduled launches' estimated paths: a wide invisible line takes the click, so a phone can hit it.
    map.addLayer({ id: "path-hit", type: "line", source: "la_paths", layout: { "line-cap": "round" }, paint: { "line-color": ink, "line-width": 16, "line-opacity": 0.001 } });
    map.addLayer({ id: "path-casing", type: "line", source: "la_paths", layout: { "line-cap": "round" }, paint: { "line-color": panel, "line-width": 4.6 } });
    map.addLayer({ id: "path-line", type: "line", source: "la_paths", layout: { "line-cap": "round" }, paint: { "line-color": actor, "line-width": 2.2, "line-dasharray": [2.4, 1.4] } });
    map.addLayer({ id: "paste-fill", type: "fill", source: "la_paste", paint: { "fill-color": accent, "fill-opacity": 0.2 } });
    map.addLayer({ id: "paste-line", type: "line", source: "la_paste", paint: { "line-color": accent, "line-width": 2 } });
    // Launches of the past seven days (off unless the viewer turns them on): a filled dot in the country's colour.
    map.addLayer({ id: "recent", type: "circle", source: "la_recent", paint: { "circle-radius": 4.5, "circle-color": actor, "circle-stroke-color": panel, "circle-stroke-width": 1.4, "circle-opacity": 0.9 } });
    map.addLayer({ id: "pads", type: "circle", source: "la_pads", paint: { "circle-radius": 5.5, "circle-color": panel, "circle-stroke-color": actor, "circle-stroke-width": 2.6 } });
    // The Paste tab's trajectory: the great circle from the chosen pad through the pasted areas, and the pad.
    map.addLayer({ id: "traj-casing", type: "line", source: "la_traj", layout: { "line-cap": "round" }, paint: { "line-color": panel, "line-width": 5 } });
    map.addLayer({ id: "traj-line", type: "line", source: "la_traj", layout: { "line-cap": "round" }, paint: { "line-color": ink, "line-width": 2, "line-dasharray": [2, 1.5] } });
    map.addLayer({ id: "traj-pad", type: "circle", source: "la_trajpad", paint: { "circle-radius": 6.5, "circle-color": panel, "circle-stroke-color": accent, "circle-stroke-width": 3.5 } });
  }
  map.on("style.load", addLayers);
  dark.addEventListener("change", async () => { const n = await buildStyle(); note(n.fellBack); map.setStyle(n.style, { diff: false }); });
  const CLICK = ["pads", "recent", "path-hit", "live-fill", "zones-fill", "paste-fill"]; // in the order a click prefers them
  const pick = (pt) => {
    const f = map.queryRenderedFeatures([[pt.x - 6, pt.y - 6], [pt.x + 6, pt.y + 6]], { layers: CLICK.filter((l) => map.getLayer(l)) });
    if (!f.length) return null;
    const rank = (x) => CLICK.indexOf(x.layer.id);
    return f.reduce((best, x) => (rank(x) < rank(best) ? x : best)).properties.key;
  };
  // pickPoint(): the next click on the map gives its position (the Paste tab's "click the map" for a pad) instead
  // of picking an item; pickPoint(null) cancels.
  let armed = null;
  map.on("click", (e) => {
    if (armed) { const f = armed; armed = null; map.getCanvas().style.cursor = ""; f([e.lngLat.wrap().lng, e.lngLat.lat]); return; }
    const k = pick(e.point); if (k) onPick(k);
  });
  map.on("mousemove", (e) => { map.getCanvas().style.cursor = armed ? "crosshair" : pick(e.point) ? "pointer" : ""; });
  const pickPoint = (cb) => { armed = cb; map.getCanvas().style.cursor = cb ? "crosshair" : ""; };

  function set(name, fc) {
    data[name] = fc || EMPTY;
    const s = map.getSource("la_" + name);
    if (s) s.setData(data[name]);
  }
  function fit(fc) {
    const pts = [];
    const add = (c) => { if (typeof c[0] === "number") pts.push(c); else c.forEach(add); };
    (fc.features || []).forEach((f) => f.geometry && add(f.geometry.coordinates));
    fitCoords(map, pts, { padding: 40, maxZoom: 7, duration: 700 });
  }
  return { set, fit, pickPoint, resize: () => map.resize() };
}
