/* The History tab's downloads: the launches in the current filters as CSV, GeoJSON (RFC 7946) or KML 2.2, built in
   the browser from the data the page already holds (data/launches.json, data/history.json), so a file holds nothing
   the page does not publish. Pure functions, no DOM: tests/test_export.py runs them in Node; history.js wires them
   to the buttons. (The third of the old launch mapper's features; its exports were of one analysis, these are of
   the History view.)

   Each launch is its pad (a point), its flight path (as charted, or estimated from an azimuth: the lines the map
   draws) and, when the view draws them, its closure areas. Lines and area edges are great circles, a point every
   25 NM, as on the map. The map lets longitudes run past 180 so a line stays whole; a file must not (RFC 7946 3.1.9,
   KML's -180..180), so lines and areas that cross the antimeridian are cut there into two parts. Times are UTC in
   every file; the CSV adds a column in the viewer's zone, named in its header. Each file names its sources and
   their licences (GeoJSON and KML in their header; the CSV per row, in its sources column). */
import { geodesic, greatCircle } from "./notam.js";

export const ATTRIBUTION = "Launch (The Intelligence Company), launch.theintelligence.company. Launches: GCAT "
  + "(J. McDowell, planet4589.org/space/gcat), CC BY 4.0; Launch Library 2 (The Space Devs); Launch's charted notices. "
  + "Chinese notices: NotamForChina (mikezang, github.com/mikezang/NotamForChina), Apache License 2.0. Publicly "
  + "available information; observations, not warnings.";
const SOURCE = { chart: "Launch's charted notices", gcat: "GCAT", ll2: "Launch Library 2", nfc: "NotamForChina" };
const PATH = { drawn: "As charted", estimated: "Estimated from an azimuth" };
const BIG = { US: "us", CN: "cn", RU: "ru" };
const group = (cc) => BIG[cc] || "other";
const r4 = (x) => Math.round(x * 1e4) / 1e4;

export const outcome = (r) => (r.status === "upcoming" ? "Scheduled" : r.outcome === "success" ? "Success" : r.outcome ? "Failure or partial" : "Not known");
export const pathName = (r) => (r.path ? PATH[r.path.kind] || r.path.kind : "None");

/* A record's time in UTC at the precision it has: a full time, a date, or a month. */
export function utcTime(r) {
  if (!r.time) return "";
  if (r.time_basis === "date") return r.time.slice(0, 10);
  if (r.time_basis === "month") return r.time.slice(0, 7);
  return r.time.replace(/:00Z$/, "Z").replace(/\.\d+Z$/, "Z");
}

/* ---------- geometry for one record (the same lines and rings hmap.js draws) ---------- */
export function geometry(r, events, withAreas) {
  const paths = !r.path ? [] : r.path.kind === "drawn"
    ? events.flatMap((e) => e.paths || []).filter((p) => p.length >= 2).map(geodesic)
    : r.pad ? [greatCircle(r.pad[0], r.pad[1], r.path.az, r.path.nm)] : [];
  const areas = !withAreas ? [] : [
    ...events.flatMap((e) => (e.areas || []).map((a) => ({ ring: a.ring, notam: a.notam || "", source: "chart" }))),
    ...(r.closures || []).map((c) => ({ ring: c.ring, notam: c.notam || "", source: "closure" })),
    ...(r.nfc_notices || []).filter((n) => n.ring && n.ring.length >= 3).map((n) => ({ ring: n.ring, notam: n.number || "", fir: n.fir || "", source: "nfc" })),
  ].map((a) => ({ ...a, ring: geodesic(a.ring) }));
  return { paths, areas };
}

/* ---------- the antimeridian ---------- */
const band = (x) => Math.floor((x + 180) / 360); // 0 for -180..180, 1 for 180..540, -1 for -540..-180
const shift = (pts, k) => pts.map(([x, y]) => [r4(x - 360 * k), r4(y)]);

