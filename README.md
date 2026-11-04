# Moonlight Studio

A Python input recorder and visual macro editor for Linux, inspired by
[Moonlight](https://github.com/oNxZero/Moonlight). Record a routine, edit its timing
and actions, and replay it with a visible stop control.

![Moonlight Studio editor](docs/editor.png)

## Run

Requires Linux and Python 3.11+. From this directory:

```bash
./start.sh
```

The launcher creates a local virtual environment and installs the package on its
first run. For a manual install:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e .
.venv/bin/moonlight-studio
```

Try the editor without input permissions:

```bash
./start.sh --demo
./start.sh --doctor
```

`--demo` loads an example and enables **Test mode**, which runs the scheduler and
highlights steps without sending input. `--doctor` prints device/session
diagnostics without opening the UI. If evdev needs to compile, install your
distribution's Python development headers, compiler, and Linux input headers
(Fedora: `python3-devel gcc kernel-headers`; Debian/Ubuntu: `python3-dev build-essential`).
Qt also needs the system's EGL/OpenGL libraries, even for offscreen rendering.
On a minimal Debian/Ubuntu installation, install `libegl1 libopengl0 libgl1
libxkbcommon0 libxcb-cursor0`. Qt's Wayland plugin is included; X11 sessions also
use the system's XCB libraries.

## What works in v0.1

- Physical keyboard presses/releases, mouse buttons, relative mouse movement, and
  vertical/horizontal scrolling, with editable delays.
- Device selection and separate keyboard/button/movement recording filters.
- A visual table: insert key taps, clicks, waits, motion, or scrolling; edit cells;
  duplicate, reorder, disable, delete, and undo/redo up to 50 changes.
- 0.1–10× replay speed, repeat count or “until stopped,” startup countdown, loop gap,
  pause/resume, and interruptible stop. Held inputs are released during cleanup.
- Script library, notes, JSON import/export, atomic saves, five-second autosave,
  explicit recovery, and unsaved-change prompts.
- **Desktop / uinput** output for Wayland and X11. It sends to the active desktop;
  focus the game during the start delay.
- **Background / X11** output to an explicitly selected X11 or Xwayland program
  window. It does not steal focus, move the real pointer, or fall back to desktop
  input. This mode is experimental and games can ignore its messages.

## Record → edit → replay

1. Open **Setup**, check your keyboard/mouse devices, and click **Apply / refresh devices**.
2. Select capture categories on the right. Click **Record** or press **F6**. Switch
   to your game during the countdown and perform the routine.
3. Press **F6** again to finish. Recording replaces the event list; Undo restores
   the previous list. Recordings include a trailing wait and missing key releases.
4. Double-click table cells to change their values. Delays occur **before** each
   enabled step, in milliseconds. Disabling a step also skips its delay. `X` and `Y`
   are relative mouse deltas or horizontal/vertical scroll notches. Positive wheel
   Y is up; positive wheel X is right. Key names use Linux `KEY_*` and `BTN_*` codes.
5. Run **Test mode** to check the sequence. Turn it off for real replay, choose a
   route, set the repeat/speed controls, and click **Play** or press **F7**.
6. Use **Save as** to add the script to your library or export it elsewhere.

| Physical shortcut | Action |
| --- | --- |
| F6 | Start / finish recording, or cancel its countdown |
| F7 | Start / stop playback |
| F8 | Pause / resume playback |
| F12 | Stop recording, countdown, or playback |
| Ctrl+N / Ctrl+O / Ctrl+S | New / open / save in the editor |
| Ctrl+Shift+S | Save as |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo event edits |

Global F-keys require a selected, readable physical keyboard. They are reserved and
excluded from recordings; they still reach the foreground application. The app
does not grab devices. During replay, the virtual output device is excluded from
monitoring to prevent feedback. Pause releases held inputs; resume presses those
logical holds again. Repeat boundaries release all held keys and buttons.

## Linux device permissions

If your existing Moonlight clicker works, its permissions may already be sufficient.
Otherwise, an administrator needs to load `uinput` and grant your account read access
to the selected `/dev/input/event*` devices and write access to `/dev/uinput`.
**Run the application as your regular user.**

One optional persistent setup, similar to the original Moonlight installer:

```bash
sudo modprobe uinput
sudo groupadd -f input
sudo usermod -aG input "$USER"
sudo tee /etc/udev/rules.d/99-moonlight-studio.rules >/dev/null <<'RULES'
SUBSYSTEM=="misc", KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
SUBSYSTEM=="input", KERNEL=="event*", GROUP="input", MODE="0660"
RULES
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Log out and back in for group membership to take effect, then refresh devices.
If your system does not load uinput on boot, an administrator can add `uinput` to
`/etc/modules-load.d/moonlight-studio.conf`. Existing distribution/udev policies
may require different rules. This setup grants broad access to physical input,
including keyboard activity across applications; restrict it to trusted users.
The launcher never changes system permissions itself. Stop recording before typing
anything you do not want included in a saved macro.

After unplugging or reconnecting a device, stop active work and refresh devices.
Disconnects and dropped event buffers stop active work with an error rather than
continuing a potentially incomplete recording.

## Background compatibility

| Target | Desktop replay | Background replay |
| --- | --- | --- |
| Native Wayland application | uinput | Unsupported |
| X11 application | uinput | Experimental directed X11 events |
| Xwayland application | uinput | Experimental directed X11 events |
| Windows / macOS | Future backend | Future assessment |

The program picker lists **windows**, with title and PID. Refresh it after opening
the game. Window identity and liveness are checked during playback; losing the
target stops playback. Background key mapping assumes the standard Xorg/Xwayland
evdev XKB mapping. Background mouse movement is a virtual cursor starting in the
window center, clamped to its initial client bounds. It is not raw camera motion.
Some applications expect input on a child widget instead of the selected top-level
window; those applications may not respond. Synthetic events do not update global
physical key state. Raw-input games, minimized apps, and protected games may ignore
them. There is no anti-cheat bypass or injection into a game's process.

This release captures ordinary keyboard codes, supported mouse buttons, and
relative motion/wheel. It does not capture touch/absolute devices, gamepads, IME
composition, or high-resolution wheel metadata. Linux keyboard codes outside the
ordinary keyboard range are not recorded. Background mode supports keycodes that
fit X11's 8–255 range and at most 100 scroll notches per step. Relative paths depend
on the starting pointer/camera position, game sensitivity, acceleration, and bindings;
they are not screen-coordinate recordings. Scripts have a 200,000-step limit.

## Files and privacy

Configuration lives in `$XDG_CONFIG_HOME/moonlight-studio` (normally
`~/.config/moonlight-studio`). Saved library scripts are under `scripts/`;
unfinished edits are autosaved to `recovery.json` every five seconds while idle.
Stopping a recording also autosaves its result. Recordings in progress are held
in memory until stopped. Autosave does not overwrite your named script. A clean
save clears recovery; normal close prompts for unsaved changes. An incomplete
recording can be lost if the process is force-killed before stopping.

Macro files contain versioned JSON data, never executable Python. They contain
your recorded input, so keep them private. No telemetry, network calls, or cloud
uploads are implemented. Files are written with private permissions and atomically
replaced. Imports are limited to 32 MiB and strictly validated before replay.

The replay worker is separate from Qt's event loop. Stop and cleanup run on normal
completion, cancellation, errors, pause, and application close. Force-killing the
process or losing power cannot run Python cleanup code. Hardware behavior still
needs testing on your compositor and target game; see [validation](docs/VALIDATION.md).

## Development

```bash
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m build
```

X11 integration tests use an unmapped controlled receiver and never change focus.
They skip if no X server is available. To run everything on a headless machine,
install Xvfb and run `xvfb-run -a env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.

See the [complete feature plan and roadmap](docs/PLAN.md), [script format](docs/FORMAT.md),
and [verification evidence](docs/VALIDATION.md). Source is independently implemented;
Moonlight supplies the product direction and color palette. Qt is distributed under
its upstream license; dependency licenses remain their respective owners'.
