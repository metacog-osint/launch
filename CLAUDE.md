# Launch

Launch and reentry closure areas (NOTAMs, navigational warnings): live areas, which scheduled launches coincide
with them, a launch history since 2023 (Chinese launches since 2012), and each pad's closure patterns.
`tic-feed/2`, program id `launch`, prefix `LA`, method `launch-1.0`. Observations only. Site:
https://launch.theintelligence.company (Cloudflare Pages project `launch`).

This file is public. Working notes, decisions and the project's history live in `CLAUDE.local.md` (git-ignored)
on the machine that has it: read it too when it is there.

## Commands
```bash
python tools/launch.py history [KML]   # source map export -> history/history.json + history/patterns.json (committed);
                                       # needs the private history/source/terms.json and refuses without it
python tools/launch.py backfill DIR    # GCAT tables -> history/ledger.json (committed baseline)
python tools/launch.py collect         # tfr + orbit lanes -> data/snapshot.json; ledger -> data/ledger.json
python tools/launch.py nfc fetch|build # NotamForChina at the pinned commit -> history/nfc.json (committed)
python tools/launch.py joey fetch|build # Joey0609/notams at the pinned commit -> history/joey.json (committed)
python tools/launch.py wayback fetch|build # Internet Archive copies of FAA TFRs and NGA warnings -> history/wayback.json
python tools/launch.py build           # site/ (incl. data/launches.json, the History tab's list); privacy check on site/
python tools/launch.py check           # registers, feed lint, public gate, privacy check (site/ and tracked files)
python -m unittest discover -s tests   # offline tests
python tools/serve.py                  # http://127.0.0.1:8771 with _headers (CSP)
```
The workflow (`.github/workflows/update.yml`) runs tests, collect, build and check, then deploys `site/`.

## Layout
- `launch/notam.py` NOTAM parser (header, Q-line, items A-G, shapes from the E) text).
- `launch/live.py` live lanes; `launch/feed.py` the feed; `launch/catalog.py` the History tab's list;
  `launch/programs.py` vehicle, site, programme and mission-type names; `launch/patterns.py` pad patterns.
- `launch/history.py` import of the source map; `launch/public.py` the public gate; `launch/privacy.py` the
  privacy check; `launch/nfc.py` NotamForChina; `launch/joey.py` Joey0609/notams;
  `launch/wayback.py` Internet Archive copies, `launch/ngawarn.py` Orbit's NGA warning rules (copied).
- `site_src/` the page: tabs `#live`, `#history`, `#patterns`, `#paste`, `#sources`. `history.js` and `hmap.js`
  are the History tab. `tic-nav.*` and `tic-time.*` are copies from the hub and `doctrine/kit/` from the doctrine
  kit: fix those at their source and copy them in again.

## History
- **Sources, joined into one list** (`data/launches.json`): Launch's charted notices (a hand-built Google My Maps
  map of closure areas, NOTAM texts, flight paths and sites, 2022 onward, imported from an export), GCAT's launches
  since 2023 (orbital, suborbital and missile firings; see Launch kinds), Launch Library 2's schedule, NotamForChina
  (Chinese launches 2012-2026 and their notices) and Joey0609/notams (launch NOTAMs with their text, mostly China's,
  Dec 2020 onward). A record's `sources` holds `chart`, `gcat`, `ll2`, `nfc`, `joey`, `wayback`; `chart` lists the charted events joined into
  it, `chart_time` keeps the time in the charted name, `chart_labels` its other names.
- **Joins:** a charted event and a GCAT launch within 3 h and 200 NM or the same country (pass 1; a suborbital
  launch or missile needs the 200 NM, and a missile fired in combat joins no charted event), or within 72 h,
  200 NM and the same vehicle or programme (pass 2); a charted event holding a NOTAM that NotamForChina lists for a
  GCAT launch (pass 3). A joined record takes GCAT's launch time.
