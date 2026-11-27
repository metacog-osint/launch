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

/* A launch whose objects Orbit lists: an orbital launch (Launch's kind "Orbital", launch/programs.py KINDS[0]) with a
   GCAT tag. A missile test or suborbital flight puts nothing in orbit, so it gets no payload cell and no Orbit link. */
export const inOrbit = (r) => !!(r && r.gcat && r.kind === "Orbital");

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

/* The Live list's rows (24 Nov 2026), one per launch and notice. A notice's lettered areas (NAVAREA XII 836/26 A, B
   and C) match one by one, since the ledger keeps each ring, and fold here into one row: the best-rated part leads
   (grouped, then time and place, then time; nearest first), `parts` are the letters and `nm`/`az` the range over the
   parts. `also`: the other launches the same notice coincides with in time and place or grouped, on a time-only row.
   `far`: a time-only row more than `farNm` from the pad that names nothing and fits no ground track. A notice that
   stands for days far from a pad holds some launch's time almost always, so such rows fold away until asked for. */
const RANK = { grouped: 0, "time and place": 1, time: 2 };
const rank = (m) => (m.level in RANK ? RANK[m.level] : 3);
export function groupMatches(ms, areas, farNm = 1500) {
  const by = new Map();
  (ms || []).forEach((m) => {
    const k = m.launch + "\u0000" + m.area;
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(m);
  });
  const rows = [...by.values()].map((g) => {
    const s = g.slice().sort((a, b) => rank(a) - rank(b) || a.distance_nm - b.distance_nm);
    const lead = s[0], nm = s.map((m) => m.distance_nm), az = s.map((m) => m.azimuth);
    const labels = s.map((m) => ((areas || [])[m.area_i] || {}).label || "");
    const named = s.find((m) => m.named) || null;
    return { ...lead, named: named ? named.named : null, named_by: named ? named.named_by : null,
      parts: s.length > 1 && labels.every(Boolean) ? labels.slice().sort() : [], area_is: s.map((m) => m.area_i),
      nm: [Math.min(...nm), Math.max(...nm)], az: [Math.min(...az), Math.max(...az)], also: [], far: false };
  });
  rows.forEach((r) => {
    if (r.level !== "time") return;
    r.also = [...new Set(rows.filter((o) => o.area === r.area && o.launch !== r.launch && rank(o) <= 1).map((o) => o.launch_name))];
    r.far = r.nm[0] > farNm && !r.named && !r.track;
  });
  return rows.sort((a, b) => (a.net < b.net ? -1 : a.net > b.net ? 1 : rank(a) - rank(b) || a.nm[0] - b.nm[0]));
}
