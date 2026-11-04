# Bug and usability audit — v0.5

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
