# Using Moonlight Studio

## Start with the example

Run `./start.sh --demo`. The example holds W, waits, then taps E. **Test mode** is
already enabled. Click **Run workflow** to watch the sequence without sending input.

![Workflow workspace](editor.png)

The top navigation opens Workflow, Events, Library and Devices. Your current workflow
name is editable in the header. Save is at the top; File contains New, Open, Save as and the example. Record and Run
stay at the bottom. Pause and Stop appear during active work. The indicator shows recording, running, paused
or ready, and the line below explains what is happening.

## Build and edit

Click **Add action** to choose Keyboard press, Mouse click, Wait, Move pointer, or
Scroll. An action is inserted after your selection, or appended if none is selected.
The plus button on a connector inserts directly at that location.

Properties are hidden until needed. Click a card to select it; the close button
in the inspector gives the space back to the canvas. **Action** on the right shows its properties:

- **Key / button:** Choose the physical key or mouse button. A hold edits its press
  and release together.
- **Delay before:** Time to wait before beginning the action. This is separate from
  the time the key stays held.
- **Hold for:** Duration between press and release.
- **Wait for:** Duration of a standalone wait action.
- **Horizontal / Vertical:** Relative movement, or scroll notches, for a single sample.
- **Include in playback:** Disabled actions are visibly faded and their delays are skipped.

Click **Apply changes** to commit. Undo restores the previous event data. The four
buttons below Apply move left, move right, duplicate, and delete. The same actions
are in a card's right-click menu. Drag a card past a neighboring slot to reorder;
the whole action moves, including its press and release. There are no free-floating
positions to save: execution always follows the connected left-to-right order.

### Grouped paths and precise events

Matching adjacent press/release pairs are represented as one hold/click card. A key
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

Mouse wheel pans horizontally. Drag empty canvas space to pan in either direction.
Ctrl + wheel zooms; the bottom controls zoom in/out or fit. Zoom is bounded so a
long sequence does not turn into unreadable dots. Workflows over 60 actions are
paged. Previous and Next move through those pages. Playback follows the active
page automatically. The underlying event list remains complete.

## Set up playback

Click **Settings**, or select **Run** in the inspector.

![Run settings](run-settings.png)

| Setting | Effect |
| --- | --- |
| Active desktop | Send through uinput to the active desktop. Focus the intended app during the countdown. |
| Background window · X11 | Select a concrete X11/Xwayland window. This experimental mode sends window events without changing focus. |
| Speed | Scale event delays from 0.1× to 10×. |
| Repeat | Number of complete cycles; zero displays “Until stopped.” |
| Start delay | Time to switch to your destination before playback or recording starts. |
| Loop gap | Pause between cycles; the engine uses a minimum 10 ms gap. |
| Test mode | Highlight the real replay sequence without emitting input. |

The estimate includes enabled events, speed, countdown, repetitions and loop gaps.
Desktop replay allows at least 0.5 s for its new virtual device to register.
It excludes time spent paused and cannot predict operating-system or game latency.
Pause releases held inputs and resume restores them. Stop interrupts a wait and
releases held inputs. Editing is locked during playback and recording; you can
still switch between Workflow and Events to watch progress.

Background compatibility remains application-specific. Native Wayland background
delivery is unavailable. See the [platform matrix](../README.md#background-compatibility).

## Record from your devices

![Guided setup](setup.png)

Open Devices, check input access, select devices, and click Apply selection.
Choose keyboard, buttons/wheel and/or movement. The permissions link explains
missing device access. If your original Moonlight clicker works, the same access
may already be available.

Press F6. After the countdown, do your routine and press F6 again. By default the result
replaces the current event sequence; Undo restores it. Enable **Append to current
workflow** in Devices to add to existing actions instead. F12 also finishes capture
or cancels a countdown. Control hotkeys never enter the recording. Capture in
progress stays in memory until stopped; stopping hands it to the editor and autosave.
After reconnecting a device, refresh the device list. Selection is remembered using
the device metadata, so changes to event-node numbers do not select an unrelated
input. Recommended resets the selection to discovered keyboards and mice. If
only a mouse is selected, global keyboard shortcuts will not work.

## Save and recover

**Save** saves to the current file, or asks for a destination on first
save. The default is your library. **File → Save as** writes a separate copy. Library
search filters by filename; double-click a result to open it. Import opens an
existing JSON script. Existing v0.1 files use the same version-1 data schema.

**Notes** stores starting position, camera direction, bindings and reminders.
An unsaved-change badge appears in the header. Idle edits are autosaved every five
seconds; startup offers recovery after an interrupted session. Saved workflows
are never silently replaced by recovery. New/open/close prompt before discarding
unsaved work. See [storage and privacy](../README.md#files-and-privacy).

## Common questions

**Why does recording say setup is needed?** Studio needs access to physical devices.
Use Devices → Input access help. Test mode and editing work without those permissions.

**Why does a key appear as a press and a release instead of one card?** Other events
occur between them, or their enabled states differ. Keeping them separate preserves
the original order and simultaneous holds.

**Can I add branches or nested loops?** This release visualizes a linear macro.
Repeat the complete sequence in Settings → Run. Conditional branches and nested loops
are planned separately; drawing a connection does not create unsupported logic.

**Why did my mouse path land elsewhere?** Movement is relative, so starting position,
camera sensitivity, acceleration and game bindings matter. Put those assumptions
in Notes. This release does not record absolute screen positions.

**Will a game accept background input?** Test it on that game. Desktop uinput and
directed X11 window messages have different compatibility. The test receiver proves
message delivery, not acceptance by any particular game.

## Remembered settings

Run speed, repeats, start delay, loop gap, capture filters, append mode and Test
mode are remembered across restarts. They are app preferences, separate from the
portable macro file. Background window handles are intentionally not restored;
choose a live window each time. Corrupt preferences fall back to defaults with
a short message; Technical details contains the underlying error.