- **Launch kinds** (16 Nov 2026: every one labelled, and each kind easy to show or hide on the map, the list and the
  downloads): every record has a `kind` (`programs.KINDS`), read from GCAT's
  LaunchCode first letter (planet4589.org/space/gcat/web/launch/lcols.html) and Category: Orbital (O, D, N),
  Suborbital rocket (S: sounding rockets, uncrewed New Shepard, HASTE), Crewed suborbital (Y), Atmospheric test (A),
  Missile test (M), Lofted missile test (L), Combat launch (M with category Weapon or Interceptor Weapon), and Not
  known (a charted notice or notice set no GCAT launch is joined to). The backfill keeps all of them since 2023
  (GCAT of 13 Nov 2026: 1,724 = 1,083 orbital + 140 S + 23 Y + 11 A + 153 M tests + 7 L + 307 combat); a
  suborbital record has orbit "Suborbital", no inclination, GCAT's apogee and range (km) and category, and a mission
  type by kind (combat: "Weapon (combat use)"; missiles: missile test; crewed: human spaceflight; others by payload
  names, else science or technology by category). A GCAT site written with "?" is read as that site
  (`site_uncertain`); a site that is a region (mobile launchers, a sea or test-range area) carries `region` and the
  card says so. Orbit publishes orbital launches only, so new suborbital launches arrive when the backfill is run
  again (`python tools/launch.py backfill ../orbit/data/raw` after an Orbit run). Backfill records are stamped
  with GCAT's table date, so Orbit's later reading of a launch wins the merge; the merge keeps the committed
  baseline's sites (names, region flags). The page: a "Show kinds" row of toggles above the map (pressed = shown;
  hiding one writes `kind=` with the kinds still shown), a "Launch kind" filter with GCAT's meaning on each option,
  a Kind column in the list, Kind, category, apogee and range on the card, and a `kind` column in every download.
  Notices: a Joey0609 notice joined by window and an NGA warning join orbital launches only (their nearest-pad
  rule within 5,000 NM cannot tell a missile from an orbital launch in the same window); an archived FAA TFR (100
  NM, nearest in time) joins any launch but a combat one, which brings 10 Space Operations Area TFRs to Wallops,
  Van Horn and Poker Flat flights.
  First build: 2,235 records (1,594 + 641); the 25 Sep 2024 ICBM charted event now joins GCAT's DF-31AG test
  2024-S55 (16 NM, 0 h) instead of the Wenchang orbital launch 2024-174 (1,393 NM).
- **Flight paths:** a charted path is drawn as charted (a great circle per leg); otherwise it is estimated from the
  bearing to the closure areas, the payload's inclination, the orbit class's, or the site's most-used corridor.
  A suborbital launch or missile: as charted, or towards its farthest closure area (at any distance, drawn to it),
  else none. Each record says its basis.
- **Closure areas** are drawn with great-circle edges on every map and the Paste tab (`notam.js` `geodesic()`);
  circles are drawn on the sphere.
