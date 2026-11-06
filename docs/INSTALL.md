# Install Automater

You need Linux and Python 3.11 or newer. From the repository folder, run:

```bash
./install.sh
```

The installer asks for sudo to install system packages on Debian/Ubuntu or Fedora. It
then sets up Python dependencies and adds Automater to your application menu. Device
permissions are a separate step below. On other distributions, install the libraries
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
the config directory if you want recovery/preferences. System input rules, if manually
installed, are separate administrator settings.

## Input permissions

Recording needs read access to your selected `/dev/input/event*` devices. Desktop
playback also needs write access to `/dev/uinput`. If you already use Moonlight, you may
have these permissions set up. Run Automater as your regular user.

The following rules grant the `input` group access to these devices. Membership allows
reading keyboard activity across applications, so only add trusted users. An
administrator can set this up with:

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

Log out and back in for group membership to take effect, then refresh devices. If your
system does not load uinput on boot, an administrator can add `uinput` to
`/etc/modules-load.d/automater.conf`. Your distribution may use different device-access
rules. The launcher does not change them. Stop recording before typing anything you do
not want included in a saved macro.

After unplugging or reconnecting a device, stop active work and refresh devices. If a
device disconnects or its event buffer overflows, Automater stops and shows an error.
