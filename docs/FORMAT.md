# Script formats v1–v4

Files use UTF-8 JSON and include `version` and a `steps` array. Existing v1 scripts
remain compatible. Advanced controls save as v2 and require Studio v0.4 or newer.

```json
{
  "version": 1,
  "name": "Walk forward",
  "notes": "Start at the same position each time.",
  "steps": [
    {"delay_ms": 0, "action": "key_down", "code": "KEY_W"},
    {"delay_ms": 650, "action": "key_up", "code": "KEY_W"},
    {"delay_ms": 200, "action": "wait"}
  ]
}
```

Each step accepts only these fields:

| Field | Default | Meaning |
| --- | --- | --- |
| `delay_ms` | 100 | Milliseconds before this action; 0–3,600,000; finite number |
| `action` | `wait` | `key_down`, `key_up`, `move`, `scroll`, or `wait` |
| `code` | empty string | Supported Linux `KEY_*` or mouse `BTN_*` name; required for key actions |
| `x` | 0 | Signed integer relative X or horizontal scroll; −32,767 to 32,767 |
| `y` | 0 | Signed integer relative Y or vertical scroll; −32,767 to 32,767 |
| `enabled` | true | Boolean; disabled steps and their delays are skipped |

`move` and `scroll` ignore `code`; `wait` only consumes its delay; key actions ignore
X/Y. The editor exports every field. Name defaults to “Untitled script” and must
contain 1–120 characters; notes default to empty and have a 20,000-character limit.
Unknown fields/versions, booleans in numeric fields, NaN/infinity, oversized scripts,
and unsupported codes are rejected. A file can contain up to 200,000 steps and 32 MiB.

Delay and repeat settings are chosen in the UI at playback time. Speed scales step
delays, but not countdown or loop gap. The engine uses at least a 10 ms loop gap to
avoid spinning on a zero-duration repeating script. Missing releases at the end of
a loop are automatically added by playback cleanup; the editor warns before real
playback of an unbalanced sequence. An explicit `wait` after a held key makes a
hold; a `key_down` step alone is released at that loop's end.

## Version 2 additions

Steps may include `delay_max_ms` (null for fixed timing, otherwise a finite number
between `delay_ms` and 3,600,000). Playback samples uniformly between minimum and
maximum for each enabled event on every loop, then applies speed. The saved events
are never mutated. `standalone: true` keeps a manually inserted Press, Release,
Timer, Move or Scroll as its own workflow card instead of grouping it with adjacent
events. Both fields default to their v1 behavior when omitted.

The key list includes Linux `KEY_*` codes, including function, media and macro
keys. Mouse buttons use the supported `BTN_*` codes shown in the key picker.
Kernel constants and unrelated gamepad codes are rejected.

The optional top-level `start` object has exactly these fields:

```json
{"x": 420, "y": 260, "settle_ms": 150, "space": "desktop"}
```

`x` and `y` are signed integers from −32,768 to 32,767. `settle_ms` is a finite
number from 0 to 10,000. `space` is `desktop` or `window`; playback rejects a
mismatch with the selected backend. The backend also checks its actual bounds.
Omitting `start` disables coordinate reset. Target window handles are never saved.
The initial countdown runs once; positioning and settle delay run before every
loop, with releases at each loop boundary. Test mode does not move any pointer.

Plain scripts continue saving as v1; ranges, standalone controls, extended keys or
starting coordinates trigger v2. Explicitly loaded v2 files retain their version.

## Versions 3 and 4: visual groups and explanations

Version 3 adds an optional top-level `groups` object. Each key is a group identity
(1–64 characters); metadata contains a `name` (1–120 characters) and `color`
(`#RRGGBB`). Steps reference their category with `group_id`; unused definitions
are pruned when editing. Groups never change input order or timing.

Version 4 adds optional plain-text `notes` to each group (at most 20,000 characters).
Nonempty group notes require Studio v0.9 or newer. For example:

```json
"groups": {
  "setup": {
    "name": "Open menu",
    "color": "#83b8f2",
    "notes": "Check that the interaction menu is ready before continuing."
  }
}
```

The `action: "note"`, `title` and `text` fields from the older inline-card design
remain accepted for import. Loading converts those cards into nearby group notes,
or retains note-only files in the workflow's top-level description. Input events,
timing and order remain unchanged; reading never overwrites the source file.
The current editor does not create standalone note cards. Explicit file versions
are retained even if their newer optional fields are absent.
