# Running workflows from the command line

You can run a saved workflow without opening the editor. The process exits when
it finishes; there is no resident service to keep running.

## Install the command

Run `./install.sh`, including when updating an existing installation. It adds
`~/.local/bin/automater`. If that directory is not on your PATH, use the full path
or add it to your shell's PATH. `AUTOMATER_BIN_DIR` can choose a different absolute
directory when running the installer.

A wheel installation also includes the `automater` command in its Python environment.
You can use `.venv/bin/automater` directly from a checkout.

## Run a workflow

```bash
automater run "/path/to/workflow.json"
```

This runs once at speed 1×, sending input to your active desktop. Focus the app you
want to control. The command does not bring a window forward or use background X11
or Gamescope mode. Run it as your regular user, without sudo.

There is no extra countdown by default. The virtual input device still needs
about half a second to register before input can begin. Add `--countdown 3` if you
need time to switch windows. Playback options start from CLI defaults; they do not
read the editor's Run settings.

To check timing without sending input:

```bash
automater run "/path/to/workflow.json" --test
```

Test mode needs no input permissions or graphical display. It checks the saved
workflow and runs its timing, but does not verify that a game will accept input.
CLI runs do not change the workflow file or editor preferences.

| Option | Meaning |
| --- | --- |
| `--test` | Run without sending input. |
| `--speed 1.5` | Change playback speed; range 0.1–10. |
| `--repeat 3` | Run three times; 0 repeats until stopped. Default: 1. |
| `--countdown 3` | Lead-in before playback, in seconds; range 0–30. Default: 0. |
| `--loop-gap 0.5` | Seconds between repetitions; range 0–3600. Default: 0.25. |
| `--no-start-position` | Skip the cursor reset saved in the workflow. |
| `--quiet` | Hide normal progress messages; errors and warnings still print. |

Relative workflow paths are resolved from your current directory. Quote paths
containing spaces. Use `automater run --help` for the available options.

## Use a desktop keybind

Save your workflow in the editor, then add a custom command shortcut in your
desktop's keyboard settings. For example, replacing the username and filename:

```text
/home/you/.local/bin/automater run "/home/you/.config/automater/scripts/My workflow.json" --countdown 1
```

Use absolute paths: a desktop shortcut may start in a different directory and may
not expand `$HOME` or `~`. A short countdown gives you time to release the shortcut
keys before playback begins.

Add a second shortcut to stop it:

```text
/home/you/.local/bin/automater stop
```

The editor does not need to be open. The CLI does not install the editor's global
F-key controls; use your stop shortcut, `automater stop`, or Ctrl+C in a terminal.

## Stop and check status

```bash
automater stop
automater status
automater status --json
```

Stop interrupts waits, releases held inputs and closes the virtual input device.
Ctrl+C, SIGTERM and SIGHUP also stop cleanly. A second CLI run is rejected while
one is active, so pressing your launch shortcut twice does not overlap workflows.

These commands control CLI runs only, not playback started in the editor. With
no CLI run active, stop succeeds and status reports that nothing is running.
JSON status contains `running`, `pid`, `workflow`, `test_mode`, `phase`, `loop` and
`completed_events`. When idle, it returns `{"running": false}`.

The run command returns 0 on completion, 1 for a workflow or playback error, 2 for
invalid command syntax, and 3 if another CLI workflow is running. Cancellation
returns 130, or 128 plus the signal number when interrupted by a signal. The stop
command itself returns 0 after the runner has released its inputs.

## Wayland cursor reset

Relative keyboard and mouse playback uses the input permissions set up by the
installer. Absolute cursor reset can also require a desktop portal on Wayland.
The CLI connects when a workflow has a saved desktop starting point. The desktop
may show an approval dialog; it cannot be approved by the installer.

You can set up approval before using a keybind:

```bash
automater pointer setup
```

Approve pointer control and select physical monitors when asked. With Remote
Desktop portal version 2, Automater asks to remember approval and saves the
returned restore token. The editor and CLI share it. Your desktop decides whether
it can reuse that approval; older portals, revoked access or changed monitors may
require another prompt. Automater does not open the screen streams or read frames.

The token is stored privately in `~/.config/automater/portal-pointer.json`, or
under `$XDG_CONFIG_HOME` if set. It is never included in workflow JSON files.
To forget the saved approval:

```bash
automater pointer forget
```

This removes Automater's saved token. It does not end sessions already open in the
editor; use your desktop's permission settings to revoke access there.

X11 and Hyprland use their existing cursor-positioning methods. A saved
window-relative starting point cannot be used for CLI desktop playback. Use
`--no-start-position` to run only the recorded inputs instead.

See [Linux compatibility](COMPATIBILITY.md) if pointer control is unavailable, and
[installation](INSTALL.md#input-permissions) for input-device permissions.
