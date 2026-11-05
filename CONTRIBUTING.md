# Contributing

Automater is a native PySide6 Linux app. Start with the
[user guide](docs/USER_GUIDE.md) and [Linux compatibility](docs/COMPATIBILITY.md).

## Development setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python -m build
```

Install Xvfb and xauth to run the private X11 integration checks rather than skip
them. CI runs `xvfb-run -a env QT_QPA_PLATFORM=offscreen python -m pytest -q` on
Python 3.11 and 3.14 on Ubuntu 22.04/24.04. Additional jobs check Debian/Fedora and
native XCB/Wayland GUI boot. Install Weston to run the headless Wayland check locally.
Tests create controlled receivers/private displays and do not
send input to a user's real applications. Run `./start.sh --demo` for UI work.

## Changes and bug reports

- Describe the trigger, expected behavior and what changed. Include focused
  regressions for input ordering, timing, persistence and interaction bugs.
- Keep replay work off the Qt thread. Preserve recorded event samples and timing
  unless the user explicitly edits them. Pair startup failures with cleanup.
- Use `theme.paint_color` for application canvas colors and `theme.icon` for icons.
  A group's saved custom color stays portable; appearance stays in Preferences.
- Do not commit recordings, preferences, recovery files or real window titles.
  Root workflow JSON files are ignored; use synthetic fixtures for tests/screenshots.
- Test UI changes at 1000×680 and a wide viewport, including Daylight. Check
  keyboard focus, selection, notes while typing, tabs, Undo and an input-free run.
- State whether a report uses Active desktop, Background X11 or a separate session.
  Include Linux desktop/session type and Automater/Python/Qt versions. Review doctor
  output before sharing; it may identify local devices and paths.

Direct game/compositor acceptance must be tested on an actual supported desktop;
mocked backends or a private X11 receiver cannot establish it. Before a stable
release, test real device recording/replay, held-input cleanup on Stop, pointer
reset across monitors, permission denial and GPU-backed game sessions.
Report security-sensitive issues through
[the private reporting route](SECURITY.md).

## Workflow data

Portable workflows contain versioned UTF-8 JSON data, never executable Python.
`src/automater/models.py` defines validation; `tests/test_models_storage.py` and the
synthetic files in `examples/` cover the format. Versions 1–4 remain readable;
newer fields add timing ranges, starting coordinates, visual groups and group notes.
Keep import compatibility and original event samples when changing the schema.

## Documentation screenshots

`QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/screenshots.py` refreshes native
Qt screenshots using synthetic workflows, an isolated config directory and Test
mode. It never captures physical input or connects to real destination windows.

`QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/record_demo.py` records the README's
looping GIF from real Test mode playback at 20 fps. Encoding requires FFmpeg;
Automater itself does not require FFmpeg. Temporary frames are cleaned up afterward.

Run `.venv/bin/python scripts/check_assets.py` after documentation or asset changes.
It checks references and unused files, including dynamically selected theme icons.
