# Moonlight Studio product and implementation plan

## Goal and scope

Build a Linux desktop companion to oNxZero/Moonlight for recording, editing, saving,
and replaying keyboard and relative mouse macros. Preserve Moonlight's navy and
periwinkle palette, profiles, physical hotkeys, and evdev/uinput compatibility with
Wayland and X11. This is a separate Python application; the existing clicker and
Minecraft client sources remain untouched.

The first release targets Linux, Python 3.11+, and ordinary keyboards and relative
mice. “All inputs” means keyboard press/release, mouse buttons, relative movement,
and vertical/horizontal wheel events. Touchscreens, absolute pointing devices,
gamepads, IME/text composition, and high resolution wheel metadata are outside v0.1.
Record physical key codes, not typed characters: keyboard layouts and in-game
bindings affect the result. No executable Python is accepted in macro files.

## User journeys

1. Open the app. The setup panel explains device access and current capabilities.
2. Select keyboard/mouse devices and capture categories. Press Record or F6;
   recording starts after a countdown so application controls stay out of the macro.
3. Perform actions. F6 ends recording; F12 stops any active operation. Reserved
   F6/F7/F8/F12 controls never enter the recording. Stopping adds necessary releases.
4. Review delays and key/button/movement/wheel events in an editable table. Insert,
   duplicate, move, disable, delete, and undo/redo steps. Edit name and notes.
5. Choose speed, repeat count, loop gap, and countdown. Test mode highlights steps
   without emitting input. Replay uses an immutable snapshot of the script.
6. Choose Desktop (uinput) for native game input, or Background (X11 experimental)
   and a specific window. Background delivery never steals focus or falls back to
   desktop injection. The user tests the target application's compatibility.
7. Save a named script to the library or open/export a JSON file. Recover unfinished
   work from autosave after a restart. Confirm before discarding unsaved edits.

## Feature inventory for v0.1

| Area | Implementation |
| --- | --- |
| Capture | evdev device chooser; keyboard/buttons/motion filters; relative timing; repeat suppression; dropped-event and disconnect errors |
| Editor | Editable enabled/delay/action/key/X/Y columns; insert key tap/click/wait/move/scroll; duplicate/delete/reorder; undo/redo; name/notes |
| Playback | Dedicated worker; monotonic deadlines; 0.1–10× speed; finite/until-stopped loops; countdown and gap; pause/resume; F12 stop |
| Cleanup | Release held inputs on pause, completion, loop boundaries, error, stop, and normal application close; restore logical holds on resume |
| Routing | Desktop uinput; explicit X11/Xwayland client picker; window identity/liveness checks; virtual client pointer starts at window center |
| Persistence | Versioned JSON; strict field and range checks; size/event limits; atomic private saves; library; timed autosave; recovery |
| UX | Resizable Qt interface; Moonlight palette; onboarding/setup; readable statuses; live step/length statistics; progress highlighting; test mode |
| Delivery | Python package and console command; local launcher; sample macro; README; architecture and compatibility docs; tests and CI |

## Capability boundaries

| Session / destination | Record physical keyboard/mouse | Desktop replay | Unfocused target replay |
| --- | --- | --- | --- |
| Linux X11 | evdev access required | uinput access required | Experimental XSendEvent |
| Linux Wayland, native client | evdev access required | uinput access required | Not supported |
| Linux Wayland, Xwayland client | evdev access required | uinput access required | Experimental XSendEvent |
| Windows / macOS | Future backend | Future backend | Future platform assessment |

Game acceptance of virtual devices and synthetic window messages is application
specific. Relative movement in background mode is a virtual window cursor, not
raw camera motion. Background mode does not guarantee minimized-window, raw-input,
or anti-cheat compatibility. Desktop mode sends to the active desktop; it cannot
keep a native Wayland game receiving input while another app has focus. Selecting
a program means selecting a concrete window, not injecting into a process.

## Architecture

