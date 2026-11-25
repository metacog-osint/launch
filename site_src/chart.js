/* The History tab's chart builder (25 Nov 2026): the launches in the current filters, counted by one field and split
   by another, like a shop's "compare" view turned into a bar chart. Pure: history.js reads the fields (its own facet
   getters, so a chart counts what the filters count) and draws; tests/test_compare_chart.py checks this in Node.

   aggregate(records, { x, split, time, top, splitTop, order })
     x(r)      -> the record's value or values on the bar axis (a launch with two programmes counts in both)
     split(r)  -> the record's one value for the colour split, or omit `split` for one series
     time      -> "year" or "month": keys sort in time order and empty years or months are filled in
     top       -> bars kept (others fold into one "__other" bar), not for time
     splitTop  -> series kept (others fold into "__other")
     order     -> a fixed series order (countries, kinds, outcomes), so a filter never repaints a series
   Returns { cats: [{ key, total, parts: { series: n } }], series: [...], folded: n categories in "__other",
             skipped: records with no value, multi: whether any record counted in more than one bar }. */

export const OTHER = "__other";

function fill(keys, time) {
  if (!keys.length) return keys;
  const out = [], [a, b] = [keys[0], keys[keys.length - 1]];
  if (time === "year") { for (let y = Number(a); y <= Number(b); y++) out.push(String(y)); return out; }
  let [y, m] = a.split("-").map(Number);
  const [by, bm] = b.split("-").map(Number);
  while (y < by || (y === by && m <= bm)) { out.push(`${y}-${String(m).padStart(2, "0")}`); m++; if (m > 12) { m = 1; y++; } }
  return out;
}

export function aggregate(records, { x, split = null, time = null, top = 12, splitTop = 6, order = null } = {}) {
  const cats = new Map(), seriesTotal = new Map();
  let skipped = 0, multi = false;
  for (const r of records || []) {
    const xs = [...new Set([].concat(x(r)).filter((v) => v !== undefined && v !== null && v !== ""))];
    if (!xs.length) { skipped++; continue; }
    if (xs.length > 1) multi = true;
    const s = split ? String(split(r) ?? "") : "";
    for (const v of xs) {
      const k = String(v);
      if (!cats.has(k)) cats.set(k, { key: k, total: 0, parts: new Map() });
      const c = cats.get(k);
      c.total++; c.parts.set(s, (c.parts.get(s) || 0) + 1);
      seriesTotal.set(s, (seriesTotal.get(s) || 0) + 1);
    }
  }
  // Series: a fixed order where one is given (unknown values after it), else by size; past splitTop they fold.
  let series = [...seriesTotal.keys()];
  if (order) series.sort((a, b) => ((order.indexOf(a) + 1 || 1e6) - (order.indexOf(b) + 1 || 1e6)) || seriesTotal.get(b) - seriesTotal.get(a) || a.localeCompare(b));
  else series.sort((a, b) => seriesTotal.get(b) - seriesTotal.get(a) || a.localeCompare(b));
  const keep = new Set(series.slice(0, splitTop));
  const foldSeries = series.length > splitTop;
  series = series.slice(0, splitTop).concat(foldSeries ? [OTHER] : []);
  const parts = (m) => {
    const o = {};
    m.forEach((n, s) => { const k = keep.has(s) ? s : OTHER; o[k] = (o[k] || 0) + n; });
    return o;
  };
  let list;
  if (time) {
    list = fill([...cats.keys()].sort(), time).map((k) => cats.get(k) || { key: k, total: 0, parts: new Map() });
  } else {
    list = [...cats.values()].sort((a, b) => b.total - a.total || a.key.localeCompare(b.key));
  }
  let folded = 0;
  if (!time && list.length > top) {
    const rest = list.slice(top);
    folded = rest.length;
    const o = { key: OTHER, total: 0, parts: new Map() };
    rest.forEach((c) => { o.total += c.total; c.parts.forEach((n, s) => o.parts.set(s, (o.parts.get(s) || 0) + n)); });
    list = list.slice(0, top).concat([o]);
  }
  return { cats: list.map((c) => ({ key: c.key, total: c.total, parts: parts(c.parts) })), series, folded, skipped, multi };
}

/* Round axis ticks for 0..max: 0, then steps of 1, 2 or 5 x 10^n, at most `n` of them past 0. */
export function ticks(max, n = 4) {
  if (!(max > 0)) return [0];
  const raw = max / n, p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw);
  const out = [];
  for (let v = 0; v <= max + 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6);
  if (out[out.length - 1] < max) out.push(Math.round((out[out.length - 1] + step) * 1e6) / 1e6);
  return out;
}

/* The chart's choice in the History address: chart=<by>.<split> ("veh.cc"; "year." for no split). */
export function parseChart(v, byKeys, splitKeys) {
  if (v === null || v === undefined) return null;
  const [by, split = ""] = String(v).split(".");
  if (!byKeys.includes(by)) return null;
  return { by, split: splitKeys.includes(split) ? split : "" };
}
export const chartParam = (c) => (c ? `${c.by}.${c.split || ""}` : null);
