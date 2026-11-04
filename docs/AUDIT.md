# Bug and usability audit — v0.6

Reviewed selection/editing, recording, pointer setup, playback feedback, asynchronous
cancellation and the Qt layout on 2026-11-04. This is a bounded audit with regression
evidence, not a claim that every bug has been found.

## Fixed

| Problem | Fix and evidence |
| --- | --- |
| Test mode made playback animate while emitting nothing | Confirmed enabled in the user's settings. Added a prominent explanation and Use real inputs button. |
| KDE Wayland had no exact reset provider | Added explicit RemoteDesktop/ScreenCast permission setup, approved-monitor bounds and positioning. Private real-D-Bus tests verify the protocol and replay integration; physical acceptance remains a manual check. |
| Matching selected actions could not be edited together | Added shared properties, Mixed indicators and atomic, undoable bulk changes. |
| Bulk editing could copy unrelated values from the first action | Only touched fields apply; tests retain different keys, timing ranges and samples. |
| Re-recording required replacing everything | Replace a selected contiguous span, preserve prefix/suffix, and allow discard/undo. |
| Record replaced work by default | Append is the default, including migration of old preferences. Whole-workflow replacement requires an explicit choice. |
| Empty recording changed existing work | Empty or discarded captures preserve the original actions. |
| Box selection required an obscure modifier | Left-drag selects; middle-drag pans, with Qt pointer-event tests. |
| Clearing Events selection left stale properties | Clear cards/properties with the table; prevent partial raw rows from expanding into a bulk edit. |
| Properties clipped in a small window | Scroll the complete inspector contents, keep Apply visible, remove duplicate controls and hide unused ranges. Visually checked at 1240×800 and 1000×680. |
| Opening properties clipped the selected card at the canvas edge | Reveal the selection after panel/window resizing settles. Defer scrolling until mouse release to preserve dragging. Eight regression cases cover all layouts, both window widths, resizing and an active pointer gesture; zoom and events stay unchanged. |
| Random timing estimates showed a single total minimum | Show a total range. |
| Recorded cleanup released modifiers too early | Release other held keys before modifiers. |
| F-keys did nothing locally without evdev access | Local fallback when monitoring is unavailable; no auto-repeat or duplicate global delivery. |
| Expired overlays could access deleted Qt windows | Idempotent cleanup and cancellation guards for delayed callbacks. |
| Portal changes could deliver stale UI callbacks | Ignore superseded connections; handle revocation, bus disconnect and cancellation. |
| Grid lines had sharp corners and highlights changed abruptly | Rounded connectors and short hover/selection/guide transitions; rendering regression coverage. |

## Remaining desktop checks and product limitations

- This environment has no physical input/uinput nodes. Recording, injection into
  real games, device reconnection and high-rate timing need the [manual checks](VALIDATION.md).
- Portal tests use a fake portal on a real private D-Bus daemon. KDE/GNOME versions,
  permissions, monitor scaling/hotplug and game pointer capture need actual desktop
  testing. A portal acknowledgment cannot prove a game accepted a move.
- Relative movement depends on acceleration, sensitivity and scaling. Guides are
  approximate and do not predict a game's camera. Verify overlays with fractional
  scaling and fullscreen games.
- X11 background messages can be ignored by games; native Wayland background
  routing is unavailable. Pointer permission does not change these capabilities.
- Global hotkeys require a selected readable keyboard. Local fallback works when
  Automater is focused. Re-recording nonadjacent spans is rejected to keep one clear
  replacement position.
- Configurable hotkeys and run presets and a real-device compatibility
  report remain useful follow-ups before broader Linux/game reliability claims.


## v0.6 findings and changes

- Existing-window routing cannot guarantee a game accepts synthetic X11 messages,
  and it cannot route to a native Wayland client. Added a separate-display session
  option with private XTEST input; it requires launching the app there and compatible
  Vulkan/GPU support. Sober itself still needs real-game validation.
- Countdown display restarted from the time a GUI signal arrived. It now uses the
  worker's actual deadline, including preparation/registration timing.
