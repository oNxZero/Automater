# Linux compatibility

Automater runs on Linux with X11 or Wayland. Recording uses evdev; desktop playback uses
uinput. Both need access to the relevant input devices.

The tables below show runtime requirements, desktop differences and what CI covers. Game
compatibility still needs testing on your own setup.

## Runtime and distributions

The PySide6-Essentials 6.11.2 packages in `requirements.lock` have these requirements:

| CPU | Standard wheel requirement |
| --- | --- |
| x86_64 | glibc 2.34+, Python 3.11+ for Automater |
| aarch64 | glibc 2.39+, Python 3.11+ for Automater |
| 32-bit / other CPUs | No standard wheel in this release; a compatible native Qt/PySide build is needed |
| musl / Alpine | Official wheels use glibc; the standard pip installer is unsupported |

The launcher looks for a supported Python version. Set
`AUTOMATER_PYTHON=/path/to/python` to choose one yourself. It checks wheel requirements
before a fresh install, but allows an already installed custom Qt build. If the existing
`.venv` uses an unsupported Python, it explains how to fix it and leaves the folder in
place.

| Distribution family | Current validation / requirement |
| --- | --- |
| Ubuntu 22.04 / 24.04 x86_64 | CI runs the full suite with Python 3.11 and 3.14; 22.04 needs a separately installed supported Python |
| Debian 12 x86_64 | CI container installation, core tests and GUI smoke check |
| Fedora 43 / 44 x86_64 | CI checks system packages, menu installation, core tests and GUI startup |
| Arch, openSUSE, Gentoo and other glibc desktops | Should work with the required libraries and permissions; not checked in CI |
| NixOS / immutable or sandboxed installs | May need distribution-specific packaging, an FHS environment or host device access; not checked in CI |
| Older glibc systems / Alpine / other CPUs | Need a newer runtime or compatible Qt build; the standard installer does not cover these |

CI checks installation, app startup and automated behavior in containers and virtual
displays. It does not test physical input or games. ARM packages are available on PyPI,
but CI does not run on ARM hardware.

Input setup is tested with temporary files and simulated system commands. Container
installations use `--no-input-permissions`; loading kernel modules and applying device
rules need a real desktop system.

## Desktop and display-server features

| Session | Record / desktop replay | Native window picker / focus guard | Absolute cursor reset |
| --- | --- | --- | --- |
| X11: KDE, GNOME, Xfce, Cinnamon, MATE, LXQt, other WMs | evdev/uinput with permissions | X11 window list and focus checks | X11 pointer warp, bounds/result checked |
| KDE Plasma Wayland | evdev/uinput with permissions | Compatible KWin scripting lists native and Xwayland windows | RemoteDesktop + ScreenCast portal, after approval |
| GNOME Wayland | evdev/uinput with permissions | X11/Xwayland list only; use Any active window for native apps | Compatible RemoteDesktop + ScreenCast portal, after approval |
| Hyprland | evdev/uinput with permissions | X11/Xwayland list only; Any active window for native apps | Direct hyprctl helper when present; compatible portal otherwise |
| Sway / other wlroots desktops | evdev/uinput with permissions | X11/Xwayland list only; Any active window for native apps | Only if the configured backend implements RemoteDesktop; screen sharing alone is insufficient |
| Other Wayland compositors | Requires input devices and permissions | Native window lists depend on the desktop; X11 windows appear with Xwayland | Requires a pointer-control portal; leave reset off if unavailable |
| No graphical session | Doctor works; no ordinary GUI desktop | None | None |

**Any active window** uses your desktop pointer and keyboard. Focus the destination
during the countdown. If the desktop cannot list that app, Automater cannot check its
focus. Sending background input to an existing native Wayland window is not supported.
X11 background playback and Gamescope have their own requirements.

On Wayland, the app tries Qt's Wayland plugin first and falls back to XCB when `DISPLAY`
is available. You can override this with `QT_QPA_PLATFORM`. Running the UI through
Xwayland does not let it move the native Wayland pointer through X11.

## Check your machine

Open **Devices → Check compatibility** or **File → Linux compatibility**. The panel
shows your desktop, session, library versions and available features. **Check pointer
portal** checks for the required interfaces without opening a permission dialog or
reading screen frames. Use **Connect Wayland pointer** when you want to grant pointer
access.

When a workflow needs cursor reset, the editor and CLI connect automatically. Remote
Desktop portal version 2 supports saved approval; Automater requests it and reuses the
replacement token returned by each successful connection. Older portals may prompt
every time. The desktop can still require approval after access is revoked or monitors
change. This uses the portal's normal permission flow; sudo cannot approve the dialog.

You can also check from a terminal:

```bash
./start.sh --doctor
./start.sh --doctor --check-portal
```

The portal check looks for RemoteDesktop pointer support and ScreenCast monitor support,
and times out if the portal does not answer. It reports missing interfaces, but cannot
tell whether permission will be granted or a game will accept the input.

Some portals omit monitor position or size. Automater needs those coordinates for cursor
reset, so reset is unavailable without them. Relative movement still works with reset
turned off.

## References

- [Exact PySide6 6.11.2 wheel files](https://pypi.org/project/PySide6-Essentials/6.11.2/#files)
- [Qt Linux glibc requirements](https://doc.qt.io/qt-6/linux.html)
- [Qt platform plugin selection and fallback](https://doc.qt.io/qt-6/qpa.html)
- [RemoteDesktop portal and available device types](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [ScreenCast capabilities and optional monitor metadata](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)
- [xdg-desktop-portal-wlr implements ScreenCast/Screenshot, not RemoteDesktop](https://github.com/emersion/xdg-desktop-portal-wlr)
