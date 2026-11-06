# Using Automater

## Build your first workflow

The first launch offers a full guided example. Choose **Start example** to open
its own workflow tab; your existing work stays intact. Follow five steps to build
**Hold Space for 500 ms → Timer for 300 ms → Hold E for 100 ms**.

Each step points to the real controls. The instruction also appears inside the
Add action dialog. **Next** becomes available when the current task is done;
**Back** lets you review a step. **Skip** or Escape ends the guide. An empty
example tab is removed; work you have started is kept.

![Guided example beside the real action properties](tutorial.png)

The last step runs the complete example in **Test mode**, without sending input.
A successful run opens the congratulations screen. Stopped or failed previews
stay on the Run step so you can try again. **Create my own** opens a new blank
workflow and keeps your example as a reference; **Keep editing** stays in the
example. You can save it with the usual Save button.

![Successful example and congratulations](tutorial-complete.png)

Reopen the guide from **File → Guided example**, or **Build your first workflow**
on an empty canvas. Recording is available after you finish or skip the guide.

## Start with the example

Run `./start.sh --demo`. The example holds W, waits, then taps E. **Test mode** is
already enabled. Click **Run** to watch the sequence without sending input.

![Workflow workspace](editor.png)

The top navigation opens Workflow, Events, Library and Devices. Your current workflow
name is editable in the header. Save is at the top; File contains New, Open, Save as and the example. Record and Run
stay at the bottom. Pause and Stop appear during active work. The indicator shows recording, running, paused
or ready, and the line below explains what is happening.

## Build and edit

Click **Add action** to choose Hold, Mouse click, Timer, Move pointer, Scroll,
Press or Release. Search any supported keyboard key or mouse button, then set the
timing in the dialog. An action is inserted after your selection, or appended if none is selected.
The plus button on a connector inserts directly at that location.

Properties are hidden until needed. Click a card to select it; the close button
in the inspector gives the space back to the canvas. **Action** on the right shows its properties:

- **Key or button:** Choose the physical key or mouse button. A hold edits its press
  and release together.
- **Delay before:** Time to wait before beginning the action. This is separate from
  the time the key stays held.
- **Hold for:** Duration between press and release.
- **Wait for:** Duration of a standalone wait action.
- **Horizontal / Vertical:** Relative movement, or scroll notches, for a single sample.
- **Enabled:** Disabled actions are visibly faded and their delays are skipped.

The key picker shows friendly names; enter a key name to search. Timing fields
show only meaningful decimals and keep fractional milliseconds. **More options**
contains Enabled, random timing, pointer-path preview and Re-record.

![Action properties with key and timing controls](action-properties.png)

Click **Apply changes** to commit. Undo restores the previous event data. The four
buttons below Apply move left, move right, duplicate, and delete. The same actions
are in a card's right-click menu. Drag a card past a neighboring slot to reorder;
the whole action moves, including its press and release. There are no free-floating
positions to save: execution always follows the connected left-to-right order.

### Grouped paths and precise events

Matching adjacent press/release pairs are represented as one hold/click card. Explicit Press and Release controls remain separate cards. A key
pressed while another is held remains an individual press or release card, so the
workflow does not hide overlapping inputs. Grouping respects enabled boundaries.

Consecutive pointer movement or scroll samples become a single card. This does
not simplify or delete samples. **Path duration** scales the delays after its first
sample proportionally; **Delay before** changes only its first delay. If the internal
duration was zero, a new duration is distributed equally over the remaining samples.
Edits that would exceed an individual event's timing limits are rejected.

Use **Events** to edit individual samples or keys. Select multiple rows to duplicate,
delete or move them as a consecutive group. Disabling individual press/release
events can create unbalanced holds; the existing replay warning and cleanup apply.

![Precise event editor](events.png)

### Explore a long routine

Mouse wheel pans horizontally. Left-drag empty canvas space to box-select; middle-drag pans in either direction.
Ctrl + wheel zooms; the bottom controls zoom in/out or fit. Zoom is bounded so a
long sequence does not turn into unreadable dots. All actions live on one continuous
canvas; scroll to reach any action. Large routines create graphics only near the
visible area, keeping every event and selection intact. **Follow playback** smoothly
moves the camera toward the running action; turn it off to inspect another area.

