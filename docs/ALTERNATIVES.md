# Similar tools

Reviewed against project/vendor documentation on 2026-11-04. These are feature and
platform comparisons, not hands-on game compatibility tests.

| Tool | Platform / focus | How it compares |
| --- | --- | --- |
| [AutoKey for Wayland](https://autokey-wayland.readthedocs.io/en/latest/) | Linux desktop automation for Wayland and X11 | Useful for Python scripting, phrases and hotkey-driven automation. Its documentation explains API availability and platform limits. |
| [atbswp](https://github.com/RMPR/atbswp) | Python macro recording for Linux and Windows | Close to the basic record/replay use case. Its README currently documents Xorg-only Linux support. |
| [Pulover’s Macro Creator](https://www.macrocreator.com/) | Windows; AutoHotkey-based recorder and macro editor | Recording, visual command editing, loops and conditionals, with control commands for background windows. Useful interaction reference for building macros without writing every command. |
| [Macro Recorder](https://www.macrorecorder.com/) | Windows and macOS | Record, review/edit and repeat mouse/keyboard actions. Its product page also describes image/OCR and other automation features. |
| [Power Automate desktop flows](https://learn.microsoft.com/en-us/power-automate/desktop-flows/recording-flow) | Desktop and web application automation | Recorder generates editable flow actions tied to UI elements. Relevant to guided workflow design, rather than raw game-input capture. |

Automater's current focus is a Linux evdev/uinput recorder with a linear
left-to-right macro canvas and a precise raw event view. A tool listing background
window commands does not establish compatibility with raw-input games, native
Wayland background routing, or protected games. Those need target-specific testing.
