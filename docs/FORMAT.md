# Script format v1

Files use UTF-8 JSON and must include `version: 1` and a `steps` array.

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