/* A line whose longitudes run on past 180 -> one or more parts, each within -180..180. */
export function splitLine(line) {
  const parts = [];
  let cur = [line[0]];
  for (let i = 1; i < line.length; i++) {
    const q = line[i - 1], p = line[i];
    let bq = band(q[0]);
    const bp = band(p[0]);
    while (bq !== bp) {
      const X = bp > bq ? 180 + 360 * bq : -180 + 360 * bq;
      const y = q[1] + ((X - q[0]) / (p[0] - q[0])) * (p[1] - q[1]);
      cur.push([X, y]); parts.push(cur);
      cur = [[X, y]]; bq += bp > bq ? 1 : -1;
    }
    cur.push(p);
  }
  parts.push(cur);
  // A part's band is that of its first leg's midpoint (its first point can sit on the boundary itself).
  return parts.filter((pts) => pts.length >= 2).map((pts) => shift(pts, band((pts[0][0] + pts[1][0]) / 2)));
}

/* Sutherland-Hodgman against one vertical line: keep x <= X (keep = -1) or x >= X (keep = 1). */
function clipX(ring, X, keep) {
  const inside = (p) => (keep < 0 ? p[0] <= X : p[0] >= X);
  const out = [];
  for (let i = 0; i < ring.length - 1; i++) {
    const a = ring[i], b = ring[i + 1];
    const ia = inside(a), ib = inside(b);
    if (ia) out.push(a);
    if (ia !== ib) out.push([X, a[1] + ((X - a[0]) / (b[0] - a[0])) * (b[1] - a[1])]);
  }
  if (out.length) out.push(out[0]);
  return out;
}
const signedArea = (ring) => ring.slice(0, -1).reduce((s, p, i) => s + p[0] * ring[i + 1][1] - ring[i + 1][0] * p[1], 0) / 2;
const ccw = (ring) => (signedArea(ring) < 0 ? ring.slice().reverse() : ring); // RFC 7946 3.1.6: exteriors anticlockwise

/* A closed ring whose longitudes may run past 180 -> one or more rings, each within -180..180. */
export function splitRing(ring) {
  const closed = ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ? [...ring, ring[0]] : ring;
  const xs = closed.map((p) => p[0]);
  const lo = band(Math.min(...xs)), hi = band(Math.max(...xs));
  const out = [];
  for (let k = lo; k <= hi; k++) {
    let part = closed;
    if (k > lo) part = clipX(part, -180 + 360 * k, 1);
    if (k < hi) part = clipX(part, 180 + 360 * k, -1);
    if (part.length >= 4 && Math.abs(signedArea(part)) > 1e-9) out.push(ccw(shift(part, k)));
  }
  return out;
}

/* ---------- what a record says ---------- */
const areaCount = (r, events) => events.reduce((n, e) => n + (e.areas || []).length, 0) + (r.closures || []).length
  + (r.nfc_notices || []).filter((n) => n.ring && n.ring.length >= 3).length;
export function notams(r, events) {
  const seen = new Set();
  events.forEach((e) => (e.notams || []).forEach((n) => n.number && seen.add(n.number)));
  (r.nfc_notices || []).forEach((n) => n.number && seen.add(n.number));
  return [...seen];
}

export function properties(r, events, o) {
  return {
    id: r.id, label: r.label || "", status: r.status, time_utc: utcTime(r), time_precision: r.time_basis,
    country: r.actor || "", country_name: o.countryName(r.actor), vehicle: r.vehicle || "", payload: r.payload || "",
    programmes: (r.programmes || []).join("; "), mission_type: r.mtype || "", site: r.site || "", orbit: r.orbit || "",
    inclination_deg: r.inc ?? null, outcome: outcome(r), flight_path: pathName(r),
    path_azimuth_deg: r.path && r.path.az != null ? r.path.az : null, path_basis: (r.path && r.path.basis) || "",
    path_length_nm: (r.path && r.path.len_nm) ?? null, farthest_area_nm: r.far_nm ?? null,
    notams: notams(r, events).join("; "), sources: (r.sources || []).map((s) => SOURCE[s] || s).join("; "),
    gcat: r.gcat || "", ll2: r.ll2_url || "", link: o.link(r.id),
  };
}