- **Globe view** (15 Nov 2026): a globe button under the zoom buttons on both maps (`map.js`
  `addProjectionToggle`), one choice for both, saved in the browser (`localStorage` `launch.projection`, flat by
  default); MapLibre 6.14's own globe projection, put in every style `buildStyle()` makes so the light/dark switch
  keeps it. Fits go through `fitCoords()`: flat, the bounds; globe, the midpoint of the two points farthest apart
  (not the mean: a curved ring's hundreds of vertices pull it), zoomed until all are in view; points no hemisphere
  holds (the 4 Feb 2025 Soyuz-2.1v/Volga launch, Plesetsk to the South Pacific) centre on the pad with the whole
  globe. The globe's scale follows the centre latitude (radius 512 * 2^z / (2pi cos lat)). A map made in a hidden
  tab gets its world zoom when first shown, and a switch at world view goes to the other projection's world view.
- **Trajectory from a pad** (Paste tab, 15 Nov 2026; second of the old launch mapper's features): `site_src/traj.js`
  (pure maths, tested in Node by `tests/test_traj.py`, which checks the inclination against `history.inclination()`)
  and `app.js` `trajRun()`. Pad from Launch's 35 sites or a map click (`map.js` `pickPoint()`); with none chosen, the
  five sites nearest the pasted areas, one click to choose. Per area (polygon, circle or point, nearest first):
  azimuth and distance from the pad to its centre, implied inclination (cos i = cos lat * sin az), orbit type
  (near-equatorial < 10, prograde < 85, near-polar to 95, retrograde; 96-102 named "sun-synchronous range"), the
  mirrored azimuth (180 - az, same inclination on the other branch), and the dog-leg test: every area should lie on
  the great circle from the pad through the farthest area; one more than 25 NM outside it (beyond its own radius) or
  behind the pad is flagged, worded as a possible dog-leg or areas from different events. The map draws the great
  circle pad -> areas (dashed) and the pad. Not ported: the old tool's typed-in dog-leg azimuth.
- **Downloads** (15 Nov 2026; third of the old launch mapper's features): CSV, GeoJSON and KML of the launches in the
  current filters, built in the browser by `site_src/export.js` (pure, tested in Node by `tests/test_export.py`, on
  made-up records and on the whole built list) from the data the page already holds, so a file holds nothing the
  page does not publish. Each launch is its pad, its flight path (the map's lines) and, when "Draw closure areas" is
  ticked, its closure areas, great-circle edges as drawn. Lines and areas crossing the antimeridian are cut there
  (RFC 7946, KML's -180..180). Times UTC at the record's precision; the CSV adds a column in the viewer's zone, named
  in its header, guards text cells against formulas and starts with a byte-order mark. GeoJSON and KML carry the
  sources and licences in their header, the CSV per row. Unnumbered NotamForChina areas carry their FIR.
  `greatCircle()` moved from `hmap.js` to `notam.js` so the export can use it without MapLibre.
- **Ranges** (15 Nov 2026; fifth of the old launch mapper's features): three from/to filters under the facets,
  `history.js` `RANGES`, in the address as `inc=`, `far=`, `plen=` (`lo-hi`, either end open, e.g. `inc=96-102`,
  `far=-500`): GCAT's payload inclination (`inc`), the farthest closure area's distance from the pad (`far_nm`,
  `catalog.farthest_nm()`: the centre of every charted or NotamForChina area, a splashdown too; coincident live
  areas do not count) and a charted path's length (`path.len_nm`, `catalog.path_length_nm()`: its longest line, legs
  summed; estimated paths have none). A launch without the number is hidden while its range is set, and each range
  says how many in the other filters have one. Presets: inclination by the Paste tab's orbit types, distances by
  band. Both distances are on the detail card and in the downloads (`farthest_area_nm`, `path_length_nm`). The
  range inputs are built once (`buildRanges()`) so typing keeps focus; `rangesShow()` refreshes them.
- **Address changes and the maps:** `app.js` listens for `hashchange` from the start, and `initHistory()` no longer
  waits for its map, so tab links and a pasted or hand-edited History address work before (or without) the maps
  loading. On a map 640 px wide or less the credit box starts closed (`map.js` `collapseAttribution()`).
- **One notice per NOTAM:** where the charted notices and NotamForChina hold the same NOTAM (number and a shared
  FIR), the charted text is shown and NotamForChina's ring is a check under it. Order: charted, then Joey0609/notams
  (it carries the text), then NotamForChina.
- **Joey0609/notams** (`launch/joey.py`, MIT, pinned `joey.SHA`): `joey fetch` copies the month files into
  git-ignored `history/joey_source/`; `joey build` keeps launch-related notices only (`joey.launch_related`: the
  parser's launch words or a WM Q-code, or a Chinese FIR's SFC-UNL danger/restricted/prohibited area open at most
  6 h, or at most 4 days in periods of at most 2 h; never a cancellation, a window over 62 days or a
  general-aviation or aerobatics notice) and drops the SOURCE line. Joins (`catalog.py`, Joey section): by NOTAM
  (number and a shared FIR) to the record holding it; else a GCAT launch of the notice's state inside its window
  (2 h either side) with its pad within 5,000 NM of the area (nearest pad; a window over 7 days only when one
  launch qualifies); else counted in `counts.joey`, no record made. `build_site` refuses to build without
  `history/JOEY-NOTAMS-LICENSE.txt` and publishes it beside the data.
- **Internet Archive copies** (`launch/wayback.py`; NGA rules copied from Orbit into `launch/ngawarn.py`):
  `wayback fetch [--since YYYY-MM-DD]` lists captures with the CDX API and fetches originals (`id_`), one request a
  second at most, into git-ignored `history/wayback_source/` with `index.json` (a rerun fetches nothing twice):
  every distinct capture of tfr.faa.gov's list page, the detail page of each SPACE OPERATIONS row (asked at the
  list capture's time, since the FAA reuses page names every year; a page issued over 120 days from its list date is
  refused), and every distinct capture of NGA's broadcast-warn API. `wayback build` -> `history/wayback.json`:
  TFR number, window, location, areas, capture link (a TFR whose page was not read keeps its list row); NGA warnings
  on Orbit's rule. Contacts, phones and emails on the pages are not kept. Joins (`catalog.py`): a TFR of at most 7
  days holding a GCAT launch time (2 h either side) with the pad within 100 NM of its area; an NGA warning window
  holding the launch time with the pad within 5,000 NM. Record key `archive_notices`, source `wayback`. The forum's
  archived copies are never read.
- **Address:** filter state is in the address (`#history?veh=LM-7A&site=Wenchang&...`). Addresses from before
  15 Nov 2026 used other words for the charted source and its flight-path value; `history.js` (`LEGACY`) reads them
  as the new ones. Record ids (`hist:`, `gcat:`, `nfc:`, `ll2:`) did not change, so `sel=` links still work.

## Public gate for the map
`history/history.json` is committed and published as `data/history.json`, so only what the gate clears goes in.
- **Sites:** only a name listed in `history/public_sites.json` is published, with its kind (launch pad, landing
  site, drop zone). A name that reads as a ship or carries a date or a time of day is never published.
- **Notes:** the map's own notes on sites are never published; a site's only note is the text under `notes` in
  `public_sites.json`, and it may hold no speed, heading, coordinate or time of day.
- **Restricted sources:** a note on the map that is not a public notice is not imported, and where it names a
  restricted source its position goes with it (sites, paths and points within 0.5 NM); a note that names a
  position tool takes every shape of its placemark with it. The terms that mark such notes are not in this
  repository: they are in the git-ignored `history/source/terms.json`, and `launch.py history` refuses to run
  without it. Tests use made-up stand-ins (`tests/synthetic_terms.py`).
- **Warning texts:** an official warning is published only when it holds a coordinate.
- **SOURCE lines:** a line saying where a notice came from is never published (`public.SOURCE_LINE`).
- **Ships and bare points:** a placemark named as a ship is not imported; an event's point is imported only when
  its placemark carries a notice; an event with no date, no notice and no shape is not imported.
- **Three checks:** at import, at build (the committed file goes through the gate again) and in `launch.py check`
  on the built file. After a new export or an edit to `public_sites.json`, run `launch.py history` and list each
  new site it names under its kind or under `held`.

## Privacy check (`launch/privacy.py`)
Fails the build (on `site/`), `launch.py check` and the tests (on `site/` and every tracked file) on a listed term.
Public rules, which name nothing private: email addresses, local paths, and a few names matched by SHA-256.
Private rules, added when `history/source/terms.json` is here: the approved term list, reported by number only.
Shared copies (`tic-nav.*`, `tic-time.*`, `doctrine/kit/`) are reported, not failed. Keep `CLAUDE.local.md`,
`history/source/` and anything private out of tracked files.

## Live lanes (`launch/live.py`)
- `tfr`: FAA TFR list, map-service shapes (joined to the active list; the service keeps stale shapes) and the
  XNOTAM XML of each SPACE OPERATIONS TFR. XML times carry a local-zone code, so TFR windows are shown as written.
- `orbit`: Orbit's published `data/snapshot.json` (scheduled launches, GCAT launches, NGA navigational warnings).
- `nms`: `waiting` until the FAA grants NOTAM Management Service access.
- NotamForChina (`launch/nfc.py`, Apache-2.0, pinned commit `nfc.SHA`): `nfc fetch` copies its workbook and
  drop-zone maps into git-ignored `history/nfc_source/`; `nfc build` writes `history/nfc.json`. `build_site`
  refuses to build without `history/NOTAMFORCHINA-LICENSE.txt`, which it publishes beside the data.
- NASASpaceflight forum: linked from history entries, not collected.

## Matching (three levels, all shown; none says an area is for a launch)
time (Orbit's rule) / time and place (azimuth band +-5 deg and downrange 0.5x-50 to 1.25x+100 NM of the pad's
history) / grouped (GCAT launch from that site, within 30 NM, inside the window). The feed carries TFRs and
time-and-place or grouped matches only.

## Tier
A space operations TFR whose XML `dateIssued` (read as UTC) is within 72 h of the run (`feed.NEW_HOURS`) is tier
anomaly, `baseline_ref` `faa-space-ops-tfrs-in-force`; everything else is routine. Cordon leaves these TFRs to
Launch.

## Rules
- Code: GNU AGPL-3.0 (`LICENSE`). Data keeps each source's licence (GCAT CC BY 4.0, NotamForChina Apache-2.0,
  Joey0609/notams MIT, FAA and NGA works of the US Government); the vendored doctrine kit in `doctrine/kit/` keeps
  its own.
- Publicly available information only. Standard library only; tests offline. Times stored UTC.
- Never `git add -A`; name the files. No key files. Never commit `history/source/`, `CLAUDE.local.md` or `.claude/`.