`models.py` owns the versioned schema and validation. `storage.py` handles bounded
imports and atomic writes. `linux_input.py` owns the device monitor, synchronized
recorder, and uinput backend. `x11.py` handles window enumeration and directed
events. `engine.py` is a GUI-independent replay scheduler with backend injection.
`editor.py` owns the Qt table and undo commands. `window.py` owns the application
workflow; worker callbacks cross into Qt through queued signals. `app.py` provides
GUI, demo, and JSON diagnostics entry points.

Threads: Qt owns all widgets; a physical-input monitor waits in select(); replay
runs in one worker and uses a condition variable for cancellation and pausing.
Only one recording/countdown/playback operation may run at once. Recording results
are handed to the UI only after capture stops. No blocking playback on the UI.
No network functionality, account system, telemetry, or automatic uploads of macros.

## Stability acceptance criteria

- Stop interrupts a long wait promptly; no busy-spin loops, even for zero-delay scripts.
- Errors reach the UI; partial presses are tracked before sending, and cleanup
  attempts every held release even if one fails.
- Pause releases held keys, resume restores their logical state, and stop while
  paused does not restore keys.
- Hotkeys work outside the app when physical devices are readable. Virtual output
  devices are excluded to prevent recursive recording and shortcut triggering.
- Input disconnect/SYN_DROPPED stops active work visibly. Restart monitoring from
  Setup after reconnecting. No automatic silent device changes during recording.
- Unknown schema versions, NaN/infinity, wrong types, oversized files, unsupported
  actions/codes, and invalid timing are rejected before replay.
- Atomic saves preserve the previous good file on failure. Autosave never silently
  replaces a user-selected script. Recovery is an explicit choice.
- Tests use injected devices/backends and offscreen Qt. Real hardware testing is a
  separate release gate; passing unit tests does not certify games or compositors.

## Implementation phases

1. **Foundation:** package, schema, bounded storage, sample, docs and test harness.
2. **Engine:** cancellation, pause/resume, repeats, deadlines and cleanup tests.
3. **Linux capture/output:** permissions diagnostics, device selection, filtering,
   hotkeys and disconnect handling; evdev fixtures and virtual-output exclusion.
4. **Visual workspace:** event editor, library, playback configuration, setup,
   undo/redo, unsaved-state protection and recovery.
5. **Background adapter:** concrete window selection, identity checks, keyboard,
   button, wheel and virtual-pointer messages; controlled X11 receiver test.
6. **Verification and delivery:** automated tests/lint/build, GUI walkthrough,
   private GitHub repository and CI; record actual verification in VALIDATION.md.

## Later releases, deliberately separate from v0.1

- Packaged desktop installers and signed release artifacts after hardware validation.
- Configurable hotkeys and theme choices; per-script playback presets.
- Nested loop blocks, reusable submacros, variables, conditionals, visual matching,
  optional OCR and a constrained expression language (no arbitrary imported code).
- Recording motion coalescing/decimation with a preview and quantified error bound;
  original samples remain available. High-resolution wheel, ABS and gamepad capture.
- Compositor-approved portal integration for devices where appropriate; investigate
  compositor-specific routing only with explicit capability detection.
- Windows/macOS adapters with their own permissions, tests and compatibility matrix.
- Isolated replay helper process plus watchdog for stronger fault containment.
  v0.1 uses a worker thread; force kill/power loss cannot run Python cleanup handlers.
- Per-game tested compatibility profiles based on observed behavior. No promise of
  anti-cheat bypass, process cloaking, driver injection, or invisible automation.

## v0.2: visual workspace redesign

The workflow canvas is now the default editing view. It presents the existing
linear sequence as connected cards from left to right, with press/release pairing,
consecutive mouse-path grouping, insertion points, drag reorder, context actions,
zoom/pan, keyboard navigation and live playback highlighting. The raw event model
remains the source of truth. Grouping is presentational and retains original samples.

