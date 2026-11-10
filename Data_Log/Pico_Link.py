"""
Send LED frames to the Pico display over USB, live.

Uses device/display_device.py (DisplayDevice, Panel). Each saved frame becomes
the next panel; a frame with "reset": true clears the ten-panel history first.
Sending runs on a background thread so the GUI never waits for the Pico's ack.
Every panel is printed to the terminal exactly as sent ("->") with the Pico's
reply ("<-").
If no Pico is plugged in, display_device.py starts device/emulator.py (a window
with the same ten panels and buttons) and connects to that instead.

The device's buttons come back as events (poll_events); Live_visualizer.py maps
them onto its own buttons.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
from pathlib import Path
from typing import Any

DEVICE_DIR = Path(__file__).resolve().parent.parent / "device"


def _display_device():
    if str(DEVICE_DIR) not in sys.path:
        sys.path.insert(0, str(DEVICE_DIR))
    import display_device

    return display_device


def frame_to_panel(frame: dict[str, Any]):
    """Our frame {"Data", "Sz", "Sx", "logical failure", "reset"} -> (Panel, reset)."""
    Panel = _display_device().Panel
    panel = Panel(
        d=list(frame["Data"]),
        z=list(frame["Sz"]),
        x=list(frame["Sx"]),
        logical_failure=bool(frame["logical failure"]),
    )
    return panel, bool(frame["reset"])


class PicoLink:
    """Queue frames and send them to the LED display one at a time."""

    def __init__(self, device=None, pid: int | None = None, verbose: bool = True):
        self.device = device
        self.verbose = verbose  # print every panel sent to the terminal
        self.sent = 0
        self.status = ""
        if self.device is None:
            try:
                module = _display_device()
                self.device = module.DisplayDevice.connect(pid=pid)
            except Exception as error:  # no Pico, no pyserial, port busy, ...
                print(f"LED panel not connected: {error}")
                self.status = "not connected (frames are only saved)"
                return
        self.status = f"connected on {getattr(self.device, 'port', '?')}"
        print(f"LED panel {self.status}")
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="pico-link", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self.device is not None

    def send(self, frame: dict[str, Any]) -> None:
        if self.connected:
            self._queue.put(frame)

    def poll_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Button events the device sent since the last call (never blocks).

        The firmware / emulator sends {"type": "event", "event": NAME, "seq", "d",
        "mode", "pause"} with NAME one of next_request, reset, pause, run, update, mode.
        """
        read = getattr(self.device, "read_message", None)
        if read is None:
            return []
        events = []
        for _ in range(limit):
            try:
                message = read(timeout=0.0)
            except Exception:
                break
            if message is None:
                break
            if isinstance(message, dict) and message.get("type") == "event":
                if self.verbose:
                    print(f"<- event: {json.dumps(message, separators=(',', ':'))}", flush=True)
                events.append(message)
        return events

    def wait(self, timeout: float = 5.0) -> None:
        """Block until every queued frame has been sent (used by tests)."""
        if not self.connected:
            return
        done = threading.Event()
        self._queue.put(done)
        done.wait(timeout)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            if isinstance(item, threading.Event):
                item.set()
                continue
            try:
                panel, reset = frame_to_panel(item)
                if self.verbose:
                    # The exact line display_device.send_next writes to the USB port.
                    line = json.dumps(panel.payload(reset=reset), separators=(",", ":"))
                    print(f"-> panel {self.sent + 1}: {line}", flush=True)
                reply = self.device.send_next(panel, reset=reset)
                if self.verbose:
                    print(f"<- {json.dumps(reply, separators=(',', ':'))}", flush=True)
                self.sent += 1
                kind = "reset" if reset else "panel"
                self.status = (
                    f"connected on {getattr(self.device, 'port', '?')}: {kind} sent "
                    f"(revision {reply.get('revision', '?')})"
                )
            except Exception as error:
                self.status = f"send failed: {error}"
                print(f"LED panel send failed: {error}")

    def close(self) -> None:
        if not self.connected:
            return
        self._queue.put(None)
        self._thread.join(timeout=5)
        try:
            self.device.close()
        except Exception:
            pass
        self.device = None