- Upcoming input was highlighted while waiting for its delay. Feedback now separates
  delay, Timer, held keys, positioning, settle, gap and actual completed events.
- Finish/Stop cleared the only evidence of where a run ended. Last-loop completed,
  last, interrupted and failed markers now persist per document with diagnostics.
- Mouse X/Y axes from a physical report became separate replay reports. They now
  stay together with report spacing and counts retained; different source devices
  never merge. This improves fidelity but does not establish exact game-camera paths.
- Added independent document undo/view/run settings and recovery files; new/open no
  longer discards work, and saving cannot collide with another open file.
- A host-pointer comparison in an X11 test could fail when the user physically moved
  the mouse. It now forbids pointer-warp/XTEST APIs in background routing; separate
  input tests use a test-owned Xvfb server.


## v0.7 findings and changes

| Finding | Fix / evidence |
| --- | --- |
| Tiny wakeup delays accumulated across every motion report | Preserve cumulative deadlines. A local 1,000-report dry run requesting 1 s improved from 1.0533 s to 1.000066 s. This is scheduler evidence, not a real-game acceptance guarantee. |
| Catching up after a late press could shorten its hold or the next release interval | Protect each key/button transition interval from actual dispatch completion; deterministic regressions cover late keyboard and mouse sends. |
| Recording waited for a 100 ms UI tick after the countdown | Arm capture immediately against the monotonic deadline; ignore earlier input and retain the first post-deadline press before the UI tick. |
| Keyboard batches could precede older mouse events | Drain pending evdev batches before merging events by kernel timestamp; preserve per-device report order even when more than 64 events are queued. |
| App selection looked like choosing a game executable | Search open windows directly. Native KDE Wayland windows are discovered read-only; unsupported background delivery is labelled and offers desktop playback explicitly. |
| A closed desktop target could become unrestricted playback after refreshing | Retain the unavailable selection and reject playback until the user chooses a valid window or explicitly clears it. |
| Action pages interrupted long workflows | Replace pages with global positions and viewport virtualization; a 20,000-event regression scrolls/follows a 10,001-action scene without losing events. |
| Dragging gave no origin or insertion preview | Original-position markers, proposed-order ghosts and neighbours, edge scrolling, Escape cancellation and one-drop Undo. |
| Playback camera jumped between cards | Cancellable easing animation, clamped endpoints, and a Follow playback toggle. Replay scheduling remains in its worker. |
| Tabs sat above the title and close icons crossed the edge | Tabs now sit above the editor; native close-button geometry reserves an inset. |
| Saved tabs used the internal Untitled title and file choosers disagreed | Tab labels use filename stems. Open/Save As share an existing directory, remember it and resolve relative saves within it; dialog regressions cover restart and new tabs. |

Physical-game accuracy and native Wayland discovery outside KDE still require
platform-specific work. No claim is made that every real game accepts every input.


## v0.8 usability findings

| Finding | Change / verification |
| --- | --- |
| Grid stayed four columns wide on large monitors | Derive columns from viewport width and zoom; reflow on resize/inspector changes and defer it during active pointer gestures. A 3440×1440 check used 12 columns. |
| Fast actions restarted the camera's easing curve | Use a critically damped camera retaining position and velocity on retarget; keep a precise timer and viewport-local graphics updates. |
| Library missed JSON files saved outside its internal folder | Index known save folders, recent files and the launcher directory; Add folder includes other locations. Ignore invalid/configuration JSON and scan off the UI thread. |
| Tabs lacked file/document controls | Right-click rename/save/save as/close/close others, plus double-click rename. Refuse destination collisions and preserve unsaved edits. |
| Recording gave no indication of captured content | Bounded live preview of recent actions, total count, elapsed time and held inputs; only finish commits events. |
| Explanations and categories were missing | Named colored groups with persistence, Undo and cross-tab clipboard metadata; v0.9 replaces inline note cards with explanations on a single group rectangle. |

## v0.9 playback and grouping findings

