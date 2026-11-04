# Starting coordinates on Linux

Starting coordinates are optional. Enable **Settings → Start → Reset cursor each
loop**, enter X/Y, and choose a settle delay. The initial countdown happens once;
every loop then moves first, settles, and starts the actions. F12 cancels countdown
or playback. This resets the pointer, not game state, a character or camera.

| Destination | Coordinate system | Implementation |
| --- | --- | --- |
| X11 active desktop | Root window screen pixels | Xlib root pointer warp, bounds and resulting position checked |
| Hyprland active desktop | Global logical pixels, including negative monitor positions | `hyprctl dispatch movecursor`, with monitor scale/transform bounds and result checked |
| X11 background window | Client-area pixels | Synthetic MotionNotify to the selected window; real cursor and focus stay unchanged |
| KDE / other Wayland desktops | Approved monitor logical coordinates | User-authorized RemoteDesktop + ScreenCast portal; requests NotifyPointerMotionAbsolute |
| Test mode | Simulation only | No positioning or input emitted |

**Choose on screen** opens a cancellable point picker. **Show starting point** marks
the point without moving there. On X11/Hyprland, **Pick position · 3 s** also lets
you point at a location, then reads it without moving
the pointer. Picking and replay countdowns are cancellable; stale pick results are
ignored. Background coordinates are entered manually. The target window must be
chosen each session. Pointer capture in games may prevent positioning; a rejected
or invalid point stops playback with an error instead of continuing there. Portal
acknowledgments cannot verify game acceptance.

For KDE and other portal desktops, click **Connect Wayland pointer**, approve input
control and select physical monitors. No frames are read from the screen streams;
only coordinate metadata is used. Permissions are temporary. Denial, cancellation,
revocation and connection loss stop or reject positioning. Disconnect closes the
portal session and pending permission requests. Relative uinput replay still requires
Linux input-device access. Pointer control does not enable background Wayland input.

These paths have automated tests using a private D-Bus portal server, mocked desktop
providers and a controlled
X11 receiver. Physical desktop and game acceptance still require manual checks;
see [validation](VALIDATION.md).

## Protocol references

- [Xlib reference](https://xorg.freedesktop.org/X11R7.0/doc/PDF/xlib.pdf)
- [Hyprland dispatchers](https://wiki.hypr.land/Configuring/Dispatchers/)
- [Using hyprctl](https://wiki.hypr.land/Configuring/Using-hyprctl/)
- [Hyprland monitor coordinates](https://wiki.hypr.land/Configuring/Monitors/)

- [RemoteDesktop portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [ScreenCast coordinate metadata](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)
