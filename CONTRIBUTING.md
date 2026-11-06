# Contributing

Automater is a Linux desktop app built with Python and PySide6. The [user
guide](docs/USER_GUIDE.md) explains how it works; [Linux
compatibility](docs/COMPATIBILITY.md) lists the desktop requirements.

## Development setup

Use Python 3.11 or newer. Install the [system
libraries](docs/INSTALL.md#system-libraries), then run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python -m build
```

Install Xvfb and xauth for the X11 tests, and Weston for the Wayland startup test. Tests
that need those tools are skipped when they aren't available. CI runs the full suite on
Ubuntu 22.04/24.04 with Python 3.11/3.14, plus installation and startup checks on Debian
and Fedora. Tests use their own displays and input receivers; they don't send input to
your desktop apps.

For UI work, `./start.sh --demo` opens a sample workflow in Test mode.

For CLI work, `python -m automater run examples/input-controls.json --test` runs
without Qt or an input device. Tests use private runtime directories and a fake
portal on a private D-Bus session; they never request desktop permissions.

## Making changes

Explain the problem and how to reproduce it in your pull request. Add a regression test
for bugs involving input order, timing, saved files or editor behavior.

A few things to watch for:

- Keep playback work off the Qt UI thread. Preserve recorded samples and timing
  unless they're being edited, and release resources when startup fails.
- Use `theme.paint_color` for canvas colors and `theme.icon` for icons. Saved group
  colors belong to the workflow; app appearance belongs to Preferences.
- Use made-up input and window names in tests and screenshots. Don't commit personal
  recordings, preferences or recovery files. Git ignores JSON files at the repo root.
- Check UI changes in Daylight and a dark theme, at 1000×680 and a wider window.
  Try keyboard navigation, selection, typing notes, tabs, Undo and a Test mode run.

Automated tests don't cover real device input or game compatibility. Before a stable
release, also check recording and replay on a desktop, Stop releasing held keys, cursor
reset across monitors, denied permissions and a Gamescope game session.

## Reporting bugs

Include the steps to reproduce, what you expected and what happened. Give your Automater
version, Linux desktop and X11/Wayland session type. For playback bugs, say which
destination mode you used. Python and Qt versions help if you know them.

Check diagnostic output before posting it: device names, paths and window titles can
identify your setup. See [SECURITY.md](SECURITY.md) for sensitive bugs.

## Workflow data

Workflows are UTF-8 JSON files. Validation lives in `src/automater/models.py`;
`tests/test_models_storage.py` and the examples in `examples/` cover the format.
Versions 1–4 are still readable. Later versions added timing ranges, starting
coordinates, groups and group notes. Keep older files readable and preserve their
recorded samples when changing the format.

## Documentation screenshots

These commands capture the app's Qt widgets offscreen:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/screenshots.py
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/record_demo.py
```

The screenshots use a temporary config and example data. Window names and the recording
preview are filled in by the script. The GIF captures a real Test mode run at 20 fps,
then FFmpeg resizes and encodes the frames. These are staged app captures, not desktop
recordings or demonstrations of input reaching a game. FFmpeg is needed to make the GIF,
but not to run Automater.

Run `.venv/bin/python scripts/check_assets.py` after changing docs or images to check
for broken references and unused assets.
