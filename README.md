# Launch

The Intelligence Company's launch-closure layer: the airspace and sea areas closed for launches and reentries (FAA
temporary flight restrictions and NOTAMs, navigational warnings), which scheduled launches coincide with each area,
a launch history since 2012, and each pad's closure patterns. Observations only: a match says an area and a launch
line up in time, or in time and place, never that the area is for that launch. Live at
https://launch.theintelligence.company.

Sources: FAA temporary flight restrictions (tfr.faa.gov) and the FAA NOTAM Management Service (US Government works;
not authoritative for non-US NOTAMs); NGA navigational warnings, read through Cordon (US public domain); GCAT (data
from J. McDowell, planet4589.org/space/gcat, CC BY 4.0) and Launch Library 2 (The Space Devs), read through Orbit;
NotamForChina (Apache 2.0) and Joey0609/notams (MIT), published with their own licence files; Internet Archive copies
of FAA and NGA pages. Every source, with its terms, is in `doctrine/sources.json` and on the page's Sources tab.
Map: MapLibre GL JS (BSD-3), Natural Earth, OpenFreeMap, OpenMapTiles, OpenStreetMap contributors.

## Commands

```bash
python tools/launch.py collect         # live lanes (FAA TFRs, Orbit, Cordon, FAA NMS) -> data/snapshot.json
python tools/launch.py build           # build site/, with the privacy check
python tools/launch.py check           # validate the registers, lint the feed, run the public and privacy checks
python -m unittest discover -s tests   # offline tests
python tools/serve.py                  # site/ on http://127.0.0.1:8771 with the headers in _headers
```

`.github/workflows/update.yml` runs the tests, collect, build and check every hour and on every push to `main`,
then deploys `site/` to Cloudflare Pages.

## Checking a downloaded copy

Each release (`ledger` and `ledger-YYYY-qN`) carries `SHA256SUMS` and `launch-manifest.json`, listing every file in
it with its size and SHA-256. Download `SHA256SUMS` beside the files, then run
`sha256sum -c SHA256SUMS --ignore-missing` (Linux), `shasum -a 256 -c SHA256SUMS --ignore-missing` (macOS), or compare
`Get-FileHash <file> -Algorithm SHA256` (PowerShell).

## Licence

Copyright © 2026 Thomas Brummer, The Intelligence Company. Launch's code is licensed under the GNU Affero General
Public License v3.0 (`LICENSE`). Third-party and shared files keep their own licences, and data keeps its sources'
terms; both are listed in `NOTICE`.

## AI assistance

This repository is built with AI coding assistance (Anthropic's Claude Code). The Intelligence Company is responsible for everything published here.
