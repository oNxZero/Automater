# Linux compatibility

Automater targets modern Linux desktop systems using X11 or Wayland. "Linux" does
not imply every distribution, libc, CPU, desktop API or game accepts every feature.
Core recording uses evdev and desktop playback uses uinput, independent of the
desktop toolkit. Input permissions and a kernel exposing these devices are required.

## Runtime and distributions

The pinned PySide6-Essentials 6.11.2 wheels published on PyPI are:

| CPU | Standard wheel requirement |
| --- | --- |
| x86_64 | glibc 2.34+, Python 3.11+ for Automater |
| aarch64 | glibc 2.39+, Python 3.11+ for Automater |
| 32-bit / other CPUs | No standard wheel in this release; a compatible native Qt/PySide build is needed |
| musl / Alpine | Official wheels use glibc; the standard pip installer is unsupported |

The launcher detects an installed supported Python instead of assuming `python3`
is new enough. `AUTOMATER_PYTHON=/path/to/python` explicitly chooses an interpreter.
It checks standard-wheel ABI requirements before attempting a fresh install and
does not reject an already installed custom Qt build solely by wheel requirements.
An unsupported existing virtual environment is left intact with repair instructions.

| Distribution family | Current validation / requirement |
| --- | --- |
| Ubuntu 22.04 / 24.04 x86_64 | CI runs the full suite with Python 3.11 and 3.14; 22.04 needs a separately installed supported Python |
| Debian 12 x86_64 | CI container installation, core tests and GUI smoke check |
| Fedora 44 x86_64 | CI container installation, core tests and GUI smoke check |
| Arch, openSUSE, Gentoo and other glibc desktops | Expected when runtime/libs/permissions match; not separately distro-certified |
| NixOS / immutable or sandboxed installs | May need native packaging/FHS support or host device access; the generic installer is not certification |
| Older glibc systems / Alpine / other CPUs | Newer runtime or compatible native build required; not standard-install targets |

Container and headless-display tests verify installation/UI boot, not physical
compositor input or acceptance in games. ARM wheel availability is verified from
PyPI; ARM hardware is not exercised by this CI matrix.

## Desktop and display-server features

| Session | Record / desktop replay | Native window picker / focus guard | Absolute cursor reset |
| --- | --- | --- | --- |
| X11: KDE, GNOME, Xfce, Cinnamon, MATE, LXQt, other WMs | evdev/uinput with permissions | X11 window list and focus checks | X11 pointer warp, bounds/result checked |
| KDE Plasma Wayland | evdev/uinput with permissions | Compatible KWin scripting lists native and Xwayland windows | RemoteDesktop + ScreenCast portal, after approval |
| GNOME Wayland | evdev/uinput with permissions | X11/Xwayland list only; use Any active window for native apps | Compatible RemoteDesktop + ScreenCast portal, after approval |
| Hyprland | evdev/uinput with permissions | X11/Xwayland list only; Any active window for native apps | Direct hyprctl helper when present; compatible portal otherwise |
| Sway / other wlroots desktops | evdev/uinput with permissions | X11/Xwayland list only; Any active window for native apps | Only if the configured backend implements RemoteDesktop; screen sharing alone is insufficient |
| Other Wayland compositors | Core input conditional on devices/permissions | Native enumeration is not generic; X11 clients if Xwayland is present | Capability-dependent portal; disable reset if unavailable |
| No graphical session | Doctor works; no ordinary GUI desktop | None | None |

**Any active window** uses the normal desktop pointer/keyboard and requires you to
focus the destination during the countdown. It cannot verify focus of an app the
desktop does not expose. Native Wayland background routing is not implemented.
X11 background messages and Gamescope are separate modes with separate compatibility.

The app prefers Qt's native Wayland plugin, with XCB fallback when DISPLAY is also
available; explicit `QT_QPA_PLATFORM` overrides are preserved. Rendering through
Xwayland never makes an X11 warp a valid native Wayland pointer reset.

## Check your machine

Open **Devices → Check compatibility** or **File → Linux compatibility**. The panel
shows detected desktop/session, runtime, input requirements and feature limits.
**Check pointer portal** only reads interface properties; it does not open an input
permission dialog, create a capture session or read screen frames. **Connect Wayland
pointer** remains the separate, explicit authorization step.

Headless diagnostics:

```bash
./start.sh --doctor
./start.sh --doctor --check-portal
```

The optional portal check is time-bounded. A present interface still does not prove
the desktop will grant a session or a game will accept its input. The check verifies
RemoteDesktop pointer capability and ScreenCast physical-monitor capability before
Automater asks for permission. Missing interfaces produce an actionable error.

Portal monitor position/size metadata is optional in the protocol. Automater still
requires unambiguous geometry for exact global reset; it refuses to guess when a
backend omits it. Relative replay remains available with reset disabled.

## Verified protocol / runtime references

- [Exact PySide6 6.11.2 wheel files](https://pypi.org/project/PySide6-Essentials/6.11.2/#files)
- [Qt Linux glibc requirements](https://doc.qt.io/qt-6/linux.html)
- [Qt platform plugin selection and fallback](https://doc.qt.io/qt-6/qpa.html)
- [RemoteDesktop portal and available device types](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [ScreenCast capabilities and optional monitor metadata](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)
- [xdg-desktop-portal-wlr implements ScreenCast/Screenshot, not RemoteDesktop](https://github.com/emersion/xdg-desktop-portal-wlr)

CI covers installation, automated behavior and GUI startup. Real device input,
scaled/multiple monitors, game acceptance and GPU-backed sessions require testing
on the target desktop. A passing CI job does not establish those results.
