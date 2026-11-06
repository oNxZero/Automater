# Install Automater

You need Linux and Python 3.11 or newer. From the repository folder, run:

```bash
./install.sh
```

The installer asks for sudo to install system packages on Debian/Ubuntu or Fedora. It
then sets up Python dependencies, configures input permissions and adds Automater to
your application menu. On other distributions, install the libraries
below and use `./install.sh --no-system-packages`.

Keep the checkout folder in place: the shortcut launches the app from there. If you move
it, rerun the installer. The menu also has a **Try the example** action that opens a
sample in Test mode.

You can also run `./start.sh` directly without installing a menu shortcut.

The launcher keeps Python packages in `.venv` and checks their versions after an update.
It looks for a supported Python if `python3` is too old. To choose one yourself, use
`AUTOMATER_PYTHON=python3.12 ./start.sh`.

The standard Qt wheels need glibc 2.34+ on x86_64 or 2.39+ on aarch64. Alpine/musl,
older glibc and other CPUs need a compatible Qt build. See [Linux
compatibility](COMPATIBILITY.md) for details.

## Manual installation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e .
.venv/bin/automater
```

Add `--demo` to open the sample in Test mode, or `--doctor` to print device and session
diagnostics. Editing and Test mode work without input-device permissions.

## System libraries

If evdev needs to compile, install Python development headers, a C compiler and Linux
input headers. On Fedora these are `python3-devel gcc kernel-headers`; on Debian/Ubuntu,
`python3-dev build-essential`.

Qt needs EGL/OpenGL and keyboard/XCB libraries. Minimal Debian/Ubuntu systems may need
`libegl1 libopengl0 libgl1 libglib2.0-0 fontconfig libfreetype6 libdbus-1-3
libxkbcommon0 libxcb-cursor0`. Qt's Wayland plugin is included. The separate-session
mode additionally needs Gamescope and GPU support; follow [the setup
guide](USER_GUIDE.md#run-independently-while-using-another-window) only if using that
mode.

On Fedora, common equivalents include `python3-pip python3-devel gcc kernel-headers
mesa-libEGL libglvnd-opengl mesa-libGL libxkbcommon libxcb xcb-util-cursor fontconfig
freetype glib2`. On minimal X11 installs, Qt also needs XCB ICCCM/keysyms/XKB, shape,
RandR, render, SHM, sync and Xfixes libraries, plus libX11-xcb. The [CI
workflow](../.github/workflows/ci.yml) lists the full Debian/Ubuntu package names. A
generic "xcb-cursor needed" Qt error can indicate another missing XCB dependency;
`QT_DEBUG_PLUGINS=1 ./start.sh` reports the underlying load failure. On native Wayland
it needs libwayland client/cursor/EGL libraries. Package names vary by distro; the CI
workflow shows the exact Debian/Fedora smoke-test setup.

Open **File → Linux compatibility** or run `./start.sh --doctor` to check your setup.
`--doctor --check-portal` also checks for pointer-control support without asking for
permission. Portal support varies between desktops; support for screen sharing alone
does not mean a backend can move the pointer.

Qt/PySide6 is kept on 6.11.x, with 6.11.2 pinned in `requirements.lock`. Version 6.12
caused a crash in the painting tests. Run the painting and clipboard shutdown tests
before changing that dependency.

## Updating and removal

Close Automater, run `git pull --ff-only`, then `./install.sh --no-system-packages` to
refresh dependencies and the menu shortcut. Rerun without that flag if system libraries
have changed. Workflow JSON files remain compatible. Appearance and preferences are
stored outside the checkout under `$XDG_CONFIG_HOME/automater`.

To remove the menu shortcut, run `.venv/bin/python -m automater.desktop --remove`. Then
close Automater and remove its checkout/virtual environment. Keep exported workflows and
the config directory if you want recovery/preferences. Input permissions are left in
place; Moonlight or other apps may also use them.

## Input permissions

`./install.sh` sets up input access automatically. It adds your account to the
`input` group, loads `uinput`, and writes:

- `/etc/udev/rules.d/99-automater.rules` for input-device permissions.
- `/etc/modules-load.d/automater.conf` to load `uinput` at boot.

Your other group memberships and any Moonlight rules are kept. Run the installer
as your regular user; it uses sudo for these changes. If your current session is
not already in the `input` group, log out and back in before recording or playback.

The `input` group can read keyboard activity across applications and send input
through `uinput`. Only give this access to trusted accounts.

To install just the editor and Test mode, skip input setup:

```bash
./install.sh --no-input-permissions
```

If system dependencies are already installed, you can combine the flags:

```bash
./install.sh --no-system-packages --no-input-permissions
```

To add input access later, rerun `./install.sh --no-system-packages`. This still
configures permissions; the flag only skips installing system packages.

If setup fails, the installer shows the error and stops. Check that `modprobe`,
`udevadm`, `groupadd` and `usermod` are installed, then retry. The app's
**Devices → Input access help** and `./start.sh --doctor` can help check your setup.
Wayland pointer-control permission is separate: grant it in Start settings if you
want an absolute cursor reset on a desktop that requires the portal.

After unplugging or reconnecting a device, stop recording or playback and refresh
the device list. A disconnect or event-buffer overflow stops the run with an error.
