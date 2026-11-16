// Launch's map, on the suite's stack (Orbit, COP, Blackout): vendored MapLibre GL JS 6.14.0, Natural Earth land
// from this site at world zoom, OpenFreeMap's vector map past DETAIL_ZOOM, Natural Earth alone if OpenFreeMap
// can't be reached. Colours come from style.css tokens through MapLibre paint (no inline styles, CSP).
// Layers: live closure areas (Orbit's navigational warnings, FAA space-operations TFRs), scheduled launch pads,
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
    return { style: s, fellBack: false };
  } catch {
    return { style: { version: 8, sources: { la_world: worldSource() },
      layers: [{ id: "bg", type: "background", paint: { "background-color": b.water } }, ...worldLayers(b)] }, fellBack: true };
  }
}

export async function createMap(container, model, { onPick }) {
  const first = await buildStyle();
  const map = new ml.Map({
    container, style: first.style, center: [110, 20], zoom: Math.max(0, Math.log2(container.clientWidth / 512)),
    dragRotate: false, pitchWithRotate: false, cooperativeGestures: true,
    attributionControl: { compact: true, customAttribution: "Land: Natural Earth · Areas: FAA, NGA via Orbit, Launch's charted notices" },
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
  map.getCanvas().setAttribute("aria-label", "Map of launch and reentry closure areas. Every item on it is also listed on this page.");
  const data = { live: model.live, pads: model.pads, zones: EMPTY, paste: EMPTY };
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
    map.addLayer({ id: "live-fill", type: "fill", source: "la_live", paint: { "fill-color": ink, "fill-opacity": 0.07 } });
    map.addLayer({ id: "live-line", type: "line", source: "la_live", paint: { "line-color": ink, "line-width": 1.3, "line-opacity": 0.8 } });
    map.addLayer({ id: "paste-fill", type: "fill", source: "la_paste", paint: { "fill-color": accent, "fill-opacity": 0.2 } });
    map.addLayer({ id: "paste-line", type: "line", source: "la_paste", paint: { "line-color": accent, "line-width": 2 } });
    map.addLayer({ id: "pads", type: "circle", source: "la_pads", paint: { "circle-radius": 5.5, "circle-color": panel, "circle-stroke-color": actor, "circle-stroke-width": 2.6 } });
  }
  map.on("style.load", addLayers);
  dark.addEventListener("change", async () => { const n = await buildStyle(); note(n.fellBack); map.setStyle(n.style, { diff: false }); });
  const CLICK = ["pads", "live-fill", "zones-fill", "paste-fill"];
  const pick = (pt) => {
    const f = map.queryRenderedFeatures([[pt.x - 6, pt.y - 6], [pt.x + 6, pt.y + 6]], { layers: CLICK.filter((l) => map.getLayer(l)) });
    return f.length ? f[0].properties.key : null;
  };
  map.on("click", (e) => { const k = pick(e.point); if (k) onPick(k); });
  map.on("mousemove", (e) => { map.getCanvas().style.cursor = pick(e.point) ? "pointer" : ""; });

  function set(name, fc) {
    data[name] = fc || EMPTY;
    const s = map.getSource("la_" + name);
    if (s) s.setData(data[name]);
  }
  function fit(fc) {
    const b = new ml.LngLatBounds();
    let n = 0;
    const add = (c) => { if (typeof c[0] === "number") { b.extend(c); n++; } else c.forEach(add); };
    (fc.features || []).forEach((f) => f.geometry && add(f.geometry.coordinates));
    if (n) map.fitBounds(b, { padding: 40, maxZoom: 7, duration: 700 });
  }
  return { set, fit, resize: () => map.resize() };
}
