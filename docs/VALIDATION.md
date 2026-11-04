# Verification of v0.11.0

Updated and checked on 2026-11-05 in a Linux development sandbox using
Python 3.14.8 and 3.11.18, Qt/PySide6 6.11.2, evdev 1.9.3, and python-xlib 0.33.

## Completed

- **334 tests collected**. Locally, **333 pass and one is skipped** because Weston
  is not installed. CI installs Weston in a separate native-display job. Coverage includes offscreen Qt workflows and five live X11
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
  viewport virtualization, and read-only behavior during replay.
- X11 integration verifies keyboard/modifier state, mouse coordinates, wheel/button
  messages, unchanged focus, two simultaneous Shift keys, changed window identity,
  and background compatibility preflight.
- `ruff check` and `ruff format --check` pass. Source distribution and wheel build
  successfully with `python -m build`. Runtime dependencies have tested constraints.
- The actual Qt window was rendered and visually inspected at 1240×800 and 1000×680.
  Screenshots include [workflow](editor.png), [events](events.png), [run settings](run-settings.png),
  [guided setup](setup.png) and [welcome](welcome.png). The current screenshots are rendered from synthetic Test mode workflows. Record/run/pause/stop
  remain in a fixed transport bar, with Pause/Stop hidden while idle. Properties
  are opened on demand. The previous sidebar and duplicate navigation are removed.
- A synthetic 20,000-event recording projects to 10,001 actions on one continuous
  canvas. Tests scroll to the middle and smoothly follow the end while graphics
  remain limited to the visible area and every original event is retained.
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
selections, whole-workflow select/delete/undo, box selection, group moves and all three
layouts. Loop-start tests check reset order every loop, coordinate-space mismatch,
failed preflight cleanup, cancellation, repeated timing sampling and speed scaling.
X11/Hyprland desktop providers are mocked: bounds, scale, transform, negative monitor
positions and position verification are covered without moving the user's cursor.
The live X11 test checks background positioning on an unmapped controlled receiver.
Test mode and cancelled/late position-picking callbacks are checked separately.

New actual Qt screenshots show [the controls](editor.png), [Start settings](start-controls.png)
and [countdown](countdown.png). Documentation captures use the running Qt app with synthetic workflows.

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
watchdogs, and packaged installers are roadmap work, not verified v0.7 features.

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


## v0.7 checks and limits

- Regression tests cover cumulative scheduling without accumulated wakeup/send
  cost, preserved late key/button holds and release intervals, exact recording
  arming, chronological drained-device batches (including multiple 64-event reads), filename tab labels and consistent
  Open/Save As directories across restart.
- Window-picker tests search app/title, select native windows explicitly for
  desktop playback, retain closed selections and reject focus loss before input.
  The KDE observer is tested over a private D-Bus daemon, including script load,
  live focus/window updates and normal unload. No real input is emitted by these tests.
- A read-only check against the actual KDE session successfully enumerated 11
  windows and an active identity, then unloaded the temporary script. No focus,
  game state, desktop preferences or persistent KWin settings were changed.
- Drag tests verify previews leave events unchanged, cancellation restores positions
  and selection, and dropping remains undoable. Camera tests verify intermediate
  positions and disabling follow. UI screenshots were checked at 1240×800 and
  1000×680; picker screenshots use illustrative titles, not private user windows.
- A local input-free benchmark of 1,000 reports at 1 ms requested 1 s: before the
  scheduling fix it took 1.0533 s; after it took 1.000066 s. These are single local
  measurements, not a real-time guarantee or proof of hardware/game acceptance.
- Actual keyboard/mouse acceptance in the user's game remains unverified: this
  sandbox has no physical input/uinput devices. Relative counts do not guarantee
  pixel-identical paths or camera movement, and existing recordings are not rewritten.


## v0.8 verification

- Added regression coverage for version-3 notes/groups, invalid metadata, zero-delay
  visual-only notes, input-only replay counts, atomic group edit/remove/Undo,
  cross-document clipboard identities, note editing and actual group-header clicks.
- Responsive-layout tests resize a 348-action grid from 1000 to 3440 pixels, toggle
  the inspector and change zoom without changing events. Camera tests verify
  continuous velocity when retargeted, intermediate positions and the follow toggle.
- Library tests discover valid workflow JSON outside the internal folder, exclude
  unrelated configuration JSON, search filename/title and persist added folders.
  A read-only scan also found all three existing user workflows beside the launcher.
- File tests rename without overwriting another file or saving unrelated edits.
  Save-dialog tests exercise save/discard/cancel and cancelled-save preservation.
  Live-preview tests verify captured events appear before committing and Discard
  leaves the prior workflow intact.
