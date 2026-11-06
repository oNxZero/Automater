<div align="center">

<img src="src/automater/assets/automater.svg" width="68" alt="Automater logo" />

# Automater

A keyboard and mouse recorder for Linux. Record a sequence, edit its actions and
timing, then replay it. You can also build a workflow by hand.

![Python](https://img.shields.io/badge/Python-3.11+-b5a4fa?style=flat-square)
![Linux](https://img.shields.io/badge/Linux-Wayland%20%7C%20X11-83b8f2?style=flat-square)
![Version](https://img.shields.io/badge/Automater-v0.13.3-75d6c0?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-9199b3?style=flat-square)
[![Checks](https://github.com/oNxZero/Automater/actions/workflows/ci.yml/badge.svg)](https://github.com/oNxZero/Automater/actions/workflows/ci.yml)

</div>

![Automater playing a workflow in Test mode](docs/workflow-demo.gif)

The GIF shows the app running an example in Test mode, without sending input.
It was captured offscreen; the screenshots in the guide use staged example data too.

## Install

Requires Linux, Git and Python 3.11+. The installer supports Debian/Ubuntu and
Fedora. See the [installation guide](docs/INSTALL.md) for other distributions.

```bash
(
  set -e
  mkdir -p "$HOME/.local/share"
  git clone https://github.com/oNxZero/Automater.git "$HOME/.local/share/Automater"
  cd "$HOME/.local/share/Automater"
  ./install.sh
)
```

Run this as your regular user. The installer uses sudo for system packages and
input permissions, sets up Python dependencies and adds **Automater** to your
application menu. Keep the installation folder in place; the menu shortcut points to it.

Input setup adds your account to the `input` group and enables `uinput` for playback.
This allows reading keyboard and mouse activity across apps. If the installer asks
you to log out and back in, do that before recording or playback.

For editing and Test mode only, run `./install.sh --no-input-permissions`.
**Devices → Input access help** has troubleshooting steps if access is still missing.

## Getting started

On first launch, the guided example walks through adding a key hold, a wait and
another key hold, then running the result in Test mode. You can skip it or reopen
it from **File → Guided example**.

To try the included sample:

```bash
~/.local/share/Automater/start.sh --demo
```

For your own recordings, choose a keyboard and mouse in **Devices**, then press
**F6** to start or finish recording. Click an action to edit it. **F7** runs or
stops playback, **F8** pauses, and **F12** stops or cancels. Global shortcuts need a
selected, readable keyboard.

The [user guide](docs/USER_GUIDE.md) covers editing, playback settings and shortcuts.

## Features

- Record keys, mouse buttons, relative movement and scrolling.
- Add holds, presses, releases and waits, with fixed or randomized timing.
- Move, copy and group actions. Add notes to explain sections of a workflow.
- Preview in Test mode before replaying, and repeat a workflow with a loop count.
- Work in multiple tabs and save workflows as JSON files.
- Switch between light and dark themes, or change the accent and background colors.

See the [theme screenshots](docs/USER_GUIDE.md#appearance-and-the-quick-guide).

## Linux support

Desktop recording and playback use evdev and uinput on X11 or Wayland.
Background playback to an existing window is limited to X11/Xwayland, and some
apps ignore it. Gamescope mode launches a new game instance on a separate display
and needs compatible GPU and game support.

Workflows are linear sequences. Conditional branches, nested loops, gamepads,
Windows and macOS are not supported. Mouse paths depend on the target app,
sensitivity and starting position; replaying the same input may give a different
result in a game.

See [Linux compatibility](docs/COMPATIBILITY.md) for desktop-specific support and
what has been tested.

## Update

Close Automater, then run:

```bash
cd "$HOME/.local/share/Automater"
git pull --ff-only
./install.sh --no-system-packages
```

Rerun `./install.sh` without the flag if an update needs new system libraries.
See [removal instructions](docs/INSTALL.md#updating-and-removal) to uninstall.

## Files and privacy

Workflows are local JSON files. Preferences and recovery files are stored in
`~/.config/automater`, or under `$XDG_CONFIG_HOME` if set. No account, telemetry or
cloud upload is involved. Recordings can contain personal input; check them before
sharing.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and checks.
Report bugs in [Issues](https://github.com/oNxZero/Automater/issues), and use
[SECURITY.md](SECURITY.md) for sensitive reports.

MIT licensed. Appearance inspired by [Moonlight](https://github.com/oNxZero/Moonlight).
