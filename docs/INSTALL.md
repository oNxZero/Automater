# Install Automater

Linux and Python 3.11+ are required. For dependencies and an application-menu shortcut,
start from the repository folder:

```bash
./install.sh
```

The installer requests sudo for system packages on Debian/Ubuntu or Fedora, prepares
the Python runtime and creates a per-user menu entry. It leaves device permissions
unchanged. On other distributions, install the libraries below and use
`./install.sh --no-system-packages`. The app stays in the checkout; rerun the installer
after moving it. The menu entry includes **Try the example** without input output.

To run directly without menu integration, use `./start.sh`.

The launcher creates `.venv`, installs the tested runtime and checks dependency
versions after updates. It never installs system packages or changes permissions.
It searches for a supported Python if `python3` is older than 3.11; use
`AUTOMATER_PYTHON=python3.12 ./start.sh` to choose one explicitly. The standard Qt
wheels require glibc 2.34+ (x86_64) or 2.39+ (aarch64). Alpine/musl, older glibc and
other CPUs require a compatible native build instead. See [compatibility](COMPATIBILITY.md).

## Manual installation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e .
.venv/bin/automater
```

For an input-free example, append `--demo`. To inspect device/session diagnostics,
append `--doctor`. Editing and Test mode do not require physical input access.

## System libraries

If evdev needs to compile, install Python development headers, a C compiler and
Linux input headers. On Fedora these are `python3-devel gcc kernel-headers`; on
Debian/Ubuntu, `python3-dev build-essential`.

Qt needs EGL/OpenGL and keyboard/XCB libraries. Minimal Debian/Ubuntu systems may
need `libegl1 libopengl0 libgl1 libglib2.0-0 fontconfig libfreetype6 libdbus-1-3
libxkbcommon0 libxcb-cursor0`. Qt's Wayland plugin is
included. The separate-session mode additionally needs Gamescope and GPU support;
follow [the setup guide](USER_GUIDE.md#run-independently-while-using-another-window) only if using that mode.

On Fedora, common equivalents include `python3-pip python3-devel gcc kernel-headers
mesa-libEGL libglvnd-opengl mesa-libGL libxkbcommon libxcb xcb-util-cursor fontconfig
freetype glib2`. On minimal X11 installs, Qt also needs XCB ICCCM/keysyms/XKB,
shape, RandR, render, SHM, sync and Xfixes libraries, plus libX11-xcb. The workflow
lists the Debian/Ubuntu package names explicitly. A generic "xcb-cursor needed"
Qt error can indicate another missing XCB dependency; `QT_DEBUG_PLUGINS=1 ./start.sh`
reports the underlying load failure.
On native Wayland it needs libwayland client/cursor/EGL libraries. Package names
vary by distro; the CI workflow shows the exact Debian/Fedora smoke-test setup.

Use **File → Linux compatibility** or `./start.sh --doctor` to report your runtime
without guessing from the distro name. `--doctor --check-portal` checks pointer
interfaces without permission prompts. GNOME, KDE, wlroots and other backends can
implement different portal interfaces; do not install an arbitrary backend solely
because it supports screen sharing.

The runtime is constrained to Qt/PySide6 6.11.x, with 6.11.2 tested in the lock file.
Do not upgrade it independently without running the native painting and clipboard
shutdown tests. The current constraint avoids a reproduced Qt 6.12 binding crash.

## Updating and removal

Close Automater, run `git pull --ff-only`, then `./install.sh --no-system-packages`
to refresh dependencies and the menu shortcut. Rerun without that flag if system
libraries have changed.
Workflow JSON files remain compatible. Appearance and preferences are stored
outside the checkout under `$XDG_CONFIG_HOME/automater`.

To remove the menu shortcut, run `.venv/bin/python -m automater.desktop --remove`.
Then close Automater and remove its checkout/virtual environment.
Keep exported workflows and the config directory if you want recovery/preferences.
System input rules, if manually installed, are separate administrator settings.

## Input permissions

If your existing Moonlight clicker works, its permissions may already be sufficient.
Otherwise, an administrator needs to load `uinput` and grant your account read access
to the selected `/dev/input/event*` devices and write access to `/dev/uinput`.
**Run the application as your regular user.**

One optional persistent setup, similar to the original Moonlight installer:

```bash
sudo modprobe uinput
sudo groupadd -f input
sudo usermod -aG input "$USER"
sudo tee /etc/udev/rules.d/99-automater.rules >/dev/null <<'RULES'
SUBSYSTEM=="misc", KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
SUBSYSTEM=="input", KERNEL=="event*", GROUP="input", MODE="0660"
RULES
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Log out and back in for group membership to take effect, then refresh devices.
If your system does not load uinput on boot, an administrator can add `uinput` to
`/etc/modules-load.d/automater.conf`. Existing distribution/udev policies
may require different rules. This setup grants broad access to physical input,
including keyboard activity across applications; restrict it to trusted users.
The launcher never changes system permissions itself. Stop recording before typing
anything you do not want included in a saved macro.

After unplugging or reconnecting a device, stop active work and refresh devices.
Disconnects and dropped event buffers stop active work with an error rather than
continuing a potentially incomplete recording.