| Reproduced problem | Resolution |
| --- | --- |
| Completed cards left all connecting arrows neutral | Connections use the worker trace for completion, running, pause and failure colors; only visible active streams animate. Timers stop while hidden or paused. |
| Camera bounced up to an earlier action near the bottom | Focus follows the latest sent/active row independently of older held inputs. Last-run banner resizing no longer reveals a stale selection. |
| Retargeting near a scroll limit overshot and reversed | Clamp each spring axis when it reaches the target; retain velocity only while approaching it. |
| Grid reflow discarded the playback camera target | Carry the active follow target through geometry changes and retarget against the new scroll bounds. |
| New-tab control sat beyond the tab strip | Put a visible + directly after the tabs; Ctrl+T remains available. |
| Inline notes occupied executable card positions; groups fragmented across rows | Remove inline note authoring/rendering. Each group has one tinted bounding rectangle with its own explanation inspector. Legacy cards migrate without altering inputs. |
| Group backgrounds could block box selection | Recognize a click on release; an actual drag continues through the graphics view's rubber-band selection. |
| Metadata edits cleared run results and collapsed multi-selection | Separate executable changes from annotations; retain source-row selection, viewport and the worker trace for visual-only changes. |
| Latest notes could be omitted during copy, save or tab switching | Flush the debounced draft before document/clipboard operations; preserve the selected group on return to a tab. |
| Autosaving notes reset the cursor to the beginning | v0.9.1 avoids replacing unchanged text/name fields during the synchronous save refresh. Cursor, selection, scroll and native text undo survive, while switching groups or Undo still loads changed values. |
| Toolbar Undo and Duplicate bypassed pending note edits | Flush drafts before Undo/Redo and before cloning group definitions, so undo and duplicated notes use the latest text. |
| Wrapped group rectangles drew headings on top of each other | Anchor the label above the group's first member and resolve heading clicks before overlapping background bounds. |
| An invalid draft could desynchronize the selected tab from its document | Keep the current tab and draft intact, show validation feedback, and avoid executing another tab's menu action. |
| Group inspector fields collapsed at 1000×680 | Put the notes panel in a scroll area and retain a usable text-editor height. |
| Newer file versions could be downgraded when other optional fields were serialized | Compute required schema with max(existing, required); preserve an explicitly loaded version. |
| Copying actions could crash Qt during interpreter shutdown | Reproduced a Python-owned QMimeData destructor running after Python exit. Use Qt-owned text clipboard data containing the validated action envelope; keep legacy custom-MIME paste support. A subprocess regression checks normal exit without clearing copied data. |

The grouping rectangle encloses its members' bounds. A nonadjacent group can
visually contain unselected cards; those cards are not added to the group. This is
a visual annotation, not a nested execution scope. Physical compositor/game input
acceptance remains outside these UI regressions.

## v0.10 creation and public-preview audit

| Finding | Fix |
| --- | --- |
| Theme colors only existed as fixed dark literals | Central palette mapping for widgets, canvas, connections, icons, event marks and preview; eleven gallery presets and local accent/background overrides. Daylight includes readable assets and softer shadows. |
| Custom backgrounds could reduce text contrast | Automatically choose text/subtext colors meeting 4.5:1 against the background; group labels keep contrast without changing saved group colors. |
| Theme changes could discard the editing context | Repaint without rebuilding events/scene or changing document state. Verify selection, caret, Undo, notes and run results remain intact. Lock the gallery during capture/playback. |
| Add Move/Scroll required another edit just to enter values | Include relative X/Y and signed scroll notches in the creation dialog, with units/direction explained. |
| Grouping a subset renamed the entire existing category | Give the subset an independent identity, retaining the other members' name, color and notes. |
| Opening the group dialog replaced custom imported colors | Retain a Custom color entry instead of selecting the first preset. |
| Ctrl+Z in text could invoke document Undo | Route focused text fields to their native history; canvas and toolbar use workflow Undo. |
| Invalid note drafts could be discarded by deleting group members or starting capture | Guard model commits, deletion and recording before any mutation/device setup; preserve the draft and show validation feedback. Clear failed pending selection changes. |
| An incomplete group name prevented quitting without a discard choice | Quit offers Save/Discard/Keep editing for the unserializable draft. Discard closes that workflow; Cancel retains its text. |
| Open/example commands claimed success despite a blocked document switch | Return actual load success and update recent files, status and Test mode only after successful activation. |
| Every new unsaved tab had the same title | Use distinct Untitled workflow names until renamed/saved. |
| Failed playback validation cleared previous results | Keep last-run feedback until a new replay actually starts. |
| Notes said Saved before the JSON was written | Use Applying/Applied and an Apply notes button; explicitly explain that Ctrl+S saves the file. |
| Clearing an imported description hid the editor and its Undo | Keep the empty description editor visible while it retains focus. |
| Onboarding depended on a long release-history README | Provide an offline Quick guide; shorten README, separate installation instructions and archive earlier feature notes. |
| Local recordings could accidentally enter a public repository | Ignore root JSON recordings; verify history and source/wheel contents; use synthetic screenshot/test data. |