`workflow.py` owns card projection and the bounded graphics scene; `inspector.py`
edits logical actions through the existing undoable model; `designer.py` builds
the workspace, guided setup, searchable library and run/notes panels. `theme.py`
and `widgets.py` share design tokens, original SVG icons and native controls.
The main UI adopts Moonlight's visual family with a sidebar, spaced cards, a
dedicated property inspector, clearer state indicators and a fixed transport bar.
Large workflows now use one continuous canvas with viewport virtualization (v0.7). Version-1 script compatibility
and input backends are retained. Conditional graphs and nested loops remain future work.

Acceptance checks include edits to both halves of a key hold, preservation of raw
mouse samples during grouped timing edits, atomic action reorder/undo, view-selection
synchronization, insertion, viewport bounds, and read-only operation during playback.

## Technical references

- [Moonlight](https://github.com/oNxZero/Moonlight) — reference behavior and palette.
- [python-evdev tutorial](https://python-evdev.readthedocs.io/en/latest/tutorial.html)
- [Linux uinput](https://docs.kernel.org/input/uinput.html)
- [Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html)
- [Xlib directed events](https://python-xlib.sourceforge.net/doc/html/python-xlib_14.html)
- [Wayland model](https://wayland.freedesktop.org/docs/book/Protocol.html)

## v0.3: simpler UI and Linux reliability

Replace the sidebar and duplicate view controls with one compact navigation row.
Keep properties closed until requested, consolidate file actions, and show pause/
stop/progress only during active work. Device diagnostics belong in Devices;
technical exception detail is available behind an explicit disclosure.

Fix the evdev InputDevice context-manager assumption with explicit finally/close.
Test against the actual installed evdev class, including pipe-fed read events and
its slotted attributes. Identify ordinary keyboards and mouse buttons, filter
unrelated interfaces, and label absolute-motion limitations. Open monitors before
claiming readiness, clean up partial failures, retry nonblocking/interrupted reads,
detect empty reads, use monotonic kernel timestamps when supported, and reject
stale listener callbacks after refresh. Pause restores modifiers before letter keys.
Replay allows a cancellable registration interval for newly created uinput devices.

Useful features without more permanent controls: private persistent input selections
and run/capture preferences, recommended input selection, and optional append
recording with one-step undo. Keep macro format v1 compatible. Preference schemas
are bounded and validated; live window handles are not persisted.

Next priorities remain configurable hotkeys, per-workflow run presets, and named
actions. Conditional blocks and visual matching need their own execution model and
compatibility validation; they should not be added as decorative canvas controls.

## v0.4: input controls, selection and loop starting point

Implemented:

- Searchable Linux keys and mouse buttons, including extended function/media/macro
  keys. Separate Press, Hold, Release, Timer, Click, Move and Scroll actions.
- Fixed or minimum/maximum timing, sampled each event and each loop, plus undoable
  percentage variation for selected actions. Coordinate samples remain unchanged.
- Ctrl/Shift multi-selection, Shift-drag box selection, selection across the whole canvas,
  copy/cut/paste, duplicate, delete, group reorder, enable/disable and hold splitting.
  Keep raw Events selections precise and preserve clipboard timing/group metadata.
- Horizontal, Vertical and Grid layouts with numbered execution order, zoom/fit,
  bounded rendering, selection toolbar, Edit menu and visible shortcut help.
- Saved per-workflow starting point, settle delay and coordinate-space validation.
  Reset before every loop through X11 or Hyprland; X11 background routing resets
  only its virtual cursor. Fail clearly for unsupported native Wayland warps.
- Cancellable position picking and large recording/replay countdown; bounded-rate
  timing feedback, loop/action highlighting and visible transport keybinds.
- Larger consistent vector icons with distinct Press/Release and solid transport
  symbols. Compact properties tabs and scrollable Start/Run controls.
- Backwards-compatible v1 import/export; automatic v2 for advanced metadata.
- Advanced Test mode example, updated screenshots, guide and regression coverage.

Next useful additions: configurable hotkeys, named action groups, saved run presets,
screen-based conditions and additional compositor positioning adapters. These need
real desktop validation before being advertised as supported.


## v0.5: shared properties, safer recording and visible pointer control

Implemented matching-action batch properties with changed-field tracking and atomic
undo; ordinary left-drag selection and middle-drag panning; default append with
legacy migration; empty/discarded capture preservation; selected-span re-recording;
explicit whole-workflow replacement; pointer picking and temporary click-through
guides; prominent Test mode feedback and local F-key fallback; user-authorized
Wayland portal positioning with cancellation/revocation; short highlight/guide
animations and rounded Grid connector corners.

The [audit](AUDIT.md) records verified fixes and remaining manual checks. Native
Wayland background routing, conditional execution and image matching remain future
work; portal pointer control is an optional desktop-positioning adapter.


## v0.6: input isolation, workflow tabs and execution feedback

Implemented a managed Gamescope launcher for Sober/custom executables; private local
input RPC and XTEST limited to the nested display; preflight, window identity,
client-coordinate reset and releases on disconnect; separate session setup dialog,
logs and lifecycle controls. Native Wayland host input is never used as a fallback.

Added workflow documents with independent undo stacks, view/run state and private
recovery files. New/open keeps old documents; close/save checks prevent accidental
loss and file collisions. Capture/playback locks document switching.

Playback now publishes an authoritative clock/phase snapshot. The UI polls current
state, highlights actual timers/holds/completed actions, retains last-loop results
per document and reports scheduler lateness. Mouse X/Y reports are kept together.
Future work includes calibration/image feedback and real Sober/GPU compatibility
validation. The private Xvfb test proves transport behavior, not game acceptance.


## v0.7: fidelity and direct manipulation

Implemented a continuous canvas with global action coordinates, viewport-based
card/connector creation, selection retained offscreen, smooth camera follow and
an explicit follow toggle. Dragging previews the proposed permutation without
mutating events; origin markers, destination ghosts, Escape cancellation and edge
scrolling support long routines. Drop still commits through the existing undo stack.

The window picker searches live titles/app names. KDE's read-only KWin scripting
API supplies native Wayland window identities and activation updates over a private
callback on the session bus. The temporary script is unloaded on normal close.
X11 discovery remains the fallback. Selected desktop windows receive focus checks;
cleanup releases remain possible after focus loss. Existing-window background and
separate-session routing retain distinct capabilities and failure behavior.

Capture is armed against the recording deadline and merges ready device batches
by kernel timestamp. Replay retains cumulative deadlines while protecting actual
key/button transition intervals, including pause restoration. File dialog folders
are consistent and persisted; tab labels come from saved filenames.

- [KDE KWin scripting API](https://develop.kde.org/docs/plasma/kwin/api/)


## v0.8: responsive, documented workflows

Implemented a viewport-responsive grid and a critically damped camera with continuous
velocity across target changes. Grid reflow is deferred during pointer gestures;
virtualization remains independent of total action count. The live recording strip
uses a bounded recorder snapshot and does not mutate the editable workflow.

Library discovery indexes known folders/recent paths on a background thread, coalesces
refresh requests, validates JSON and supports explicit added folders. Tab context
menus, collision-safe file rename and a custom save/discard/cancel dialog complete
the document flow. Unsaved status is adjacent to the workflow summary.

Schema version 3 adds visual note steps and group definitions. Event group identities
travel with source events, so reordering/editing retains membership. The undo command
snapshots group definitions with events; cross-document clipboard copies receive fresh
identities. Note steps are skipped by replay and contribute no delay. Versions 1 and
2 remain readable and retain their serialized form when annotations are unused.

Desktop window activation is explicit and enabled by default before playback: KDE
uses a temporary identity-checked KWin script, and X11 requests activation through
EWMH. Activation happens after the countdown, before any input, and failure stops
playback with an error. Background routes retain their separate capabilities; this
does not make foreground desktop input independent of the user's pointer.

Validation includes responsive layouts at 1000–3440 pixels, continuous-camera
retargeting, live capture preview, saved-file discovery, tab rename/cancel behavior,
annotation schema validation, grouped clipboard/undo, and activation over a private
D-Bus server plus JavaScript evaluation against an owned workspace fixture.
