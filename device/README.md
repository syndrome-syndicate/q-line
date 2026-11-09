# Display Device

Plug in the device and run:

```bash uv run app.py ```

## JSON Contract

The application sends one JSON object per panel update.

```json
{
  "type": "next",
  "d": ["on", "x", "z", "y", "off", "on", "off", "x", "z"],
  "z": ["on", "flagged", "off", "on"],
  "x": ["off", "on", "flagged", "off"],
  "logical_failure": false,
  "reset": false
}
```

### Fields

| Field | Required | Values |
|---|---|---|
| `type` | Yes | `"next"` |
| `d` | Yes | Exactly 9 values: `"on"`, `"x"`, `"z"`, `"y"`, `"off"` |
| `z` | Yes | Exactly 4 values: `"on"`, `"flagged"`, `"off"` |
| `x` | Yes | Exactly 4 values: `"on"`, `"flagged"`, `"off"` |
| `logical_failure` | No | `true` / `false` (default: `false`) |
| `reset` | No | `true` / `false` (default: `false`) |

All field names and string values are case-sensitive.

### Panel Behavior

The display maintains exactly 10 panels.

- **`reset: false`** — Shift panels 2–10 into positions 1–9, discard the old panel 1, and place the supplied panel in panel 10.
- **`reset: true`** — Clear all 10 panels, then place the supplied panel in panel 10.
- **Blank panel** — All array values `"off"`; still advances the display.
- **`logical_failure`** — Belongs to the supplied panel and moves with it when panels shift.

Invalid JSON or invalid field values are rejected without changing the panel history.

### Python API

Use `display_device.py` to handle USB discovery, serial communication, JSON serialization, validation, and acknowledgments.

```python
from display_device import DisplayDevice, Panel

with DisplayDevice.connect() as device:
    # Reset history and place a panel in position 10.
    device.send_next(
        Panel(
            d=["on", "x", "z", "y", "off", "on", "off", "x", "z"],
            z=["on", "flagged", "off", "on"],
            x=["off", "on", "flagged", "off"],
            logical_failure=False,
        ),
        reset=True,
    )

    # Shift a blank panel into position 10.
    device.send_next(Panel())

    # Add another panel without resetting.
    device.send_next(Panel(d=["on"] * 9))
```

The library automatically discovers the device using USB VID `2E8A`, PID `0009`.

### Acknowledgment

Each accepted panel receives:

```json
{"type":"ack","ok":true,"revision":1}
```

An invalid panel receives:

```json
{"type":"ack","ok":false,"error":"invalid_next"}
```

`revision` increments whenever a panel is successfully accepted.

The firmware maintains the 10-panel history. The application only supplies the next panel and decides when to reset.