The native Qt visual pass also caught theme gallery cards compressed below their
label height and double-mapped icon colors in Daylight; both have regressions.
Publication and real game/compositor acceptance remain owner/manual checks in
[RELEASE](RELEASE.md). This audit does not claim that every possible bug is gone.

## v0.11 Linux compatibility findings

| Finding | Fix / explicit boundary |
| --- | --- |
| Missing display variables were treated as X11 | Shared session detection distinguishes native X11, Wayland with Xwayland and headless sessions. Pointer reset fails clearly without a graphical desktop. |
| Stale WAYLAND_DISPLAY / Hyprland variables selected the wrong pointer backend | An explicit XDG_SESSION_TYPE takes precedence; Hyprland requires a Wayland session and available helper. |
| Desktop identification assumed XDG_CURRENT_DESKTOP always contained KDE | Fall back to XDG_SESSION_DESKTOP, including plasma, and use the same detection in reporting and observer startup. |
| Wayland Qt startup depended entirely on distro defaults | Prefer the native Wayland plugin, with XCB fallback when available. Explicit user overrides are preserved. Xwayland rendering does not authorize a native pointer warp. |
| Screen-sharing support was mistaken for pointer-control support | Read RemoteDesktop and ScreenCast capability properties before creating a permission session. The optional UI/doctor probe never requests permission. |
| Users could not tell distro/runtime limitations from device permissions | Add a read-only compatibility panel, structured doctor report and a feature/distro matrix. |
| The launcher blindly used an older python3 | Search supported installed interpreters; honor AUTOMATER_PYTHON; retain unsupported existing virtual environments with repair guidance. |
| Qt wheel ABI differences appeared as generic pip/import failures | Check fresh-install architecture/libc floors from the pinned wheel release. Preserve already installed native builds. |
| Empty/relative XDG_CONFIG_HOME wrote configuration into the working directory | Follow XDG semantics: use the normal home config directory unless the override is absolute. |
| Only Ubuntu offscreen rendering had CI coverage | Add Ubuntu 22.04/24.04 matrices, Debian/Fedora installation smoke checks and private native XCB/Weston GUI launches. |

The core evdev/uinput path is desktop-independent when devices/permissions are
available. Native Wayland window discovery and portal geometry remain backend
capabilities; they are not universal. See [COMPATIBILITY](COMPATIBILITY.md).
| Save prompt and unsaved badge did not match the workspace | Custom save dialog with explicit choices and safe cancellation; badge beside the title summary, with long summaries elided instead of wrapping. |
| Selected foreground apps stopped immediately when unfocused | Restore/focus the chosen window after countdown, before input, with an opt-out. Identity/focus checks and cleanup remain active. Background input still requires a supported background route. |
| Empty properties retained a stale action caption | Clear the caption and close action properties on explicit deselection. |

Real game acceptance and compositor-specific activation policy still require a
physical desktop check. No real user window was activated by automated tests.
