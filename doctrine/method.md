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
4. **Matching** (`launch/live.py`), three named levels: time (Orbit's rule, widened from 4 h on 22 Nov 2026: NET in
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
   **Live paths** (`catalog.live_paths()`, 21 Nov 2026): a scheduled launch's estimated path runs through the matched
   areas within 2,500 NM of its pad, by the same rule as History's paths. A time-only match counts only within 15
   degrees of the launch's expected bearing, and a NET known only to the day ties nothing. A launch with no area on
   its ascent has no line on the Live map.
5. **Live lanes:** FAA space-operations TFRs; Orbit's published snapshot; NGA warnings and FAA NMS NOTAMs through
   Cordon. The
   NASASpaceflight forum is linked, not collected.
   **Scheduled launches** (19 Nov 2026, from Orbit): one record per expected launch from one or more sources (Launch
   Library 2 first), with Launch's own id; each kind of evidence is named ("listed" so far), none is a forecast.
   Headlines are links only. The LL2 ledger is verified and extended each run; its launches GCAT has not listed are
   provisional until a GCAT launch joins them.
6. **Not for navigation.**

## Feed contract revision 2.1 (23 Nov 2026)
Every feed item states `subject_id` and `last_change`, and `event_start` wherever the notice gives a time. Ids do not
change; `subject_id` is the id with any space replaced by a hyphen, because the contract allows none.

A TFR's event time runs from its first window's start to its last window's end, or is its issue time when it lists no
window. Its `last_change` is `new` at the FAA's issue time. A TFR issued within 72 hours is tier anomaly, and its
`signal` is the hours since issue. A coincidence carries the closure area's window, and its `last_change` is `none`,
because a coincidence has no source date and Launch keeps no log of its feed items.
