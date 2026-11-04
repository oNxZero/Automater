# Verification of v0.2

Implemented and checked on 2026-11-04 in a Linux development sandbox using
Python 3.14.8, Qt/PySide6 6.12.0, evdev 1.9.3, and python-xlib 0.33.

## Completed

- **70 automated tests passed**, including offscreen Qt workflows and four live X11
  integration tests against an unmapped, controlled receiver. No user window was
  targeted and focus was never changed by the tests.
- Replay tests cover long-delay cancellation, held-key release, partial-send failure,
  pause/resume, stop while paused, target loss, finite/unbounded repeats, disabled
  steps, speed settings, countdown cancellation and concurrent-start rejection.
- Capture tests cover inactive capture, reserved shortcut exclusion, physical repeat
  suppression, filtering, shared logical holds across devices, event timestamp
  spacing, monitor-to-recorder delivery, virtual-device exclusion and SYN_DROPPED.
- A mocked uinput device verifies exact key/button/relative-axis event translation,
  report synchronization and close behavior. It does not prove hardware acceptance.
- Persistence tests cover private file permissions, atomic replacement failure,
  round trips, file-size limits, malformed fields, invalid timing/types and versions.
- Qt tests cover editing, validation feedback, undo/redo, test replay, locked editing
  during playback, autosave, saving/library refresh, input permission failures,
  cancelled countdown, explicit background targets, unsaved-change cancellation,
  recording handoff and recovery.
- Twelve workflow tests cover lossless card grouping, overlapping holds, inspector
  edits to both halves of a key hold, action insertion/reordering/undo, duplicate/
  disable/delete, grouped mouse timing with original coordinates retained, empty
  state and navigation, canvas/event selection sync, actual pointer drag reorder,
  bounded page rendering, and read-only behavior during replay.
- X11 integration verifies keyboard/modifier state, mouse coordinates, wheel/button
  messages, unchanged focus, two simultaneous Shift keys, changed window identity,
  and background compatibility preflight.
- `ruff check` and `ruff format --check` pass. Source distribution and wheel build
  successfully with `python -m build`. Runtime dependencies have tested constraints.
- The actual Qt window was rendered and visually inspected at 1480×900 and 1100×740.
  Screenshots include [workflow](editor.png), [events](events.png), [run settings](run-settings.png),
  [guided setup](setup.png) and [welcome](welcome.png). An actual Test mode recording
  produced [the animated walkthrough](workflow-demo.gif). Record/run/pause/stop
  remain in a fixed transport bar. Test mode is near the top of Run settings.
- A 100,000-event mouse recording loaded in approximately 0.31 s and edited one
  event in 0.22 s on this sandbox. It projected to one path card without deleting
  samples. Graphics scenes are bounded to 60 cards per page. These measurements
  are observations, not latency guarantees.
- `./start.sh --doctor` works and accurately reports the sandbox's missing device
  nodes instead of claiming recording/replay access.
- GitHub Actions is configured for Python 3.11 and 3.14 on Ubuntu, using Xvfb for
  X11 tests and Qt offscreen rendering. Check the repository's Actions tab for
  remote run results; the local results above are independent of CI availability.

## Requires a real desktop before calling this game-tested

This sandbox exposes an X server but no `/dev/input` or `/dev/uinput`. The following
manual checks remain unverified:

1. On Wayland and X11, grant input permissions, select the intended physical devices,
   record a held key, simultaneous modifiers, clicks, motion and horizontal/vertical
   scrolling; compare timing to the original actions.
2. Replay into a harmless local test app, then the intended game. Confirm the virtual
   device is recognized, the first event is received after countdown, and relative
   motion behaves as expected at the chosen sensitivity/acceleration settings.
3. While a key is held, exercise F12, pause/resume, repeated playback and normal close.
   Confirm the destination observes releases. Test disconnect/reconnect of a device.
4. In background mode, select each actual target application and verify acceptance
   of events while another app is focused. Test target closure, changed window
   identity, modifiers, buttons and virtual-cursor movement. Games can ignore this
   mode; an X11 receiver test cannot establish game compatibility.
5. Test high polling-rate mice and extended recordings near the 200,000-step limit;
   validate memory usage and timing on the user's actual machine.

Native Wayland background routing, gamepad/absolute input, Windows/macOS, process
watchdogs, and packaged installers are roadmap work, not verified v0.2 features.