/* ---------- GeoJSON ---------- */
const lineGeom = (lines) => {
  const parts = lines.flatMap(splitLine);
  return parts.length === 1 ? { type: "LineString", coordinates: parts[0] } : { type: "MultiLineString", coordinates: parts };
};
const polyGeom = (ring) => {
  const parts = splitRing(ring);
  return !parts.length ? null : parts.length === 1 ? { type: "Polygon", coordinates: [parts[0]] } : { type: "MultiPolygon", coordinates: parts.map((p) => [p]) };
};

export function toGeoJSON(rows, o) {
  const features = [];
  rows.forEach((r) => {
    const evs = o.eventsFor(r), props = properties(r, evs, o), g = geometry(r, evs, o.withAreas);
    features.push({ type: "Feature", id: r.id, properties: { feature: "launch", ...props },
      geometry: r.pad ? { type: "Point", coordinates: [r4(r.pad[0]), r4(r.pad[1])] } : null });
    if (g.paths.length) features.push({ type: "Feature", properties: { feature: "flight path", id: r.id, label: props.label, flight_path: props.flight_path, path_basis: props.path_basis }, geometry: lineGeom(g.paths) });
    g.areas.forEach((a) => {
      const geom = polyGeom(a.ring);
      if (geom) features.push({ type: "Feature", properties: { feature: "closure area", id: r.id, label: props.label, notam: a.notam, fir: a.fir || "", source: SOURCE[a.source] || "Closure" }, geometry: geom });
    });
  });
  return { type: "FeatureCollection", name: "Launch history", generated: o.generated, view: o.view, attribution: ATTRIBUTION, features };
}

/* ---------- KML ---------- */
const xml = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const coordText = (pts) => pts.map(([x, y]) => `${r4(x)},${r4(y)}`).join(" ");
// KML colours are aabbggrr. The light theme's actor colours (style.css --g-us, --g-cn, --g-ru, --g-other).
const HEX = { us: "2a78d6", cn: "eb6834", ru: "1baf7a", other: "a7adb5" };
const kmlColour = (hex, alpha) => alpha + hex.slice(4, 6) + hex.slice(2, 4) + hex.slice(0, 2);
const LABELS = { label: "Name", status: "Status", time_utc: "Time (UTC)", time_precision: "Time precision", country_name: "Country",
  vehicle: "Vehicle", payload: "Payload", programmes: "Programmes", mission_type: "Mission type", site: "Launch site",
  orbit: "Orbit", inclination_deg: "Inclination (deg)", outcome: "Outcome", flight_path: "Flight path",
  path_azimuth_deg: "Path azimuth (deg)", path_basis: "Path basis", path_length_nm: "Charted path length (NM)",
  farthest_area_nm: "Farthest closure area (NM from the pad)", notams: "NOTAMs", sources: "Sources", gcat: "GCAT",
  ll2: "Launch Library 2", link: "On Launch" };

