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
  privacy check; `launch/nfc.py` NotamForChina.
- `site_src/` the page: tabs `#live`, `#history`, `#patterns`, `#paste`, `#sources`. `history.js` and `hmap.js`
  are the History tab. `tic-nav.*` and `tic-time.*` are copies from the hub and `doctrine/kit/` from the doctrine
  kit: fix those at their source and copy them in again.

## History
- **Sources, joined into one list** (`data/launches.json`): Launch's charted notices (a hand-built Google My Maps
  map of closure areas, NOTAM texts, flight paths and sites, 2022 onward, imported from an export), GCAT's orbital
  launches since 2023, Launch Library 2's schedule, and NotamForChina (Chinese launches 2012-2026 and their
  notices). A record's `sources` holds `chart`, `gcat`, `ll2`, `nfc`; `chart` lists the charted events joined into
  it, `chart_time` keeps the time in the charted name, `chart_labels` its other names.
- **Joins:** a charted event and a GCAT launch within 3 h and 200 NM or the same country (pass 1), or within 72 h,
  200 NM and the same vehicle or programme (pass 2); a charted event holding a NOTAM that NotamForChina lists for a
  GCAT launch (pass 3). A joined record takes GCAT's launch time.
- **Flight paths:** a charted path is drawn as charted (a great circle per leg); otherwise it is estimated from the
  bearing to the closure areas, the payload's inclination, the orbit class's, or the site's most-used corridor.
  Each record says its basis.
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
- **One notice per NOTAM:** where the charted notices and NotamForChina hold the same NOTAM (number and a shared
  FIR), the charted text is shown and NotamForChina's ring is a check under it.
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
- Publicly available information only. Standard library only; tests offline. Times stored UTC.
- Never `git add -A`; name the files. No key files. Never commit `history/source/`, `CLAUDE.local.md` or `.claude/`.
