# Display Device

Python interface for communicating with the display device (Raspberry Pi Pico 2 was used)

## Quick Start

Connect the device via USB, then run:

```bash
uv run app.py
```

`uv` automatically manages Python (3.14.9+) and the required dependencies.

> [!WARNING]
>
> If no physical device is detected, a local emulator automatically launches.
>
> Although it shows basic functionality the emulator does **not** fully replicate the real device's firmware or behavior accurately. Do not rely on it to validate hardware functionality or device-specific behavior.
> **The emulator is intended for interface development and testing only.**

## Python API

Applications communicate through the `display_device` Python module.

```python
from display_device import DisplayDevice, Panel

with DisplayDevice.connect() as device:
    # Reset history and place a blank panel in position 10.
    device.send_next(Panel(), reset=True)

    # Advance the display with a populated panel.
    device.send_next(
        Panel(
            d=["on", "x", "z", "y", "off", "on", "off", "x", "z"],
            z=["on", "flagged", "off", "on"],
            x=["off", "on", "flagged", "off"],
            logical_failure=False,
        )
    )
```

The module handles USB discovery, serial communication, JSON validation, acknowledgments, and automatic emulator fallback.

The physical device is identified using USB VID `2E8A` and PID `0009`.

## JSON Protocol

Communication is bidirectional:

- **Computer → Device:** Sends complete display panels using `next`.
- **Device → Computer:** Sends events reporting changes or requesting application actions.
- **Device → Computer:** Acknowledges incoming panel commands.

### Computer → Device: `next`

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

| Field | Required | Values |
|---|---|---|
| `type` | Yes | `"next"` |
| `d` | Yes | Exactly 9: `"on"`, `"x"`, `"z"`, `"y"`, `"off"` |
| `z` | Yes | Exactly 4: `"on"`, `"flagged"`, `"off"` |
| `x` | Yes | Exactly 4: `"on"`, `"flagged"`, `"off"` |
| `logical_failure` | No | Boolean, defaults to `false` |
| `reset` | No | Boolean, defaults to `false` |

All field names and string values are case-sensitive.

### Panel History

The device maintains exactly 10 panels. Panel 10 is the newest and currently interactive panel.

**Normal advance (`reset: false`):**

1. Discard panel 1.
2. Shift panels 2–10 into positions 1–9.
3. Insert the supplied panel into position 10.

**Reset (`reset: true`):**

1. Clear all ten panels.
2. Insert the supplied panel into position 10.

A blank panel (all array values `"off"`) is valid and still advances history.

### Temporary Local Edits

While paused, the physical data buttons may modify the nine `d` values currently displayed on panel 10.

These edits do not modify `x`, `z`, or `logical_failure`.

The device preserves two versions of panel 10:

- **Original:** Last panel supplied by the computer.
- **Displayed:** Current visible panel, including local edits.

When a `next` command arrives:

- If a `next_request` occurred, the device preserves the exact displayed snapshot captured at the time of that request.
- Otherwise, the device preserves the original computer-supplied panel and discards temporary edits.

Both versions are replaced by the newly supplied panel 10. Pending request state is cleared.

A `reset: true` command always clears the history before inserting the supplied panel.

## Device → Computer: Events

The device reports events using a common JSON structure.

```json
{
  "type": "event",
  "event": "next_request",
  "seq": 42,
  "d": ["on", "x", "z", "y", "off", "on", "off", "x", "z"],
  "mode": 2,
  "pause": true
}
```

| Field | Description |
|---|---|
| `type` | Always `"event"` |
| `event` | Event name |
| `seq` | Incrementing event sequence |
| `d` | Nine currently displayed data values |
| `mode` | Current mode selector |
| `pause` | Whether the device is paused |

### Event Types

| Event | Trigger |
|---|---|
| `update` | Local data-button edit |
| `next_request` | Short NEXT press |
| `reset` | NEXT held for 2 seconds |
| `pause` | PAUSE selected |
| `run` | RUN selected |
| `mode` | Mode selector changed |

The X/Z selector, X/Z check arrays, and `logical_failure` are not included in outgoing events.

The NEXT long-press `reset` event is a request to the application; it does not automatically clear panel history.

### Handling Events in Python

```python
from display_device import DisplayDevice, Panel

with DisplayDevice.connect() as device:
    while True:
        event = device.read_message(timeout=0.5)

        if not event or event.get("type") != "event":
            continue

        if event["event"] == "next_request":
            # Application determines the next panel.
            next_panel = Panel()
            device.send_next(next_panel)

        elif event["event"] == "reset":
            # Clear history and supply a new panel 10.
            device.send_next(Panel(), reset=True)

        elif event["event"] == "update":
            print("Current data:", event["d"])

        elif event["event"] in ("pause", "run", "mode"):
            print("Control event:", event)
```

This is a simple integration example. The included `app.py` demonstrates a persistent bidirectional connection with generated test patterns.

## Acknowledgments

Accepted `next` command:

```json
{"type":"ack","ok":true,"revision":1}
```

Rejected command:

```json
{"type":"ack","ok":false,"error":"invalid_next"}
```

`revision` increments whenever the stored display state changes.

Invalid JSON or invalid panel values are rejected without advancing panel history.

## Device and Emulator

The same Python API supports both environments.

| Environment | Connection |
|---|---|
| Physical Pico 2 W | USB serial, VID `2E8A`, PID `0009` |
| Local emulator | TCP at `127.0.0.1:8765` |

The application does not need to select the transport manually. When no matching physical device is detected, the module starts the emulator automatically.

The application can send panels and receive events through the same interface regardless of transport.