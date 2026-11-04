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
| Other native Wayland desktops | Exact reset unavailable | Disable reset to use relative replay; no Xwayland fallback is presented as a desktop warp |
| Test mode | Simulation only | No positioning or input emitted |

**Pick position · 3 s** lets you point at a location, then reads it without moving
the pointer. Picking and replay countdowns are cancellable; stale pick results are
ignored. Background coordinates are entered manually. The target window must be
chosen each session. Pointer capture in games may prevent positioning; a rejected
or unreachable point stops playback with an error instead of continuing there.

These paths have automated tests using mocked desktop providers and a controlled
X11 receiver. Physical desktop and game acceptance still require manual checks;
see [validation](VALIDATION.md).

## Protocol references

- [Xlib reference](https://xorg.freedesktop.org/X11R7.0/doc/PDF/xlib.pdf)
- [Hyprland dispatchers](https://wiki.hypr.land/Configuring/Dispatchers/)
- [Using hyprctl](https://wiki.hypr.land/Configuring/Using-hyprctl/)
- [Hyprland monitor coordinates](https://wiki.hypr.land/Configuring/Monitors/)
