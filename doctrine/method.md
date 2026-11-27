# Launch method (`launch-1.0`, 13 Nov 2026)

Launch maps the airspace and sea areas states close for launches, stage drops and reentries, keeps their
history, and says which scheduled launches coincide with them. Observations only.

1. **History** comes from Launch's charted notices (a Google My Maps export of 13 Nov 2026). One name per event groups its
   closure polygons, flight-path lines and points. Each closure polygon is kept as charted and, when its text is
   a NOTAM, checked against what Launch's parser reads from that text (largest vertex distance; "agrees" within
   5 NM). The map's exercise layer is not imported: it holds scenario text, not public notices.
2. **Parser** (`launch/notam.py`): ICAO NOTAM header, Q-line and items A-G; shapes from the E) text (polygons,
   circles) or, only when the text has none, the Q-line circle marked approximate. Unreadable coordinates are
   listed, never guessed. "Relayed" means the text names a state other than the issuing FIR's.
3. **Patterns** (`launch/patterns.py`): per pad, closure azimuths in 5-degree bands with the inclination each
   implies (cos i = cos(lat) sin(az), LA-ASM-1); drop zones used by three or more events within 25 NM; window
   lengths; notices per FIR per year; launch hour by actor. Counted, not predicted.
4. **Matching** (`launch/live.py`; since 25 Nov 2026 the scheduled launches are Launch's own records that Launch
   Library 2 lists, item 5, not Orbit's copy), three named levels: time (Orbit's rule, widened from 4 h on 22 Nov 2026: NET in
   a window of 6 h or less, or up to 1 h before it opens; Ariane 6 VA271's own areas ran 4.9 to 5.7 h); time and place (also within 30 NM of the pad, or inside an azimuth band the pad's
   charted history has; where that history rests on under 10 events, as at most US pads, also on the launch azimuth,
   +-5 degrees, of an inclination GCAT shows flown five or more times from the site, within 1,500 NM, added 24 Nov
   2026 after NG-25's and USSF-380's own areas read time only; within 1,500 NM where the pad has neither; or, for a far area, under the launch's own ground
   track, on the orbit its farthest place-matched area implies, within 150 NM of the area at a time its window allows,
   10 to 110 minutes after NET, over a rotating earth: an upper stage's disposal area, added 24 Nov 2026 after
   NG-25's South Pacific areas read time only; a launch with no place match has no direction and gets none); grouped (GCAT has since dated a launch from that site inside the window).
   None says an area is for a launch.
   **Named** (22 Nov 2026), beside the level: the notice's text has the launch's mission designator (a word of letters
   and digits in LL2's mission name, hyphens ignored, such as NROL-136), which also lets a window of up to 7 days
   match; or the vehicle's name (ARIANE 6 for an Ariane 64) where the place fits too. A match named by its mission is
   kept with the launch and may set its live path like a time-and-place match. Still a coincidence of words.
   **Off the live view** (`nms.off_live()`, 22 Nov 2026): a kept NOTAM whose text says it is an amateur rocketry
   window, no longer in force or an aerodrome notice, or, without space words (space, satellite, orbit, reentry,
   debris, rocket launch), a missile firing, an airdrop or airlift, a military exercise, an explosives demolition or a navaid flight
   inspection, or a stated ceiling under 10,000 ft (24 Nov 2026), or a prohibited area with no launch word, stays in the closure
   ledger, matches no launch, and is hidden on the Live map and list until the viewer turns such notices on. Terse notices ("AIRSPACE CLSD", "ACT") say nothing and stay.
   **Closure with no listing** (`launch/unlisted.py`, 21 Nov 2026): a window of 6 h or less in the next 14 days, within
   450 NM of a site with launch-timing history, with no exactly dated listed launch within 100 NM of that site in any
   of the notice's windows, and no time-and-place match to a listed launch elsewhere. A listing dated only to a day or
   month is named beside it. It says the schedule shows nothing for a closure, not that a launch is coming.
   Each such row is also a record in the upcoming store (25 Nov 2026, Ascent step 1b): source `closure`, id
   `upcoming:closure:<notice key>` (kept while any of its notices stays in a row), NET the window's opening with
   precision "closure window". When a source lists an exactly dated launch within 100 NM of the site inside the
   window, the two records are joined and the one seen first keeps its id. A closure record is never a listing.
   **Live paths** (`catalog.live_paths()`, 21 Nov 2026): a scheduled launch's estimated path runs through the matched
   areas within 2,500 NM of its pad, by the same rule as History's paths. A time-only match counts only within 15
   degrees of the launch's expected bearing, and a NET known only to the day ties nothing. A launch with no area on
   its ascent has no line on the Live map.
5. **Live lanes:** FAA space-operations TFRs; Orbit's published snapshot (GCAT launches only); NGA warnings and FAA NMS NOTAMs through
   Cordon. The
   NASASpaceflight forum is linked, not collected.
   **Scheduled launches** (19 Nov 2026, from Orbit): one record per expected launch from one or more sources (Launch
   Library 2 first), with Launch's own id; each kind of evidence is named ("listed" so far), none is a forecast.
   Headlines are links only. The LL2 ledger is verified and extended each run; its launches GCAT has not listed are
   provisional until a GCAT launch joins them. Orbit's frozen ledger is read only to begin Launch's when none is held.
   **RocketLaunch.Live** (`launch/rll.py`, 26 Nov 2026): the free tier's next five launches, one request a run, a
   second listing source (`rll`, id `upcoming:rll:<its id>`). A RocketLaunch.Live record and a Launch Library 2 record
   are one launch, and are joined (the one seen first keeps its id), when they share a place word, their NETs are
   within 3 h (36 h when either is dated only to a day or coarser) and their vehicles do not differ; with two equally
   near candidates neither joins. Launch Library 2's fields are shown when both hold a record. The free tier gives no
   coordinates or status: a record takes the coordinates of a Launch Library 2 launch at the same place, else none,
   and only Launch Library 2's records go to matching. Every copy says "Data by RocketLaunch.Live".
   **What a launch put in orbit** is Orbit's: Past 7 days and each orbital record in History link to Orbit by GCAT's
   tag (the launch's row on Orbit's launches page, and Orbit's object search, which lists the first 20 pieces with a
   count). Only launches of the kind Orbital get the payloads cell and the links; a missile test or suborbital flight
   puts nothing in orbit.
6. **Not for navigation.**

## Feed contract revision 2.1 (23 Nov 2026)
Every feed item states `subject_id` and `last_change`, and `event_start` wherever the notice gives a time. Ids do not
change; `subject_id` is the id with any space replaced by a hyphen, because the contract allows none.

A TFR's event time runs from its first window's start to its last window's end, or is its issue time when it lists no
window. Its `last_change` is `new` at the FAA's issue time. A TFR issued within 72 hours is tier anomaly, and its
`signal` is the hours since issue. A coincidence carries the closure area's window, and its `last_change` is `none`,
because a coincidence has no source date and Launch keeps no log of its feed items.

**Upcoming launches** (Ascent step 3, 25 Nov 2026): each record in the schedule's live view is a feed item
(LA-PIR-3), id and `subject_id` both `launch:upcoming:<record id>` with spaces as hyphens, so
`launch:upcoming:ll2:<LL2 id>`, `launch:upcoming:rll:<RocketLaunch.Live id>` or
`launch:upcoming:closure:<notice key>`. Each listed item cites the sources that list it. A record keeps its id when another source
joins it, and so does its item. `measures.evidence` says what the record rests on ("listed", "closure with no
listing"). A listed launch's time is LL2's, floored to its stated precision; a closure record's times are the
window's, not a launch time. `last_change` is `new` at the time Launch first read the record.