When dragging, a dashed marker shows the original position. A translucent card and
shifted neighbours preview the new order. Hover near an edge to scroll farther.
Release to commit one undoable move, or press Escape to cancel.

## Set up playback

Click **Settings**, or select **Run** in the inspector.

![Run settings](run-settings.png)

| Setting | Effect |
| --- | --- |
| Active desktop | Send through uinput to the active desktop. Focus the intended app during the countdown. |
| Background window · X11 | Select a concrete X11/Xwayland window. This experimental mode sends window events without changing focus. |
| Speed | Scale event delays from 0.1× to 10×. |
| Repeat | Number of complete cycles; zero displays “Until stopped.” |
| Start tab → Countdown | Time to switch to your destination before playback or recording starts. |
| Loop gap | Pause between cycles; the engine uses a minimum 10 ms gap. |
| Test mode | Highlight the real replay sequence without emitting input. |

Click **Choose open window** to search your currently open games and applications;
there is no file browser. On KDE Plasma this includes native Wayland windows.
Other desktops currently expose X11/Xwayland windows only. Refresh after opening
an app. A closed selected desktop window remains marked unavailable until you
choose another window; it does not silently become unrestricted desktop playback.

For **Active desktop**, **Focus selected window on start** restores
and focuses your chosen app after the countdown. Turn it off if you prefer to
focus the app yourself. After starting, switching away stops the script and releases
held inputs. This still moves your normal
pointer. Use **Use any active window** in the picker to remove that focus check.
**Background window · X11** sends best-effort background messages. For a native
Wayland window, the picker explicitly offers **Use on active desktop** instead.
**Separate game session** lists only windows inside the game display you launched;
use that advanced mode for independent mouse/keyboard input in supported games.

![Search currently open apps](window-picker.png)

The estimate includes enabled events, speed, countdown, repetitions and loop gaps.
Desktop replay allows at least 0.5 s for its new virtual device to register.
It excludes time spent paused and cannot predict operating-system or game latency.
Pause releases held inputs and resume restores them. Stop interrupts a wait and
releases held inputs. Editing is locked during playback and recording; you can
still switch between Workflow and Events to watch progress.

