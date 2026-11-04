# Bug and usability audit — v0.6

Reviewed selection/editing, recording, pointer setup, playback feedback, asynchronous
cancellation and the Qt layout on 2026-11-04. This is a bounded audit with regression
evidence, not a claim that every bug has been found.

## Fixed

| Problem | Fix and evidence |
| --- | --- |
| Test mode made playback animate while emitting nothing | Confirmed enabled in the user's settings. Added a prominent explanation and Use real inputs button. |
| KDE Wayland had no exact reset provider | Added explicit RemoteDesktop/ScreenCast permission setup, approved-monitor bounds and positioning. Private real-D-Bus tests verify the protocol and replay integration; physical acceptance remains a manual check. |
| Matching selected actions could not be edited together | Added shared properties, Mixed indicators and atomic, undoable bulk changes. |
| Bulk editing could copy unrelated values from the first action | Only touched fields apply; tests retain different keys, timing ranges and samples. |
| Re-recording required replacing everything | Replace a selected contiguous span, preserve prefix/suffix, and allow discard/undo. |
| Record replaced work by default | Append is the default, including migration of old preferences. Whole-workflow replacement requires an explicit choice. |
| Empty recording changed existing work | Empty or discarded captures preserve the original actions. |
| Box selection required an obscure modifier | Left-drag selects; middle-drag pans, with Qt pointer-event tests. |
| Clearing Events selection left stale properties | Clear cards/properties with the table; prevent partial raw rows from expanding into a bulk edit. |
| Properties clipped in a small window | Scroll the complete inspector contents, keep Apply visible, remove duplicate controls and hide unused ranges. Visually checked at 1240×800 and 1000×680. |
| Opening properties clipped the selected card at the canvas edge | Reveal the selection after panel/window resizing settles. Defer scrolling until mouse release to preserve dragging. Eight regression cases cover all layouts, both window widths, resizing and an active pointer gesture; zoom and events stay unchanged. |
| Random timing estimates showed a single total minimum | Show a total range. |
| Recorded cleanup released modifiers too early | Release other held keys before modifiers. |
| F-keys did nothing locally without evdev access | Local fallback when monitoring is unavailable; no auto-repeat or duplicate global delivery. |
| Expired overlays could access deleted Qt windows | Idempotent cleanup and cancellation guards for delayed callbacks. |
| Portal changes could deliver stale UI callbacks | Ignore superseded connections; handle revocation, bus disconnect and cancellation. |
| Grid lines had sharp corners and highlights changed abruptly | Rounded connectors and short hover/selection/guide transitions; rendering regression coverage. |

## Remaining desktop checks and product limitations

- This environment has no physical input/uinput nodes. Recording, injection into
  real games, device reconnection and high-rate timing need the [manual checks](VALIDATION.md).
- Portal tests use a fake portal on a real private D-Bus daemon. KDE/GNOME versions,
  permissions, monitor scaling/hotplug and game pointer capture need actual desktop
  testing. A portal acknowledgment cannot prove a game accepted a move.
- Relative movement depends on acceleration, sensitivity and scaling. Guides are
  approximate and do not predict a game's camera. Verify overlays with fractional
  scaling and fullscreen games.
- X11 background messages can be ignored by games; native Wayland background
  routing is unavailable. Pointer permission does not change these capabilities.
- Global hotkeys require a selected readable keyboard. Local fallback works when
  Studio is focused. Re-recording nonadjacent spans is rejected to keep one clear
  replacement position.
- Configurable hotkeys, named groups, run presets and a real-device compatibility
  report remain useful follow-ups before broader Linux/game reliability claims.


## v0.6 findings and changes

- Existing-window routing cannot guarantee a game accepts synthetic X11 messages,
  and it cannot route to a native Wayland client. Added a separate-display session
  option with private XTEST input; it requires launching the app there and compatible
  Vulkan/GPU support. Sober itself still needs real-game validation.
- Countdown display restarted from the time a GUI signal arrived. It now uses the
  worker's actual deadline, including preparation/registration timing.
- Upcoming input was highlighted while waiting for its delay. Feedback now separates
  delay, Timer, held keys, positioning, settle, gap and actual completed events.
- Finish/Stop cleared the only evidence of where a run ended. Last-loop completed,
  last, interrupted and failed markers now persist per document with diagnostics.
- Mouse X/Y axes from a physical report became separate replay reports. They now
  stay together with report spacing and counts retained; different source devices
  never merge. This improves fidelity but does not establish exact game-camera paths.
- Added independent document undo/view/run settings and recovery files; new/open no
  longer discards work, and saving cannot collide with another open file.
- A host-pointer comparison in an X11 test could fail when the user physically moved
  the mouse. It now forbids pointer-warp/XTEST APIs in background routing; separate
  input tests use a test-owned Xvfb server.


## v0.7 findings and changes

| Finding | Fix / evidence |
| --- | --- |
| Tiny wakeup delays accumulated across every motion report | Preserve cumulative deadlines. A local 1,000-report dry run requesting 1 s improved from 1.0533 s to 1.000066 s. This is scheduler evidence, not a real-game acceptance guarantee. |
| Catching up after a late press could shorten its hold or the next release interval | Protect each key/button transition interval from actual dispatch completion; deterministic regressions cover late keyboard and mouse sends. |
| Recording waited for a 100 ms UI tick after the countdown | Arm capture immediately against the monotonic deadline; ignore earlier input and retain the first post-deadline press before the UI tick. |
| Keyboard batches could precede older mouse events | Drain pending evdev batches before merging events by kernel timestamp; preserve per-device report order even when more than 64 events are queued. |
| App selection looked like choosing a game executable | Search open windows directly. Native KDE Wayland windows are discovered read-only; unsupported background delivery is labelled and offers desktop playback explicitly. |
| A closed desktop target could become unrestricted playback after refreshing | Retain the unavailable selection and reject playback until the user chooses a valid window or explicitly clears it. |
| Action pages interrupted long workflows | Replace pages with global positions and viewport virtualization; a 20,000-event regression scrolls/follows a 10,001-action scene without losing events. |
| Dragging gave no origin or insertion preview | Original-position markers, proposed-order ghosts and neighbours, edge scrolling, Escape cancellation and one-drop Undo. |
| Playback camera jumped between cards | Cancellable easing animation, clamped endpoints, and a Follow playback toggle. Replay scheduling remains in its worker. |
| Tabs sat above the title and close icons crossed the edge | Tabs now sit above the editor; native close-button geometry reserves an inset. |
| Saved tabs used the internal Untitled title and file choosers disagreed | Tab labels use filename stems. Open/Save As share an existing directory, remember it and resolve relative saves within it; dialog regressions cover restart and new tabs. |

Physical-game accuracy and native Wayland discovery outside KDE still require
platform-specific work. No claim is made that every real game accepts every input.
