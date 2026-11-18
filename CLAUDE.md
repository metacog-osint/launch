# Launch

Launch and reentry closure areas (NOTAMs, navigational warnings): live areas, which scheduled launches coincide
with them, a launch history since 2012, and each pad's closure patterns.
`tic-feed/2`, program id `launch`, prefix `LA`, method `launch-1.0`. Observations only. Site:
https://launch.theintelligence.company (Cloudflare Pages project `launch`).

Public file, lasting facts only (slimmed 18 Nov 2026 from 29 KB; full text in git history and the git-ignored
`history/source/claude-md-archive-2026-11-18.md`). Notes, decisions, state and open items: the git-ignored
`CLAUDE.local.md` and the prompt in `.claude/`, where present. Detail is in each module's docstrings.

## Commands
```bash
python tools/launch.py history [KML]   # map export -> history/history.json + patterns.json; needs history/source/terms.json
python tools/launch.py backfill DIR    # GCAT tables -> history/ledger.json (committed baseline)
python tools/launch.py collect         # tfr, orbit, cordon, nms lanes -> data/snapshot.json, data/ledger.json
python tools/launch.py nfc fetch|build|links  # NotamForChina (pinned) -> history/nfc.json, history/nsf_links.json
python tools/launch.py joey fetch|build       # Joey0609/notams (pinned) -> history/joey.json
python tools/launch.py wayback fetch|build    # Internet Archive FAA TFRs and NGA warnings -> history/wayback.json
python tools/launch.py build           # site/ (incl. data/launches.json); privacy check on site/
python tools/launch.py timing          # opening-to-launch by site -> history/timing.json
python tools/launch.py check           # registers, feed lint, public gate, privacy check
python -m unittest discover -s tests   # offline tests
python tools/serve.py                  # http://127.0.0.1:8771 with _headers (CSP)
```
`.github/workflows/update.yml` (every 6 h at :11, on every push to `main`, by hand) runs tests, collect, build and
check, then deploys `site/`. State (snapshot, ledger, nms and gnss state) is in the private Actions cache; each run
unions the committed baseline, the cache, the published ledger and Orbit's launches, so a lost cache loses nothing.

