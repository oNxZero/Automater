# Contributing

Moonlight Studio is a native PySide6 Linux app. Start with the
[user guide](docs/USER_GUIDE.md), [format](docs/FORMAT.md) and [audit](docs/AUDIT.md).

## Development setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m build
```

Install Xvfb and xauth to run the private X11 integration checks rather than skip
them. CI runs `xvfb-run -a env QT_QPA_PLATFORM=offscreen python -m pytest -q` on
Python 3.11 and 3.14. Tests create controlled receivers/private displays and do not
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
  Include Linux desktop/session type and Studio/Python/Qt versions. Review doctor
  output before sharing; it may identify local devices and paths.

Direct game/compositor acceptance must be tested on an actual supported desktop;
mocked backends or a private X11 receiver cannot establish it. See the
[release checks](docs/RELEASE.md). Report security-sensitive issues through
[the private reporting route](SECURITY.md).