- Window activation is tested through the private D-Bus fixture, including temporary
  script load/run/unload and observed focus updates. The generated JavaScript is
  evaluated against an owned workspace fixture with quoted identities; wrong PIDs
  cannot select another window. GUI replay verifies activation precedes input.
  These tests never activate a real user window or inject real desktop input.
- Actual Qt screenshots were inspected at 1240×800 and 3440×1440; the wide grid used
  12 columns. A local offscreen camera check produced 261 updates over roughly two
  seconds: median interval 7.89 ms, 95th percentile 8.64 ms, and 4,464 scene pixels
  travelled. This measures the local Qt camera, not a guaranteed physical display
  refresh rate or real-game input acceptance.
- Foreground activation still uses the normal desktop pointer/keyboard. Independent
  background input remains X11 best effort or a separate game session. Physical
  compositor/game acceptance is still a manual check.

## v0.9 verification

- Both Python 3.11 and 3.14 passed the complete 259-test suite, including normal
  interpreter exit. Twenty new regressions cover colored/animated connectors,
  stopped/paused/loop-gap states, older held keys, target overshoot, last-run banner
  resize, responsive reflow while following, adjacent + tab creation, one group
  rectangle across rows, actual background click versus box-drag gestures, note
  drafts across edits/save/copy/tab changes, last-run retention and legacy migration.
  Wrapped group headings stay distinct/clickable, and pending notes participate in
  toolbar Undo/Redo and Duplicate.
- The Group inspector was checked at 1000×680 with a usable scrolling text editor,
  and the workflow at 1440×900 and 3440×1440. The wide canvas uses 12 columns.
  Screenshots: [group notes](group-notes.png), [playback arrows](flow-playback.png),
  [workspace](editor.png) and [wide grid](wide-workflow.png).
- A shutdown SIGSEGV was reproduced with a standalone Python-created QMimeData on
  Qt's clipboard. GDB traced destruction through Shiboken after Python shutdown.
  Copy now uses Qt-owned text data with the same validated JSON envelope; the child
  process regression copies through the real editor and exits without clearing
  the clipboard. Older custom-MIME selections remain readable.
- Metadata edits retain raw events, multi-selection, viewport and completed-run
  markers. Invalid group drafts preserve their text and active tab. Legacy note
  migration preserves input timing/order and leaves source files unchanged until
  explicitly saved. Version 4 carries group notes and never silently downgrades.
- Lint/format checks and source/wheel builds pass. Distribution contents include
  the new modules and exclude personal workflow JSON files. No physical input,
  host-window activation or game launch was needed for this UI update.

## v0.9.1 note editing regression

Reproduced autosave moving the description cursor from position 1205 to 0 and
clearing a text selection during Save. The inspector now leaves unchanged fields
intact when refreshing the same group. Switching groups and applying changed
model values still updates their fields normally.

Two Qt regressions type into an 80-line note, wait for the actual debounce timer,
continue typing after saving, and verify cursor/scroll/focus/native undo state.
Explicit workflow Save and a model refresh also preserve description and name
selections while persisting the complete text. Both tests failed before the fix.
GitHub's font/layout combination also exposed a 10-pixel scroll change. Status
messages now reserve two lines so initial/Saving/Saved feedback cannot resize the
editor during typing. Refreshing the same group retains its current save status
instead of temporarily restoring the longer initial hint. The regression also
verifies the text viewport keeps its size.

## v0.10 creation, themes and public-preview checks

- Both Python 3.11 and 3.14 pass 298 tests, including 37 new audit/theme cases.
  Each of the eleven palettes renders the native Qt window and meets 4.5:1 text
  contrast for normal background/panel text and primary-button labels. Custom
  light, gray, dark and warm backgrounds verify automatic text/subtext contrast.
- Theme tests preserve input data, groups, notes, selection, editing cursor and
  Undo history across live changes and restore preferences on restart. Daylight
  checks cover canvas colors, readable SVG assets/group labels and icon colors.
  Active playback locks appearance controls. Gallery label height is regressed.
- Creation/editing checks cover direct signed movement/scroll input, subset-group
  independence and Undo, custom imported group colors, duplicate order and copied
  group identities/notes, distinct new-document names, native text Ctrl+Z, protected
  invalid drafts, truthful blocked file/example handling and retained run marks
  after failed playback validation. Clearing an imported description keeps Undo.
  Quit permits Discard/Keep editing for an invalid draft instead of trapping the user.
- Actual native screenshots were inspected at 1440×920 and 1000×680, including
  [Automater](editor.png), [the gallery](themes.png), [Daylight](daylight.png) and the
  group panel. The pass found compressed gallery labels and double-mapped icons;
  these were fixed before release. No generated mockups are used.
