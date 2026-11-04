# Verification of v0.6

Implemented and checked on 2026-11-04 in a Linux development sandbox using
Python 3.14.8 and 3.11.18, Qt/PySide6 6.11.2, evdev 1.9.3, and python-xlib 0.33.

## Completed

- **194 automated tests passed**, including offscreen Qt workflows and five live X11
  integration tests against an unmapped, controlled receiver. No user window was
  targeted and focus was never changed by the tests.
- Reproduced a Qt/PySide6 6.12.0 reference-count crash during repeated painting on
  Python 3.11. Constrained runtime to 6.11.2–6.11.x, pinned 6.11.2 in the lock file,
  and verified the full suite on 3.11 and 3.14. The launcher checks pinned installed
  versions and refreshes changed dependencies before starting the app.
  A separate process draws 20,000 pixmaps and must exit cleanly as a regression check.
- Replay tests cover long-delay cancellation, held-key release, partial-send failure,
  pause/resume, stop while paused, target loss, finite/unbounded repeats, disabled
  steps, speed settings, countdown cancellation and concurrent-start rejection.
- Capture tests cover inactive capture, reserved shortcut exclusion, physical repeat
  suppression, filtering, shared logical holds across devices, event timestamp
  spacing, monitor-to-recorder delivery, virtual-device exclusion and SYN_DROPPED.
- A mocked uinput device verifies exact key/button/relative-axis event translation,
  report synchronization and close behavior. It does not prove hardware acceptance.
- Discovery tests now use the actual installed `evdev.InputDevice` class with supplied
  metadata and real file descriptors, exercising its real capabilities/close methods,
  slots, and lack of a context manager. This directly regresses the user-reported bug.
- Real evdev `read()` is exercised on pipe-fed Linux input_event packets through
  the monitor and recorder, for both realtime fallback and monotonic clock paths.
  These are simulated kernel packets, not physical hardware or a compositor test.
- Device tests cover permission errors, removed nodes, partial-open cleanup, virtual/
  unrelated-device filtering, separate wheel interfaces, stable identity under node renumbering, and explicit
  absolute-motion limitations. GUI tests apply selections, repair permissions,
  ignore stale listeners, and verify that failed startup never claims readiness.
- Preferences tests verify private atomic storage, validation and malformed-data
  handling. GUI tests restore run/capture settings and append recordings with undo.
  Engine tests verify cancellation before virtual-device registration and modifier
  ordering during pause/resume.
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
- The actual Qt window was rendered and visually inspected at 1240×800 and 1000×680.
  Screenshots include [workflow](editor.png), [events](events.png), [run settings](run-settings.png),
  [guided setup](setup.png) and [welcome](welcome.png). An actual Test mode recording
  produced [the animated walkthrough](workflow-demo.gif). Record/run/pause/stop
  remain in a fixed transport bar, with Pause/Stop hidden while idle. Properties
  are opened on demand. The previous sidebar and duplicate navigation are removed.
- A synthetic 10,130-event recording is preserved by the workflow tests while
  graphics scenes remain bounded to 60 cards per page.
- `./start.sh --doctor` works and accurately reports the sandbox's missing device
  nodes instead of claiming recording/replay access.
- GitHub Actions is configured for Python 3.11 and 3.14 on Ubuntu, using Xvfb for
  X11 tests and Qt offscreen rendering. Check the repository's Actions tab for
  remote run results; the local results above are independent of CI availability.

## v0.5 regression checks

Inspector visibility tests reproduce cards being clipped when properties open in
Horizontal, Vertical and Grid layouts at 1000 and 1240 pixel window widths. The
fix reveals selected cards after layout changes without altering zoom or events,
waits for mouse release during gestures, and handles resizing an open inspector.

Batch editing checks partial field updates, differing keys/durations/ranges, atomic
validation and single-step undo. Capture checks default append, legacy preference
migration, confirmed replacement, empty capture, selected re-record/discard/undo and
modifier release order. Qt checks unmodified box selection, middle-drag, smooth
highlight transitions, curved grid paths, point picking/cancellation, click-through
overlay flags, safe overlay cleanup and Test mode visibility/local F-key fallback.

Five portal tests communicate over a real private D-Bus daemon to a fake portal,
verifying request/response serialization, permission denial/revocation, cancellation,
coordinate bounds/scaling and the window-to-replay integration across two loop resets.
No real portal permission prompt is opened and no actual cursor movement is emitted.
The synthetic portal cannot establish physical compositor or game compatibility.

## Requires a real desktop before calling this game-tested

The v0.4 additions also verify Press/Release grouping, extended keys, random ranges,
v1/v2 persistence, clipboard validation, native editing shortcuts, precise Events
selections, cross-page select/delete/undo, box selection, group moves and all three
layouts. Loop-start tests check reset order every loop, coordinate-space mismatch,
failed preflight cleanup, cancellation, repeated timing sampling and speed scaling.
X11/Hyprland desktop providers are mocked: bounds, scale, transform, negative monitor
positions and position verification are covered without moving the user's cursor.
The live X11 test checks background positioning on an unmapped controlled receiver.
Test mode and cancelled/late position-picking callbacks are checked separately.

New actual Qt screenshots show [the controls](editor.png), [Start settings](start-controls.png)
and [countdown](countdown.png). The Test mode GIF uses frames from the running app.

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
6. On X11, Hyprland and an approved KDE portal session, pick a desktop point and run at least two loops. Check
   monitor scaling, pointer capture, settle delay and interruption. Verify exact
   background coordinates separately in the intended X11 application.

Native Wayland background routing, gamepad/absolute input, Windows/macOS, process
watchdogs, and packaged installers are roadmap work, not verified v0.6 features.

7. On KDE and GNOME portal backends, approve the intended monitors, deny/cancel,
   revoke permission during a loop, change monitor layout/scale, reconnect, and
   verify that reset really reaches the point. Test overlay positioning and
   click-through behavior, especially with fractional scaling and fullscreen games.


## v0.6 checks and specific limits

Twenty-six additional tests cover document switching/undo, close/cancel, duplicate
file activation, per-tab recovery, save collisions and playback locks; authoritative
countdown deadlines, waiting/held/timer phases, retained failure/completion markers,
recorded XY reports, source separation and measured slow-destination lateness.

Four input integration cases start a separate Xvfb server on an automatically chosen
display. They run the actual private RPC/XTEST service, checking real key/button/
motion events, pointer position, client coordinates, identity, authentication and
held-key cleanup. No XTEST input is sent to the host server. Launcher tests check
argument boundaries, private directory permissions, explicit startup, Sober's
existing-instance rejection and absence of desktop fallback. GUI routing tests
ensure existing host-window targets do not carry into separate-session mode.

Gamescope's actual headless launch was attempted with a harmless test receiver.
It failed before starting a game because this environment has no accessible Vulkan
physical device. The Sober/GPU launch path and actual game input acceptance remain
unverified. No existing Sober process was closed or relaunched.

Actual Qt screenshots show workflow tabs, the session dialog and stopped-run
markers at 1240×800; 1000×680 was also visually checked. Local Xvfb was extracted
into /tmp for testing only; no system packages or input permissions were changed.
