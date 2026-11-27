/* The History tab's compare tray (25 Nov 2026): up to four launches picked from the list or the detail card, shown
   side by side with their key facts, and rows that differ marked. Pure: history.js defines the rows (label and how
   each is read) and draws; tests/test_compare_chart.py checks this in Node. The tray is kept in the address
   (cmp=<id>|<id>), so a comparison can be shared. */

export const MAX = 4;

/* The ids from the address, in order, without repeats, at most MAX. */
export const parseIds = (v) => [...new Set(String(v || "").split("|").filter(Boolean))].slice(0, MAX);

/* Add or remove one id. Adding to a full tray changes nothing and says so. */
export function toggle(ids, id) {
  if (ids.includes(id)) return { ids: ids.filter((x) => x !== id), full: false };
  if (ids.length >= MAX) return { ids, full: true };
  return { ids: [...ids, id], full: false };
}

/* Rows for the side-by-side table: [{ label, cells: [text per record], differ }]. A row every record leaves empty
   is dropped. `differ` is true when the records do not all share one value (an empty cell counts as a value). */
export function rows(records, fields) {
  return fields.map((f) => {
    const cells = records.map((r) => { const v = f.get(r); return v === null || v === undefined ? "" : String(v); });
    return { label: f.label, cells, differ: records.length > 1 && new Set(cells).size > 1 };
  }).filter((row) => row.cells.some((c) => c !== ""));
}