## Layout
- `launch/`: `notam.py` parser; `live.py` lanes; `feed.py`; `catalog.py` the History list and its joins;
  `programs.py` vehicles, sites, programmes, kinds, mission types; `patterns.py` pad patterns; `overfly.py` path
  crosses; `timing.py`; `history.py` map import; `public.py` public gate; `privacy.py`; `nfc.py`, `joey.py`,
  `wayback.py`, `ngawarn.py` (Orbit's NGA rules, archive only), `nsf.py` forum links, `nms.py`, `gnss.py`.
- `site_src/`: tabs `#live`, `#history`, `#patterns`, `#paste`, `#sources`; `traj.js`, `export.js`, `saved.js`
  tested in Node. `tic-nav.*`, `tic-time.*` (hub) and `doctrine/kit/` are
  copies: fix them at their source and copy in again.

## History (`data/launches.json`, one list)
- **Sources** (`sources`): `chart` (Launch's charted notices: a hand-built Google My Maps map of closure areas,
  NOTAM texts, analyst lines and sites, 2022 on, imported from an export), `gcat` (GCAT since
  `catalog.LEDGER_SINCE` 2012-01-01: orbital, suborbital, missiles), `ll2` (schedule), `nfc` (Chinese launches
  2012-2026), `joey` (launch NOTAMs, mostly China, Dec 2020 on), `wayback`, `saved`. `chart` lists joined charted
  events; `chart_time`, `chart_labels` keep their names. Ids (`hist:`, `gcat:`, `nfc:`, `ll2:`) are stable, and a
  record folded by a join keeps its `sel=` address. A joined record takes GCAT's launch time.
- **Charted-event joins** (`catalog.py`): pass 1, GCAT launch within 3 h and 200 NM, or same country when vehicles
  do not differ (`_other_vehicle()`); suborbital and missiles need the 200 NM; combat joins none; a charted pad at no
  site joins by vehicle or programme and takes GCAT's pad (`chart_pad` keeps the charted one). Pass 2: 72 h, 200
  NM, same vehicle or programme. Pass 3: holds a NOTAM NotamForChina lists for a GCAT launch. Pass 4: no pad, so
  same vehicle (else programme) and country, nearest in time, 3 h before the window (`chart_window()`) to 72 h after.
  A return or reentry joins nothing.
- **Notice joins:** by NOTAM (number and a shared FIR) first. Joey0609 and NGA: window holds the launch (Joey 2 h
  either side, the notice's state), pad within 5,000 NM, nearest; a window over 7 days only when one launch
  qualifies; orbital launches only. Archived FAA TFR: at most 7 days, 2 h either side, pad within 100 NM, any
  non-combat launch. Forum threads (`nsf_join`): timed, nearest Chinese launch within `NSF_HOURS` (3) whose vehicle
  does not differ; untimed, the day's only launch of that vehicle sharing a payload word; undated, none. Saved
  notices: same NOTAM, else as Joey (non-combat), else a record of their own, status "notice".
- **One notice per NOTAM:** shown charted, then Joey0609 (carries text), then NotamForChina; the rest are checks.
- **Launch kinds** (`programs.KINDS`, each shown or hidden on map, list and downloads via `kind=`): GCAT LaunchCode
  first letter and Category: Orbital (O, D, N), Suborbital rocket (S), Crewed suborbital (Y), Atmospheric test (A),
  Missile test (M), Lofted missile test (L), Combat launch (M with Weapon or Interceptor Weapon), Not known (a
  charted notice or notice set no GCAT launch joins). Suborbital: orbit "Suborbital", apogee, range (km), category.
  GCAT "?" sites are read as that site (`site_uncertain`); regions carry `region`.
- **Backfill:** Orbit publishes orbital launches only; run `python tools/launch.py backfill ../orbit/data/raw` after
  an Orbit run for suborbital launches and missiles. Orbit's later reading wins the merge. GIK-2 is Svobodny, not Vostochny; KLA is Kiritimati (sea launch).
- **Pads and site names:** `catalog.orient_paths()` reverses a charted line whose last point, not first, is a site
  (within `SITE_NM`) and moves a pad at no site to a line start that is one. A joined launch takes GCAT's site name
  when within `SITE_NM`, else the site nearest the charted pad.
- **Flight paths:** a charted line is drawn as charted, azimuth to its farthest point within a quarter globe, else
  its first leg (`drawn_heading`). Otherwise estimated from the closure areas' bearing, payload inclination, orbit
  class, or the site's main corridor; Cape south-going paths follow `programs.POLAR_CORRIDOR` (turn point off Boca
  Raton, approximate; `path.via`). Suborbital and missiles: as charted, or towards the farthest area, else none.
  Each record says its basis. The charted lines are analyst guesses, not flight paths: the charted-map plan in
  `.claude/` moves every record to one computed method and drops the lines.
- **Path crosses** (`overfly.py`): `over`, per path `[{cc, from, to}]` in NM, from the kit's de facto borders; 5 NM
  samples, land only, gaps under 25 NM closed. A ground track is not airspace (the card says so). Filter `ovf=`.
- **Ranges** (`history.js` `RANGES`, `inc=`, `far=`, `plen=` as `lo-hi`, open ends): payload inclination, farthest
  area from the pad (`catalog.farthest_nm()`, charted and NotamForChina areas, not live), charted path length
  (`path.len_nm`). A launch without the number hides while its range is set.
- **Downloads** (`export.js`): CSV, GeoJSON, KML of the filtered launches, only data the page holds; antimeridian
  cut; UTC plus the viewer's named zone; formula-guarded CSV; sources and licences in every file.
- **Maps:** great-circle edges (`geodesic()`), globe toggle (`launch.projection`), `fitCoords()`. Filters live in
  the address (`#history?veh=...`); `history.js` `LEGACY` reads pre-15 Nov 2026 words.
- **Paste tab:** trajectory from a pad (`traj.js`, dog-leg flag at 25 NM off the great circle); saved notices stay
  in the browser (`localStorage` `launch.saved`).
- **Source rules:** NotamForChina (Apache-2.0, `nfc.SHA`) and Joey0609/notams (MIT, `joey.SHA`) are fetched into
  git-ignored folders; `build_site` refuses without their licence files and publishes them. `joey.launch_related`
  never keeps a cancellation, a window over 62 days or GA/aerobatics; SOURCE lines dropped. `wayback`: one request
  a second at most, no refetch, detail pages asked at the list capture's time (FAA reuses names), contacts not kept.
  The NASASpaceflight forum and its archived copies are never fetched; threads come from NotamForChina's list.

## Public gate for the map
`history/history.json` is committed and published, so only what the gate clears goes in.
- Sites: only names in `history/public_sites.json`, with their kind; a ship name or a date or time of day never.
- Notes: the map's own notes never; a site's only note is `notes` in `public_sites.json` (no speed, heading,
  coordinate or time of day).
- Restricted sources: a note that is not a public notice is not imported; one naming a restricted source takes its
  position (within 0.5 NM) with it; one naming a position tool takes every shape of its placemark. The marking terms
  are only in the git-ignored `history/source/terms.json`; tests use stand-ins (`tests/synthetic_terms.py`).
- Warning texts only with a coordinate; SOURCE lines never (`public.SOURCE_LINE`); ships and bare points not imported.
- Checked at import, at build and in `check`. After a new export or a `public_sites.json` edit, run `history` and
  list each new site under its kind or `held`.

## Privacy check (`launch/privacy.py`)
Fails build, `check` and tests on a listed term in `site/` or any tracked file. Public rules: emails, local paths,
names by SHA-256. Private rules from `history/source/terms.json`, reported by number only. Shared copies are
reported, not failed.

## Live lanes (`launch/live.py`)
- `tfr`: FAA TFR list, map-service shapes (joined to the active list), XNOTAM XML of each SPACE OPERATIONS TFR.
  Windows UTC (`tfr_windows`): the text's EFFECTIVE...UNTIL UTC, else `dateEffective`/`dateExpire` as UTC;
  `codeTimeZone` is only the FAA page's display zone.
- `orbit`: Orbit's `data/snapshot.json` (scheduled and GCAT launches, payload `inc`); its NGA warnings only until
  `cordon` has succeeded once.
- `cordon`: Cordon's feed, `launch` category (the one NGA reader): launch, debris, reentry hazards; Orbit's keys.
- `nms` (`nms.py`): FAA NMS-API, keys `NMS_CLIENT_ID`/`NMS_CLIENT_SECRET`, `NMS_ENV` (workflow default prod);
  no keys, `waiting`. FAA limits: one bulk a day (~80,000 NOTAMs), else one delta every 3 min on the kept set.
  `nms.keep`: no cancels, permanent notices, windows over 62 days, tops under FL100 or non-launch hazards; kept for launch words, area/warning Q-codes, `cn-area`,
  `unl-area`, `recurring-area` (within 25 NM of a historical area). FDC notices the tfr lane holds go to it. FAA
  terms (`nms.SOURCE_NOTE`): redistribution allowed, never "FAA data", not authoritative for non-US NOTAMs.
- **GPS/GNSS NOTAMs** (`gnss.py`, `gnss-1.0`, for Noisefloor): a second subset of the same pulls, no launch filters
  (Q-code GA/GW, signal text, `refers`). Publishes `data/gnss-notams/active.json`, one
  `YYYY-MM-DD.json` per ended UTC day (rewritten up to 48 h, n=0 days included), 14 days, `index.json`.
- **Timing** (`timing.py`): median opening-to-launch per site (5+ launches; 450 NM, windows 6 h or less) gives
  nearby live areas an `expect`. History, not a forecast.

## Matching (three levels, all shown; none says an area is for a launch)
time (Orbit's rule) / time and place (azimuth +-5 deg, downrange 0.5x-50 to 1.25x+100 NM of the pad's history) /
grouped (GCAT launch from that site, within 30 NM, in the window). The feed carries TFRs and the last two only.

## Tier
A space operations TFR whose XML `dateIssued` (UTC) is within 72 h of the run (`feed.NEW_HOURS`) is anomaly,
`baseline_ref` `faa-space-ops-tfrs-in-force`; else routine. Cordon leaves these TFRs to Launch.

## Rules
- Code GNU AGPL-3.0. Data keeps each source's licence (GCAT CC BY 4.0, NotamForChina Apache-2.0, Joey0609 MIT,
  FAA and NGA US Government works); `doctrine/kit/` keeps its own.
- Publicly available information only. Standard library only; tests offline. Times stored UTC.
- Never `git add -A`; name files. No key files. Never commit `history/source/`, `CLAUDE.local.md` or `.claude/`.
- Copy `history/source/terms.json` into a new worktree, or `history` and `check` refuse.
