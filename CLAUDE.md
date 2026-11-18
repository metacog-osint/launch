# Launch

Launch and reentry closure areas (NOTAMs, navigational warnings): live areas, which scheduled launches coincide
with them, a launch history since 2012, and each pad's closure patterns.
`tic-feed/2`, program id `launch`, prefix `LA`, method `launch-1.0`. Observations only. Site:
https://launch.theintelligence.company (Cloudflare Pages project `launch`).

This file is public. Working notes, decisions and the project's history live in `CLAUDE.local.md` (git-ignored)
on the machine that has it: read it too when it is there.

## Commands
```bash
python tools/launch.py history [KML]   # source map export -> history/history.json + history/patterns.json (committed);
                                       # needs the private history/source/terms.json and refuses without it
python tools/launch.py backfill DIR    # GCAT tables -> history/ledger.json (committed baseline)
python tools/launch.py collect         # tfr, orbit, cordon lanes -> data/snapshot.json; ledger -> data/ledger.json
python tools/launch.py nfc fetch|build # NotamForChina at the pinned commit -> history/nfc.json (committed)
python tools/launch.py nfc links       # its list of forum thread links -> history/nsf_links.json (committed)
python tools/launch.py joey fetch|build # Joey0609/notams at the pinned commit -> history/joey.json (committed)
python tools/launch.py wayback fetch|build # Internet Archive copies of FAA TFRs and NGA warnings -> history/wayback.json
python tools/launch.py build           # site/ (incl. data/launches.json, the History tab's list); privacy check on site/
python tools/launch.py timing          # closure opening to launch by site, from the built list -> history/timing.json
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
  `launch/wayback.py` Internet Archive copies, `launch/ngawarn.py` Orbit's NGA warning rules (copied),
  `launch/nsf.py` NotamForChina's forum thread links; `site_src/saved.js` notices saved from the Paste tab.
- `site_src/` the page: tabs `#live`, `#history`, `#patterns`, `#paste`, `#sources`. `history.js` and `hmap.js`
  are the History tab. `tic-nav.*` and `tic-time.*` are copies from the hub and `doctrine/kit/` from the doctrine
  kit: fix those at their source and copy them in again.

## History
- **Sources, joined into one list** (`data/launches.json`): Launch's charted notices (a hand-built Google My Maps
  map of closure areas, NOTAM texts, flight paths and sites, 2022 onward, imported from an export), GCAT's launches
  since 2012 (orbital, suborbital and missile firings; see Launch kinds and GCAT from 2012), Launch Library 2's schedule, NotamForChina
  (Chinese launches 2012-2026 and their notices) and Joey0609/notams (launch NOTAMs with their text, mostly China's,
  Dec 2020 onward). A record's `sources` holds `chart`, `gcat`, `ll2`, `nfc`, `joey`, `wayback`; `chart` lists the charted events joined into
  it, `chart_time` keeps the time in the charted name, `chart_labels` its other names.
