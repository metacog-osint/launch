/* History tab facets that read a record's notices (history.js FACETS), kept apart from the page so they run in Node
   (tests/test_facets.py).
   firs(r, events): the flight information regions (four-letter ICAO codes) of every notice on the record: charted
   notices (`events`, the record's charted events from data/history.json), NotamForChina, Joey0609/notams, stored live
   closures (the code after the NOTAM number), reviewed published notices ("Philippines (RPHI)") and notices saved in
   this browser. Navigational warnings and FAA TFRs carry no FIR.
   joinedBy(r): how notices were tied to the launch, one value per way, worded for the filter panel. */

const FIR = /^[A-Z]{4}$/;
const firOf = (s) => (typeof s === "string" && FIR.test(s.trim()) ? s.trim() : null);

export const NO_FIR = "No FIR";
export const NO_JOIN = "No notice joined";

export function firs(r, events) {
  const out = new Set();
  const add = (v) => { const f = firOf(v); if (f) out.add(f); };
  (events || []).forEach((e) => (e.notams || []).forEach((n) => add((n.q || {}).fir)));
  (r.nfc_notices || []).forEach((n) => String(n.fir || "").split("/").forEach(add));
  (r.joey_notices || []).forEach((n) => { add(n.fir); (n.locations || []).forEach(add); });
  (r.closures || []).forEach((c) => add(String(c.area || "").split(/\s+/)[1]));
  (r.published_notices || []).forEach((n) => { const m = /\(([A-Z]{4})\)\s*$/.exec(n.issuer || ""); if (m) add(m[1]); });
  (r.saved_notices || []).forEach((n) => (n.firs || []).forEach(add));
  return out.size ? [...out].sort() : [NO_FIR];
}

const CHART = {
  0: "Charted notice: same NOTAM number",
  1: "Charted notice: same time and place",
  2: "Charted notice: same vehicle and place, time differs",
  4: "Charted notice: no pad charted, nearest in time",
};
const NFC = {
  tag: "NotamForChina: lists this launch",
  vehicle: "NotamForChina: same vehicle within 3 h",
  slip: "NotamForChina: same vehicle and site within 72 h",
};
const NUMBER = "Notice: same NOTAM number and FIR";
const WINDOW = "Notice: its window holds the launch";

export const JOIN_NOTES = {
  [CHART[0]]: "A charted NOTAM has the number and FIR of one NotamForChina lists for this launch, or of one Joey0609/notams' window places on it.",
  [CHART[1]]: "Within 3 h of the launch, and within 200 NM of its pad or from the same country with no other vehicle named.",
  [CHART[2]]: "Within 72 h and 200 NM, same vehicle or programme.",
  [CHART[4]]: "No pad on the chart: same vehicle (else programme) and country, nearest in time.",
  [NFC.tag]: "NotamForChina's sheet names the GCAT launch.",
  [NFC.vehicle]: "Same vehicle, within 3 h of NotamForChina's time.",
  [NFC.slip]: "Same vehicle and site, within 72 h of NotamForChina's time (a launch that slipped).",
  [NUMBER]: "A notice whose number and FIR match one already on the launch.",
  [WINDOW]: "A notice whose window holds the launch time and whose area is near enough the pad.",
};

export function joinedBy(r) {
  if (r.status === "notice") return ["Notice with no identified launch"];
  const out = new Set();
  [r.join, ...(r.chart_joins || [])].forEach((j) => { if (j && CHART[j.pass]) out.add(CHART[j.pass]); });
  const nb = (r.nfc_join || {}).by;
  if (NFC[nb]) out.add(NFC[nb]);
  else if (nb === "notam") out.add(NUMBER);
  [...(r.joey_notices || []), ...(r.archive_notices || [])].forEach((n) => {
    const by = (n.join || {}).by;
    if (by === "notam") out.add(NUMBER);
    else if (by === "window") out.add(WINDOW);
  });
  if ((r.forum || []).length) out.add("Forum thread");
  if ((r.closures || []).length) out.add("Live closure coincided");
  if ((r.published_notices || []).length) out.add("Published notice (reviewed copy)");
  if ((r.saved_notices || []).length) out.add("Notice saved in this browser");
  return out.size ? [...out] : [NO_JOIN];
}
