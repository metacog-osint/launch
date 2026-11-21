/* The Live tab's scheduled-launch paths and its past-week list. Pure functions, no DOM: tests/test_live_paths.py runs
   them in Node. The paths themselves are worked out at build (catalog.live_paths()): `r.path` is the estimate and
   `r.live.closures` the live areas that coincide with the launch, each with its role:
     path         on the estimated path
     pad          at the pad (nearer than the distance an ascent is read from)
     coincidence  the time fits but the place does not, with `why`
   None of the roles says an area is for the launch. */

/* A scheduled launch whose estimated path runs through at least one live closure area. */
export const hasLivePath = (r) => !!(r && r.status === "upcoming" && r.pad && r.path && r.path.az !== null
  && r.path.az !== undefined && r.path.nm && ((r.live || {}).closures || []).some((c) => c.role === "path"));

export const livePathRecords = (records) => (records || []).filter(hasLivePath);

/* Index in snapshot.areas -> the launches whose path or pad it is tied to (soonest first). */
export function tiedAreas(records) {
  const out = new Map();
  (records || []).filter((r) => r.status === "upcoming" && r.live)
    .sort((a, b) => ((a.time || "") < (b.time || "") ? -1 : 1))
    .forEach((r) => {
      if (!hasLivePath(r)) return;
      r.live.closures.filter((c) => c.role === "path" || c.role === "pad").forEach((c) => {
        if (!out.has(c.i)) out.set(c.i, []);
        out.get(c.i).push(r);
      });
    });
  return out;
}

/* Launches flown in the `days` before `now`, newest first. */
export function pastWeek(records, now, days = 7) {
  const end = Date.parse(now);
  if (Number.isNaN(end)) return [];
  const start = end - days * 86400000;
  return (records || []).filter((r) => {
    if (r.status !== "launched" || !r.time) return false;
    const t = Date.parse(r.time);
    return t >= start && t <= end;
  }).sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
}

/* The History tab's address for one record. */
export const historyHref = (r) => "#history?sel=" + encodeURIComponent(r.id);