- **Joins:** a charted event and a GCAT launch within 3 h and 200 NM, or the same country when the vehicles do not
  differ (`catalog._other_vehicle()`: both read and neither name starts with the other) (pass 1; a suborbital
  launch or missile needs the 200 NM, and a missile fired in combat joins no charted event; a charted pad at no
  launch site, a path drawn from a point downrange, joins by the same vehicle or programme instead of place and the
  record takes GCAT's pad and vehicle name, keeping the charted start as `chart_pad`), or within 72 h,
  200 NM and the same vehicle or programme (pass 2); a charted event holding a NOTAM that NotamForChina lists for a
  GCAT launch (pass 3); a charted event with no pad (no line was charted, and the pad is a line's first point) joins
  the GCAT launch of the same vehicle (else, where neither vehicle differs, the same programme) and country, nearest in
  time, from 3 h before its window opens to 72 h after it closes (`chart_window()`: "21-30 Apr", "0900-1700"); a
  return or reentry joins nothing (pass 4, 18 Nov 2026: 17 events onto 9 launches, among them Falcon 9/Optus-X,
  Progress MS-34, Starship Flight 8 and RS-24 Yars, read as GCAT's "Yars (missile)"; a record folded by a join keeps
  its `sel=` address). A joined record takes GCAT's launch time.
- **Launch kinds** (16 Nov 2026: every one labelled, and each kind easy to show or hide on the map, the list and the
  downloads): every record has a `kind` (`programs.KINDS`), read from GCAT's
  LaunchCode first letter (planet4589.org/space/gcat/web/launch/lcols.html) and Category: Orbital (O, D, N),
  Suborbital rocket (S: sounding rockets, uncrewed New Shepard, HASTE), Crewed suborbital (Y), Atmospheric test (A),
  Missile test (M), Lofted missile test (L), Combat launch (M with category Weapon or Interceptor Weapon), and Not
  known (a charted notice or notice set no GCAT launch is joined to). The backfill keeps all of them since 2012
  (GCAT of 13 Nov 2026: 4,914; the build of 16 Nov holds 4,917 = 2,263 orbital + 568 S + 69 Y + 91 A + 958 M tests
  + 12 L + 956 combat); a
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
- **GCAT from 2012** (16 Nov 2026; was 2023): `catalog.LEDGER_SINCE` is 2012-01-01, the year NotamForChina starts,
  and the backfill's site table takes every site used since then. Every NotamForChina launch now joins a GCAT launch
  (its own launched records went 304 -> 0), and the archived NGA warnings and FAA TFRs before 2023 have launches to
  join (NGA +82 in 2022). Build: 5,118 records, `launches.json` 4.8 MB (0.62 MB gzipped), about 32 s. In headless
  Chrome the History tab's main thread blocks about 2.2 s in its first 12 s (live, 2,233 records: 1.8-3.9 s),
  longest block 0.8 s, a filter change 0.6 s. Site names: GCAT's GIK-2 (Svobodniy, to 2006) is Svobodny, not
  Vostochny; KLA (Sea Launch) is Kiritimati (sea launch).
- **Pads and site names** (16 Nov 2026): some charted paths were drawn from the far end back to the pad, and the
  import takes the first point of the first path as the pad. `catalog.orient_paths()` turns a line round when its
  last point is a launch site (within `SITE_NM`) and its first is not, and moves a pad at no site to the first line
  start that is one (28 pads were up to 4,800 NM off, with azimuths pointing backwards). A joined launch takes GCAT's
  site name when GCAT's site is within `SITE_NM` of the pad (neighbouring pads: Wenchang and Hainan commercial,
  Cape Canaveral and Kennedy); else the nearest site to the charted pad (sea launches, where GCAT's point is coarse).
- **Flight paths:** a charted path is drawn as charted (a great circle per leg), and its azimuth is the bearing from
  its start to its farthest point within a quarter of the globe, else its first leg's heading (`drawn_heading`: the
  bearing to the end of a path drawn round half the world reads backwards); otherwise it is estimated from the
  bearing to the closure areas, the payload's inclination, the orbit class's, or the site's most-used corridor.
  A south-going path from an inclination at Cape Canaveral or Kennedy (16 Nov 2026) follows the Cape's polar
  corridor: offshore to a turn point off Boca Raton (`programs.POLAR_CORRIDOR`, approximate), then the
  inclination's azimuth from there (`path.via`; `notam.js` `estimatedLine()` draws and exports it, `overfly.py`
  samples it). From the pad, 189 deg crossed about 190 NM of the Florida peninsula, which these launches avoid
  (south-east over the Atlantic, then south along the coast, then over Cuba: Spaceflight Now on OneWeb 16 and
  SAOCOM 1B). Three records: OneWeb-2, PACE, gcat:2025-066.
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
- **Path crosses** (15 Nov 2026; fourth of the old mapper's features, which only guessed "likely crosses land"):
  `launch/overfly.py`, run by `build`, gives each record with a flight path `over`, the countries its ground track
  crosses, one list per path (a charted event's two or three paths longest first), each `[{cc, from, to}]` in order,
  NM from the path's start, from the kit's Natural Earth outlines
  (`doctrine/kit/geo/countries.json`, de facto borders, 0.05 deg). Sampled every 5 NM; land only; gaps under 25 NM
  over one country closed; an enclave the kit keeps without a hole (Lesotho) wins over its neighbour. Shown in the
  detail card (with the caveat that a ground track is not
  airspace), as the "Path crosses" filter (`ovf=` in the address) and in the downloads. About 4 s for all paths.
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
- **Forum threads** (`launch/nsf.py`, 16 Nov 2026): NotamForChina's `data/nsfLinkList.html` at its pinned commit
  (read from GitHub; the forum is never fetched) lists 878 NASASpaceflight threads with their titles; `nfc links`
  writes `history/nsf_links.json` with the date, UTC time and vehicle each title gives (446 dated). `catalog.nsf_join`
  puts a dated thread on a Chinese launch: with a time, the nearest launch within `NSF_HOURS` (3) whose vehicle does
  not differ (LM-11H is LM-11); without one, the only launch of that vehicle that day (a day either side) that also
  shares a payload word with the title (untimed titles often carry a planned date that slipped). A thread the charted
  notices already link is not repeated. First build: 387 threads on 387 launches (9 already charted);
  undated threads (rumours, plans, discussion) join nothing. The card shows each as "Forum thread", linked.
- **Saved notices** (`site_src/saved.js`, the Paste tab, 16 Nov 2026): each pasted notice can be saved to the
  History tab in that browser only (`localStorage` `launch.saved`, at most 500; no server, nothing leaves the
  browser), exported to a JSON file and imported back. On the History tab a saved notice joins, first that applies:
  a launch holding the same NOTAM (number and a shared FIR), else a launched record (not a combat launch) inside its
  window, 2 h either side, with its pad within 5,000 NM of the area (nearest pad, then nearest time; a window over 7
  days only when one launch qualifies), else a record of its own with status "notice". Source `saved`, "Saved in
  this browser"; its areas are drawn; the card shows its text and can remove it. Tested in Node
  (`tests/test_saved.py`).
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
  XNOTAM XML of each SPACE OPERATIONS TFR. Windows are UTC (`live.tfr_windows`, 16 Nov 2026): from the NOTAM text's
  "EFFECTIVE yymmddhhmm UTC ... UNTIL yymmddhhmm UTC" (or the range that ends the text), else `dateEffective` /
  `dateExpire` read as UTC. `codeTimeZone` names the zone the FAA's page displays, not the zone of those fields
  (FDC 6/7113, 15 Nov: 17:01-18:50 with codeTimeZone EST, text "2611151701 UTC ... UNTIL 2611151850 UTC").
  Before this, TFRs had no window and were never time-matched.
- `orbit`: Orbit's published `data/snapshot.json` (scheduled launches, GCAT launches). Its NGA warnings are used
  only until the `cordon` lane has succeeded once.
- `cordon` (17 Nov 2026): Cordon's published `data/feed.geojson`, the NGA warnings in its `launch` category with
  the windows, hazard and cancels Cordon parses (method `cordon-feed-1.1`; Cordon is the suite's one NGA reader).
  `live.cordon_read` keeps those with a launch, debris or reentry hazard (missile firings, hazard null, are left
  out and counted), gives each polygon Orbit's key (`navarea-iv-1081-26`, so match ids did not change) and NGA's
  number, takes area letters from the text when the areas have no windows of their own, and matches on the
  message's windows as before. Checked on the 17 Nov 18:15 UTC feed: the same 12 warnings, polygons, windows,
  hazards, letters and the same 11 matches as Orbit's copy (Orbit's 13th, HYDROPAC 3315/26, had already left
  NGA's own list). Match items cite Cordon as a second source. `launch/ngawarn.py` stays for the Internet
  Archive history only.
- `nms` (`launch/nms.py`, 17 Nov 2026): the FAA NOTAM Management Service API, OAuth2 keys from the environment
  (`NMS_CLIENT_ID`, `NMS_CLIENT_SECRET`; `NMS_ENV` staging or prod, the workflow's default prod); without keys the
  lane says `waiting`. Within the FAA's limits (production: one bulk pull a day, one delta pull every 3 minutes):
  a bulk pull of every active NOTAM (classifications INTERNATIONAL, FDC, MILITARY, DOMESTIC; about 80,000, 9
  requests) when the last is over 24 h old, else one delta (`lastUpdatedDate`, a minute's overlap) applied to the
  notices kept from the last run (in `data/snapshot.json`, so in the Actions cache). Every NOTAM is filtered by
  Launch (`nms.keep`): never a cancellation, a permanent notice, a window over 62 days, an upper limit under FL100,
  or text naming model rockets, gun, mortar or flare firing, lasers, fireworks, displays, balloons, drones,
  detonations; kept for launch words (`WORDS`: `notam.LAUNCH_WORDS` with "stage" only as a rocket's stage, and a
  Q-code of an area, a warning or "other"), China's SFC-UNL rule (`cn-area`, from `joey.py`), any state's
  surface-to-unlimited area or warning with a short window (`unl-area`, the "-UNL" search), or an area from the
  surface, open at most 7 days, centred within 25 NM of a closure area in the history (`recurring-area`). First
  staging pull (17 Nov): 80,134 NOTAMs, 62 kept (words 42, unl-area 10, recurring 6, cn-area 4). An FDC notice the
  tfr lane holds is left to it. The page and the feed say the FAA's terms: redistribution allowed, not called FAA
  data, NMS not authoritative for non-US NOTAMs (`nms.SOURCE_NOTE`).
- **Timing** (`launch/timing.py`, `python tools/launch.py timing` -> committed `history/timing.json`, from the
  built `site/data/launches.json`): for each launch with a GCAT time, the notice nearest the pad (within 450 NM,
  window of 6 h or less) whose window holds the launch; minutes from its opening to the launch, by site (5+
  launches). First table (17 Nov 2026): Jiuquan 40 launches, median 9 min; Xichang 25, 10; Taiyuan 18, 9; Wenchang
  12, 10.1; Cape Canaveral 75, 38.6; Kennedy 35, 39; Wallops 9, 36.8. A live area within 450 NM of such a site,
  window 6 h or less, carries `expect`: "if a launch from <site>, around <opening + median>". History, not a
  forecast.
- NotamForChina (`launch/nfc.py`, Apache-2.0, pinned commit `nfc.SHA`): `nfc fetch` copies its workbook and
  drop-zone maps into git-ignored `history/nfc_source/`; `nfc build` writes `history/nfc.json`. `build_site`
  refuses to build without `history/NOTAMFORCHINA-LICENSE.txt`, which it publishes beside the data.
- NASASpaceflight forum: linked from history entries (the charted notices' links and NotamForChina's thread list), not collected.

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