export function toKML(rows, o) {
  const out = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2">', "<Document>",
    "<name>Launch history</name>", `<description>${xml(`${rows.length} launches. Generated ${o.generated}. View: ${o.view}. ${ATTRIBUTION}`)}</description>`];
  Object.entries(HEX).forEach(([g, hex]) => out.push(
    `<Style id="pad-${g}"><IconStyle><color>${kmlColour(hex, "ff")}</color><scale>0.8</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle></Style>`,
    `<Style id="path-${g}"><LineStyle><color>${kmlColour(hex, "e6")}</color><width>2</width></LineStyle></Style>`,
    `<Style id="area-${g}"><LineStyle><color>${kmlColour(hex, "cc")}</color><width>1</width></LineStyle><PolyStyle><color>${kmlColour(hex, "33")}</color></PolyStyle></Style>`));
  rows.forEach((r) => {
    const evs = o.eventsFor(r), props = properties(r, evs, o), g = geometry(r, evs, o.withAreas), gp = group(r.actor);
    const name = xml([props.time_utc.slice(0, 10), props.vehicle, props.payload && props.payload !== props.vehicle ? props.payload : ""].filter(Boolean).join(" ") || props.label || r.id);
    const when = r.time ? `<TimeStamp><when>${xml(props.time_utc)}</when></TimeStamp>` : "";
    const data = Object.entries(LABELS).filter(([k]) => props[k] !== "" && props[k] != null)
      .map(([k, l]) => `<Data name="${k}"><displayName>${xml(l)}</displayName><value>${xml(props[k])}</value></Data>`).join("");
    out.push(`<Folder><name>${name}</name>`);
    if (r.pad) out.push(`<Placemark><name>${name}</name>${when}<styleUrl>#pad-${gp}</styleUrl><ExtendedData>${data}</ExtendedData><Point><coordinates>${coordText([r.pad])}</coordinates></Point></Placemark>`);
    else out.push(`<Placemark><name>${name}</name>${when}<ExtendedData>${data}</ExtendedData></Placemark>`);
    const lines = g.paths.flatMap(splitLine);
    if (lines.length) {
      const ls = lines.map((l) => `<LineString><tessellate>1</tessellate><coordinates>${coordText(l)}</coordinates></LineString>`);
      out.push(`<Placemark><name>${xml("Flight path: " + props.flight_path)}</name>${when}<styleUrl>#path-${gp}</styleUrl>${ls.length === 1 ? ls[0] : `<MultiGeometry>${ls.join("")}</MultiGeometry>`}</Placemark>`);
    }
    g.areas.forEach((a) => {
      const rings = splitRing(a.ring);
      if (!rings.length) return;
      const ps = rings.map((ring) => `<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>${coordText(ring)}</coordinates></LinearRing></outerBoundaryIs></Polygon>`);
      out.push(`<Placemark><name>${xml("Closure area" + (a.notam ? " " + a.notam : a.fir ? " (" + a.fir + ")" : ""))}</name>${when}<styleUrl>#area-${gp}</styleUrl>${ps.length === 1 ? ps[0] : `<MultiGeometry>${ps.join("")}</MultiGeometry>`}</Placemark>`);
    });
    out.push("</Folder>");
  });
  out.push("</Document>", "</kml>");
  return out.join("\n");
}

/* ---------- CSV (RFC 4180; a byte-order mark so spreadsheet programs read it as UTF-8) ---------- */
const NUMERIC = new Set(["pad_lat", "pad_lon", "inclination_deg", "path_azimuth_deg", "path_length_nm", "farthest_area_nm", "closure_areas"]);
function cell(k, v) {
  if (v === null || v === undefined) return "";
  let s = String(v);
  // Text that begins with = + - @ or a tab gets a leading apostrophe, so spreadsheets show it as text, not a formula.
  if (!NUMERIC.has(k) && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCSV(rows, o) {
  const cols = ["id", "status", "time_utc", "when_local", "time_precision", "country", "country_name", "label", "vehicle",
    "payload", "programmes", "mission_type", "site", "pad_lat", "pad_lon", "orbit", "inclination_deg", "outcome",
    "flight_path", "path_azimuth_deg", "path_basis", "path_length_nm", "farthest_area_nm", "closure_areas", "notams", "sources", "gcat", "ll2", "link"];
  const head = cols.map((c) => (c === "when_local" ? `when (${o.zone})` : c));
  const lines = [head.map((h) => cell("", h)).join(",")];
  rows.forEach((r) => {
    const evs = o.eventsFor(r), p = properties(r, evs, o);
    const v = { ...p, when_local: r.time ? o.when(r) : "", pad_lat: r.pad ? r4(r.pad[1]) : null, pad_lon: r.pad ? r4(r.pad[0]) : null,
      closure_areas: areaCount(r, evs) };
    lines.push(cols.map((c) => cell(c, v[c])).join(","));
  });
  return "﻿" + lines.join("\r\n") + "\r\n";
}

export const fileName = (kind, generated) => `launch-history-${generated.slice(0, 10)}.${kind}`;