Background compatibility remains application-specific. Native Wayland background
delivery is unavailable. See the [platform matrix](COMPATIBILITY.md#desktop-and-display-server-features).

## Record from your devices

![Guided setup](setup.png)

Open Devices, check input access, select devices, and click Apply selection.
Choose keyboard, buttons/wheel and/or movement. The permissions link explains
missing device access. If your original Moonlight clicker works, the same access
may already be available.

Use **Record** (or **Record more** when adding to a routine), or press F6. After the countdown, do your routine and press F6 again. By default the result
appends to the existing workflow. To replace a part, select one action or adjacent
actions and choose **Re-record**. Discard keeps the original; Undo restores it after
finishing. Empty recordings keep existing actions. Disable **Add recording to current
workflow** in Devices for a confirmed replacement of all actions. F12 also finishes capture
or cancels a countdown. Control hotkeys never enter the recording. Capture in
progress stays in memory until stopped; stopping hands it to the editor and autosave.
After reconnecting a device, refresh the device list. Selection is remembered using
the device metadata, so changes to event-node numbers do not select an unrelated
input. Recommended resets the selection to discovered keyboards and mice. If
only a mouse is selected, global keyboard shortcuts will not work.

## Save and recover

**Save** saves to the current file, or asks for a destination on first
save. The default is your library. **File → Save as** writes a separate copy. Library searches filenames and workflow titles; double-click a result to open it.
It indexes known save locations and recently opened files, including older workflows
saved beside the launcher. **Add folder…** includes another directory, and Refresh
picks up files added outside Automater. Only valid workflow JSON appears; preferences
and recovery files stay out of the list. Import opens an
existing JSON script. Existing version-1 files remain readable. Advanced controls, timing ranges and
starting points use version 2 when saved; they require Automater v0.4 or newer.
Named groups use version 3; group explanations use version 4 and require v0.9 or
newer. Existing files are not rewritten when Library indexes them or converts
older inline note cards for display. Save explicitly to persist the conversion.

**Group notes** let you describe a starting position, camera direction, bindings
and reminders for a section. These are written reminders; they do not configure
playback. Use **Settings → Start** to set an actual cursor reset.
An unsaved-change badge appears in the header. Idle edits are autosaved every five
seconds; startup offers recovery after an interrupted session. Saved workflows
are never silently replaced by recovery. Closing a changed tab or quitting prompts before discarding
unsaved work. See [storage and privacy](../README.md#files-and-privacy).

## Common questions

**Why does recording say setup is needed?** Automater needs access to physical devices.
Use Devices → Input access help. Test mode and editing work without those permissions.

**Why does a key appear as a press and a release instead of one card?** Other events
occur between them, or their enabled states differ. Keeping them separate preserves
the original order and simultaneous holds.

**Can I add branches or nested loops?** This release visualizes a linear macro.
Repeat the complete sequence in Settings → Run. Conditional branches and nested loops
are planned separately; drawing a connection does not create unsupported logic.

**Why did my mouse path land elsewhere?** Movement is relative, so starting position,
camera sensitivity, acceleration and game bindings matter. Put those assumptions
in group notes. This release does not record absolute screen positions.

**Will a game accept background input?** Test it on that game. Desktop uinput and
directed X11 window messages have different compatibility. The test receiver proves
message delivery, not acceptance by any particular game.

## Remembered settings

Run speed, repeats, start delay, loop gap, capture filters, append mode and Test
mode are remembered across restarts. They are app preferences, separate from the
portable macro file. Background window handles are intentionally not restored;
choose a live window each time. Corrupt preferences fall back to defaults with
a short message; Technical details contains the underlying error.

## Press, hold, release and timers

**Press** sends key-down only. Use a **Timer** while it stays down, then **Release**
that same key. **Hold** contains a press and timed release together. A mouse button
can be used with these controls too. Every loop and Stop releases outstanding holds.
For example: Press W → Timer 500 ms → Release W → Hold Space for 100 ms.

In properties, **Delay before** is a minimum when Random delay is enabled; **Up to**
is the maximum. Hold/path durations have their own random range. A new value is
sampled for each ranged event each loop, then divided by playback speed. Random
choices never change the saved minimum/maximum or shuffle action order.

Select actions and choose **Edit → Randomize selected timing** for percentage
variation. Zero delays remain zero unless you give them an explicit range. The
context menu's **Use fixed timing** removes ranges and keeps their minimum values.
**Split holds into press / release** preserves both events while showing separate cards.

## Selection and clipboard

Ctrl-click toggles a card. Shift-click selects a range. Left-drag from empty canvas
box-selects; middle-drag pans. Ctrl+A selects every action, including those offscreen.
Scrolling keeps your selection. Copy/cut/paste and duplicate act in original sequence order;
paste inserts after the last selected event, or at the end if nothing is selected.
Clipboard data is bounded, validated JSON and includes all original samples/ranges.
It does not include the workflow's starting-point configuration.

Ctrl+C copies, Ctrl+X cuts, Ctrl+V pastes, Ctrl+D duplicates, and Delete/Backspace
removes the selection. Ctrl+Z undoes, Ctrl+Shift+Z redoes, Esc clears selection.
Text boxes retain normal text-editing shortcuts. The Events view keeps precise raw
row selection even when the workflow view groups a press/release pair. F1 shows help.

Choose Horizontal, Vertical or Grid below the canvas. Layout is visual only;
numbered action order controls execution. Alt+arrows moves selected actions as a
group. Changing layout, zooming or selecting actions never changes macro timing.

## Start countdown and loop reset

Open **Settings → Start**, or click the Start marker. The initial countdown gives
you time to switch windows; the large countdown banner has a Cancel button and F12
always stops. Add a Timer action if you also need a delay inside each loop.

Enable the starting point and set X/Y plus settle time. The cursor moves first on
**every loop**, waits the settle interval, then begins the actions. Pick position
waits three seconds and reads the cursor without moving it. F12 cancels capture;
a late result from a cancelled pick is ignored.

Coordinates are saved with the script. X11 and Hyprland support direct positioning.
On KDE or another Wayland desktop, use **Connect Wayland pointer**, approve pointer
control and select physical monitors. This requires a compatible desktop portal.
The connection is temporary and closes with Automater. No screen frames are read or saved.
Use **Choose on screen** to click a location, and **Show starting point** to check it.
A portal acknowledgment is not a guarantee that a game accepted the move. Background
coordinates are relative to the selected X11 window's client area and do not move
or capture the real pointer. The target must still be chosen each session. Switching
to another workflow restores its saved starting point or turns reset off if it has none.

| Destination | Starting-point coordinates |
| --- | --- |
| X11 active desktop | Root-window screen pixels. |
| Hyprland active desktop | Global logical pixels, including negative monitor positions. |
| Wayland pointer portal | Approved physical-monitor logical coordinates; monitor metadata is required. |
| Background X11 or separate game session | Selected window's client-area pixels; your real cursor stays independent. |
| Test mode | Simulation only; no pointer moves. |

Portal denial, cancellation, revocation or connection loss stops/rejects positioning.
Relative replay remains available with reset disabled, provided device access works.
A cursor reset does not reset your character, camera or game state.

![Start controls](start-controls.png)


## Edit matching actions together

Select matching Holds, Presses, Releases, Timers, Moves or Scrolls. The Action panel
shows **Apply to N actions**. Different values show Mixed or Multiple keys. Change
only the fields you want copied, then Apply. Untouched keys, coordinates, durations
and timing ranges stay as they are. One undo restores the whole batch. Holds and
standalone Press/Release controls are different types. Mixed action types retain
copy/delete/randomize; select matching types for shared properties.

![Batch properties](batch-edit.png)

## Pointer path guides

Select a movement card and choose **Show pointer path** in its properties or the
context menu. The guide marks start/end and disappears after four seconds. It is
click-through and sends no input. If the script has no starting point, click a
preview origin first. Esc/F12 or right-click cancels a point picker. The point is
chosen on mouse release so the selection click is not passed to another app.

Recorded movement is relative device counts. Desktop scaling, acceleration and game
sensitivity affect the actual path, so this guide is approximate. It is not screen
matching or a prediction of a game's camera. Background coordinates are window-local;
desktop overlays are unavailable for that routing mode.

![Temporary pointer path guide](pointer-guide.png)

## Playback runs but the mouse does not move

Check the visible **Test mode** line first. Test mode intentionally emits nothing;
click **Use real inputs** to leave preview mode. In background mode the real cursor
stays where it is. For desktop reset on KDE Wayland, connect pointer control in
Start settings first. A permission or input-device error is shown in the status bar;
hover it for the full message. See [starting-point setup](#start-countdown-and-loop-reset).


## Multiple workflows

Use + or Ctrl+T for a workflow tab. Opening a file or example creates another tab;
opening a file already loaded activates its tab and preserves unsaved changes.
Tabs have independent undo/redo, selected actions, layout/zoom, starting coordinates,
run settings and recovery files. * means unsaved. Ctrl+W closes the active tab;
Ctrl+Tab and Ctrl+Shift+Tab switch. Closing the last tab leaves a blank workflow.
Tabs are locked during recording/playback so feedback and new captures stay with
one document. Saving cannot overwrite a file open in a different tab.

## Run independently while using another window

This mode launches a new game display with independent input. It requires Gamescope,
a compatible Vulkan driver/GPU and an X11-capable game. An already running game
cannot be moved into the session.

1. Close any existing Sober instance yourself. Automater refuses to launch a second
   instance that might reuse your ordinary desktop window.
2. Choose **Settings → Run → Separate game session · Gamescope**, then
   **Set up game session…**.
3. Choose **Sober · Flatpak**, set the resolution, and click **Launch game in session**.
   Automater does not install Gamescope or change persistent Flatpak permissions.
4. Select the game window in Run settings. Only windows inside that session appear;
   a sole window is selected automatically.
5. Turn Test mode off and run a short routine. You can use another desktop or window
   while it runs. Stop releases held inputs inside the game session.

![Separate game setup](isolated-session.png)

For another app, choose Custom application and enter its executable and arguments.
Arguments are passed directly, without shell expansion. Close existing single-instance
apps first; the destination must open inside the new session.

Starting X/Y coordinates refer to the game client area. This transport does not use
your desktop pointer permission or `/dev/uinput`; physical recording and global
hotkeys still need readable input devices. It never falls back to desktop injection
if startup, targeting or input fails. Existing native Wayland windows cannot receive
independent background input through this mode.

Closing Automater stops automation and leaves the launched game open. **Close game
session** asks before closing it because game progress could be lost. Use **Session
diagnostics** for startup logs. A missing Vulkan device requires working GPU/driver
access. Game sensitivity, pointer grabs and frame handling still affect replay;
physical Gamescope/Sober compatibility needs testing on your machine.

## Understand playback and its last result

The countdown uses the replay worker's monotonic deadline. Input checks and target
setup happen before that countdown. Delay, Timer, cursor reset/settle, pause and
loop gap have distinct states. Held keys and a Timer can be active together. A
future key press is not highlighted until it is dispatched. The UI shows the
latest worker snapshot about 30 times per second, rather than replaying a queue of
old highlights. Input scheduling is independent of the UI timer.

After Finish, Stop or failure, the latest loop's results remain:

- **Green:** the action completed.
- **Blue:** the last completed action.
- **Amber:** the action in progress when stopped.
- **Red:** the step that failed or could not continue.

Unexecuted actions remain neutral. For grouped movement/holds, all enabled samples
must finish before the card is marked completed. **Edit → Last playback details**
shows completed events, failure, requested/actual loop time and maximum measured
dispatch lateness. These measurements cannot confirm receipt by the game. Details
exclude countdown/reset/gap and paused time from actual loop duration. Edits or a
new run clear old markers; switching tabs preserves each tab's latest result.

![Last run markers](run-results.png)

## When recording and playback differ

Use speed **1×**, fixed timings, the same game bindings/sensitivity and a consistent
starting position/camera. Relative mouse counts are preserved; desktop acceleration,
scaling, a virtual mouse's settings and the game's input/frame handling can change
the visible path. A starting cursor coordinate does not reset a game's camera or
character state. Start with a short harmless routine and inspect **Edit → Last
playback details** for missed deadlines or a failed action.

Replay maintains the recorded cumulative schedule and protects hold/release
intervals against late sends. Recording uses kernel timestamps across ready devices
and accepts events at the actual countdown deadline even if the UI is busy. These
fixes reduce internal drift; they cannot confirm that a game accepted every event.
New recordings benefit from capture fixes; existing JSON timings are kept unchanged.

Saved tab labels use the filename without `.json`. Open and Save As start in the
active file's folder, otherwise the last used folder, otherwise the workflow library.
The editable workflow title inside a JSON file remains independent of its filename.

## Add explanations and visual categories

Select cards with Ctrl-click, Shift-click or a left-drag selection box. Click
**Group**, press **Ctrl+G**, or choose Group selection in the context menu. Give
the section a name, color and optional explanation. One translucent rectangle
surrounds all its members, including across grid rows. For a nonadjacent selection,
the rectangle can enclose other cards; only the selected cards belong to the group.
Grouping never reorders actions, changes timing or adds execution logic.

Click the rectangle's background or heading to select its members and open the
**Group** panel. Edit its name, color or plain-text notes (up to 20,000 characters).
Changes apply to the document after a short pause; **Apply notes** applies
immediately. Save the workflow to write them to its JSON file. **Ctrl+Shift+N**
opens notes for the selected group, or creates a group for ungrouped actions.
Dragging across a rectangle still box-selects actions; middle-drag still pans.

Right-click the rectangle for Open group notes, Select group actions and Remove
group. **Ctrl+Shift+G** removes selected actions from their groups. Group changes
and note edits are undoable; copy/paste between tabs copies their metadata and
creates independent identities. Editing names, colors or notes preserves last-run
highlights. Editing executable input clears those results.

Standalone note cards are no longer offered. Older cards convert to nearby group
notes on opening without changing recorded input timing/order. A file containing
only notes retains them as an imported workflow description in the Group panel.

![Group rectangles and their notes](group-notes.png)

## Live capture preview

During recording, a preview above the editor shows the most recent actions, total
captured events, elapsed time and currently held inputs. The original workflow stays
intact until you finish. **F6** adds the captured events using the append/re-record
mode you chose; **Discard** keeps the previous workflow. In-progress capture remains
in memory, so finish the recording before closing Automater.

![Live recording preview](recording-preview.png)

## Manage tabs and unsaved changes

Click **+** beside the tabs, or press **Ctrl+T**, for a new workflow.
Right-click a tab for Rename, Save, Save as, Close workflow and Close other workflows.
Double-click a tab to rename it. Renaming a saved workflow moves its JSON file within
the same folder, refuses an existing destination, and keeps unsaved edits in memory.
The updated internal workflow title is persisted when you Save. Closing a tab does
not delete its saved JSON file.

The unsaved badge sits beside the summary below the workflow title. Closing changed
work opens Automater's save dialog: **Save workflow** writes your changes, **Discard
changes** keeps the last saved file, and **Keep editing** or Escape cancels closing.
Cancelling the file chooser during Save also leaves the tab open.

![Save, discard or keep editing](save-changes.png)

## Wide screens and smooth following

Grid columns follow the visible width, current zoom and properties panel. The
layout reflows after a pointer gesture finishes, keeping dragging and box selection
stable while properties open. Selection and raw input data do not change.

Playback uses a continuously updated camera with retained velocity when targets
change and clamped motion at scroll limits. It follows the newest dispatched input
while older held inputs keep their own highlights. It stays separate from replay
timing. Turn **Follow playback** off to pan
freely, then turn it on to return to the current action. Shorter-than-frame inputs
are represented by the latest worker snapshot; the UI cannot display every physical
event as a separate rendered frame.

## Appearance and the quick guide

![Theme gallery](themes.png)

![Daylight workflow](daylight.png)

Open **File → Appearance & themes**, or press **Ctrl+,**. The gallery includes Automater plus Moonlight, Obsidian, Crimson,
Dracula, Viper, Nord, Sakura, Solaris, Catppuccin and Daylight. Click a card to apply
it; accent and background color pickers add local overrides. Choosing another
gallery card clears the overrides. Reset to Automater restores the original look.

Theme changes preserve actions, input timing, selection, notes, Undo and last-run
results. Appearance is stored in Preferences, not exported JSON workflows. Group
colors remain portable; labels are adjusted for contrast. Custom backgrounds
automatically choose readable text colors. Stop capture/playback before changing
appearance; the gallery is disabled during active work.

**File → Getting started** and **Quick guide** on the empty canvas explain action
creation, Hold/Press/Release, selection, duplication, groups, playback destinations
and saving without requiring a browser. Ctrl+Z inside a text field uses its native
text history; on the canvas it undoes workflow edits. Toolbar Undo/Redo apply to
the document. Applying notes changes the document; Ctrl+S saves the JSON file.

## Linux compatibility

**Devices → Check compatibility** and **File → Linux compatibility** explain the
detected distro, desktop, display server, pointer method and input requirements.
Use **Check pointer portal** to read capability properties without requesting
permission. Connect Wayland pointer remains the separate approval step.

Core recording and desktop replay use Linux input devices on X11 and Wayland.
Window discovery, absolute reset and background modes have different requirements.
On a Wayland desktop that does not expose native windows, choose **Any active
window**, then focus the game during the countdown. This mode cannot guard focus
of an app the desktop does not expose. See the [matrix](COMPATIBILITY.md).

Connections follow the same worker snapshot: completed inputs leave colored
arrows, and a moving stream points toward the current action or next waiting input.
Pause and Stop freeze that stream. Shorter-than-frame transitions can be skipped
visually while their final completion colors remain visible.
