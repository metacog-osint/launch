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
4. **Matching** (`launch/live.py`), three named levels: time (Orbit's rule: NET in a window of 4 h or less, or up
   to 1 h before it opens); time and place (also inside an azimuth band the pad's history has, or within 1,500
   NM where the pad has no history); grouped (GCAT has since dated a launch from that site inside the window).
   None says an area is for a launch.
5. **Live lanes:** FAA space-operations TFRs; Orbit's published snapshot. FAA NMS waits for access. The
   NASASpaceflight forum is linked, not collected.
6. **Not for navigation.**
