/* The upcoming-launch board on the Live tab (25 Nov 2026): every launch scheduled in the next 14 days, soonest first,
   with its country, site, status, how often its NET has moved and the live closures it coincides with. Pure: app.js
   draws the rows, tests/test_layers.py checks them in Node. Records come from data/launches.json (status
   "upcoming"); the NET moves from data/upcoming.json (Launch's multi-source schedule), joined on the LL2 id. */

/* One row per scheduled launch: { r, id, net, actor, site, status, moves, lastMove, path, pad, other }.
   `sched` is data/upcoming.json's records (may be empty: the board then shows no moves). A record whose NET can't be
   read sorts last. */
export function boardRows(records, sched) {
  const byLl2 = new Map((sched || []).map((x) => [(x.refs || {}).ll2, x]));
  const rows = (records || []).filter((r) => r.status === "upcoming").map((r) => {
    const x = byLl2.get(r.ll2) || {};
    const moves = Array.isArray(x.net_moves) ? x.net_moves : [];
    const cl = ((r.live || {}).closures) || [];
    return {
      r, id: r.id, net: r.time || null, actor: r.actor || null, site: r.site || r.pad_name || "", status: r.ll2_status || "",
      moves: Number.isFinite(x.net_changes) ? x.net_changes : moves.length, lastMove: moves.length ? moves[moves.length - 1] : null,
      path: cl.filter((c) => c.role === "path").length, pad: cl.filter((c) => c.role === "pad").length,
      other: cl.filter((c) => c.role !== "path" && c.role !== "pad").length,
    };
  });
  return rows.sort((a, b) => (a.net || "￿").localeCompare(b.net || "￿") || a.id.localeCompare(b.id));
}

/* "2 times; last later by 1 day 2 h" from a row (later or earlier, rounded to the hour; under an hour in minutes). */
export function moveText(row) {
  if (!row.moves) return "Not moved";
  const times = row.moves === 1 ? "Once" : `${row.moves} times`;
  const m = row.lastMove;
  const a = m && Date.parse(m.from || ""), b = m && Date.parse(m.to || "");
  if (!m || !Number.isFinite(a) || !Number.isFinite(b) || a === b) return times;
  const d = Math.abs(b - a) / 60000, dir = b > a ? "later" : "earlier";
  if (d < 60) return `${times}; last ${Math.round(d)} min ${dir}`;
  const h = Math.round(d / 60), days = Math.floor(h / 24), hh = h % 24;
  return `${times}; last ${days ? `${days} day${days === 1 ? "" : "s"}${hh ? ` ${hh} h` : ""}` : `${hh} h`} ${dir}`;
}

/* "2 on the path, 1 at the pad" (or "None"). */
export function closureText(row) {
  const parts = [];
  if (row.path) parts.push(`${row.path} on the path`);
  if (row.pad) parts.push(`${row.pad} at the pad`);
  if (row.other) parts.push(`${row.other} elsewhere`);
  return parts.length ? parts.join(", ") : "None";
}