- The README now describes current flows; earlier feature history is archived.
  Local documentation links resolve. The wheel includes the new modules and light
  assets; the source archive also includes contribution/security/install guides,
  launcher, lock file and two synthetic examples. Runtime doctor works without
  a GUI. Git history contains only the two synthetic example JSON files; personal
  root recordings are ignored and excluded from distributions.
- GitHub action release tags were verified through the upstream repositories and
  updated to checkout/setup-python v7. The full CI matrix is run before completion.
  The repository remains private; publication is an owner decision documented in
  [RELEASE](RELEASE.md). Physical device/compositor/game/GPU checks listed there
  remain manual and are not established by these tests.

## v0.11 Linux compatibility verification

- Session tests cover headless operation, X11, Wayland with Xwayland, stale display
  variables, explicit Qt platform overrides and Hyprland helper selection. Desktop
  identity also falls back to XDG_SESSION_DESKTOP=plasma. An Xwayland connection
  never changes a Wayland session into a native X11 pointer destination.
- Runtime tests check the exact pinned Qt wheel ABI floors (x86_64 glibc 2.34 and
  aarch64 glibc 2.39), musl rejection for standard fresh installs, custom installed
  Qt builds, automatic supported-Python selection, explicit interpreter overrides
  and XDG_CONFIG_HOME defaults. Official wheel filenames were checked on PyPI.
- Private D-Bus tests verify successful read-only capability probes, missing
  RemoteDesktop/ScreenCast interfaces, absent pointer capability, rejection before
  any permission session, and --doctor --check-portal emitting only GetAll calls.
  Existing approval, denial, cancellation, revocation and loop-reset tests remain.
  A read-only probe of the actual KDE session also reported RemoteDesktop v2 and
  ScreenCast v5 with pointer/monitor capability; no permission session was opened.
- Native XCB GUI startup runs against a new private Xvfb server and passes locally.
  Native Wayland uses a private headless Weston/Pixman server in CI. The child GUI
  substitutes an empty physical-device list and never emits input. Rendering/boot
  checks do not certify real input on KDE, GNOME, wlroots or games.
- CI expands the full Python 3.11/3.14 suite to Ubuntu 22.04 and 24.04. Debian 12
  and Fedora 44 containers install the app and run core/GUI smoke checks; container
  tags were verified. Physical desktop, ARM and GPU coverage remain manual.
  The first minimal-image run exposed missing Debian GLib and native XCB runtime
  dependencies; the installation lists now include them explicitly. Native GUI
  failures retain Qt plugin-loader diagnostics instead of only its generic error.
- Compatibility reporting and the optional portal probe leave workflow data and
  permissions unchanged. Source/wheel contents, launcher doctor, lint/format and
  documentation links are checked before completion. See [the feature matrix](COMPATIBILITY.md).
  Native Qt views at 1000×680 were inspected; Devices now scrolls so the added
  compatibility action does not compress its capture instructions.

## v0.12 Automater rename and installation

- Python 3.11 (installed wheel) and Python 3.14 (editable checkout) each pass
  343 tests locally; the native Wayland test is skipped locally without Weston.
  Lint/format, shell syntax, documentation links, packaged contents and doctor pass.
- Product UI, CLI/module/package, repository metadata/URLs, desktop identity, default
  theme, integration identifiers, docs and screenshots use Automater. The earlier
  identifiers remain only where needed to migrate settings or exclude old virtual
  input devices. Root recordings are untouched and ignored by Git.
- Migration tests copy synthetic settings, saved workflows and recovery files into
  the new config root; preserve original bytes; relocate library paths; translate
  the previous default theme; and keep already existing Automater settings. Failed
  copies leave no partial destination. Config-path discovery and doctor do not
  perform migration; ordinary GUI startup prepares it.
- Actual desktop entries pass desktop-file-validate and launch a synthetic receiver
  through GIO, including paths containing spaces, apostrophes, equals, percent,
  backslashes, quotes, dollar signs and backticks. No physical input is sent.
  Installer tests reject runtime failures before registering a menu entry; shortcut
  removal preserves settings and unrelated entries. A real --no-system-packages
  install was also checked with a temporary XDG_DATA_HOME.
- All current screenshots come from the actual Qt UI with a temporary config, empty
  device list, synthetic windows and input-free Test mode. The screenshot script is
  included in the source archive. Old-branded animation/drag captures were removed.
- Source and wheel builds contain the Automater package/command and only synthetic
  example JSON. The expanded distro/native-display CI matrix also checks desktop
  registration; administrator package installation is not executed on the host.
