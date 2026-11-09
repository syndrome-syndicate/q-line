"""USB serial transport for the display-device Pico firmware.

Requires: pyserial
Protocol: one newline-terminated JSON object per "next" command.
"""

import argparse
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import serial
from serial.tools import list_ports


DEFAULT_VID = 0x2E8A
# Pico SDK CDC identifiers; override with --pid or connect(pid=...).
DEFAULT_PIDS = (0x0009,)

DATA_VALUES = frozenset(("on", "x", "z", "y", "off"))
CHECK_VALUES = frozenset(("on", "flagged", "off"))


@dataclass
class Panel:
    d: list[str] = field(default_factory=lambda: ["off"] * 9)
    z: list[str] = field(default_factory=lambda: ["off"] * 4)
    x: list[str] = field(default_factory=lambda: ["off"] * 4)
    logical_failure: bool = False

    def payload(self, reset: bool = False) -> dict:
        for name, values, count, allowed in (
            ("d", self.d, 9, DATA_VALUES),
            ("z", self.z, 4, CHECK_VALUES),
            ("x", self.x, 4, CHECK_VALUES),
        ):
            if not isinstance(values, (list, tuple)):
                raise ValueError(f"{name} must be an array")
            if len(values) != count:
                raise ValueError(f"{name} must contain exactly {count} values")
            if any(type(v) is not str or v not in allowed for v in values):
                raise ValueError(f"{name} contains an invalid value")

        if type(self.logical_failure) is not bool:
            raise ValueError("logical_failure must be a boolean")
        if type(reset) is not bool:
            raise ValueError("reset must be a boolean")

        return {
            "type": "next",
            "d": list(self.d),
            "z": list(self.z),
            "x": list(self.x),
            "logical_failure": self.logical_failure,
            "reset": reset,
        }


def ports():
    """Return available USB serial port descriptions."""
    return list(list_ports.comports())


def discover(vid=DEFAULT_VID, pid=None) -> str:
    """Return one matching device path, or fail on zero/multiple matches."""
    pids = (pid,) if pid is not None else DEFAULT_PIDS

    matches = [
        port for port in ports()
        if port.vid == vid and port.pid in pids
    ]

    if not matches:
        found = ", ".join(
            f"{p.device}={p.vid:04X}:{p.pid:04X}"
            for p in ports()
            if p.vid is not None and p.pid is not None
        )
        raise RuntimeError(
            "No matching display device found. "
            f"Visible USB serial ports: {found or 'none'}"
        )

    if len(matches) != 1:
        names = ", ".join(p.device for p in matches)
        raise RuntimeError(
            f"Expected exactly one matching device; "
            f"found {len(matches)}: {names}. Specify a PID."
        )

    return matches[0].device


class DisplayDevice:
    def __init__(
        self,
        port: str,
        on_message: Optional[Callable[[dict], None]] = None,
    ):
        self.port = port
        self.on_message = on_message

        self._serial = serial.Serial(
            port=port,
            baudrate=115200,
            timeout=0.1,
            write_timeout=2,
        )

        self._stop = threading.Event()
        self._tx_lock = threading.Lock()
        self._acks = queue.Queue()
        self._lines = queue.Queue()
        self._messages = queue.Queue()
        self._error = None

        self._thread = threading.Thread(
            target=self._reader,
            name="display-device-listener",
            daemon=True,
        )
        self._thread.start()

    @classmethod
    def connect(cls, vid=DEFAULT_VID, pid=None, on_message=None):
        return cls(discover(vid=vid, pid=pid), on_message=on_message)

    def _reader(self):
        try:
            while not self._stop.is_set():
                raw = self._serial.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                line = line.lstrip(">").strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._lines.put(line)
                    continue

                if isinstance(message, dict):
                    if message.get("type") == "ack":
                        self._acks.put(message)
                    else:
                        self._messages.put(message)
                        if self.on_message is not None:
                            try:
                                self.on_message(message)
                            except Exception as exc:
                                self._lines.put(f"listener error: {exc}")
                else:
                    self._lines.put(line)

        except (serial.SerialException, OSError) as exc:
            self._error = exc
            self._stop.set()

    def _write_line(self, line):
        if not self._serial.is_open or self._error:
            raise ConnectionError(f"Device disconnected: {self._error}")
        self._serial.write((line + "\n").encode("utf-8"))
        self._serial.flush()

    def _wait(self, incoming, timeout):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self._error:
                raise ConnectionError(f"Serial reader failed: {self._error}")
            try:
                return incoming.get(timeout=min(0.1, max(
                    0.001, deadline - time.monotonic()
                )))
            except queue.Empty:
                continue

        raise TimeoutError("Timed out waiting for device response")

    def send_next(self, panel: Panel, reset=False, timeout=3.0) -> dict:
        """Send one panel, await firmware acknowledgment."""
        if not isinstance(panel, Panel):
            raise TypeError("panel must be a Panel instance")

        payload = panel.payload(reset=reset)
        encoded = json.dumps(payload, separators=(",", ":"))

        # Firmware command buffer is 512 bytes, including NUL.
        if len(encoded.encode("utf-8")) >= 512:
            raise ValueError("JSON payload exceeds firmware input limit")

        with self._tx_lock:
            while not self._acks.empty():
                try:
                    self._acks.get_nowait()
                except queue.Empty:
                    break

            self._write_line(encoded)
            reply = self._wait(self._acks, timeout)

        if reply.get("ok") is not True:
            raise RuntimeError(f"Firmware rejected panel: {reply}")

        return reply

    def next(self, panel: Panel, reset=False, timeout=3.0):
        return self.send_next(panel, reset=reset, timeout=timeout)

    def read_message(self, timeout=0.0):
        """Retrieve an unsolicited parsed JSON message, if available."""
        try:
            return self._messages.get(timeout=timeout)
        except queue.Empty:
            return None

    def debug_command(self, command: str, timeout=3.0) -> str:
        """Temporary test-only access to existing firmware diagnostics."""
        if not command.startswith(("panel get ", "panel status")):
            raise ValueError("Unsupported diagnostic command")

        with self._tx_lock:
            while not self._lines.empty():
                try:
                    self._lines.get_nowait()
                except queue.Empty:
                    break

            self._write_line(command)

            # "panel get" returns JSON; status returns plain text.
            if command.startswith("panel get "):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    item = self.read_message(timeout=0.05)
                    if isinstance(item, dict) and "panel" in item:
                        return json.dumps(item)
                    if self._error:
                        raise ConnectionError(str(self._error))
                raise TimeoutError("No panel readback received")

            return self._wait(self._lines, timeout)

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
        if self._serial.is_open:
            self._serial.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("ports", "test"),
        help="List USB ports or run ten-panel integration test"
    )
    parser.add_argument("--vid", type=lambda s: int(s, 16),
                        default=DEFAULT_VID)
    parser.add_argument("--pid", type=lambda s: int(s, 16))
    args = parser.parse_args()

    if args.action == "ports":
        for p in ports():
            ident = (
                f"{p.vid:04X}:{p.pid:04X}"
                if p.vid is not None and p.pid is not None
                else "unknown"
            )
            print(f"{p.device:10} {ident:10} {p.description}")
        return

    print("Discovering device...")
    with DisplayDevice.connect(vid=args.vid, pid=args.pid) as device:
        print("Connected:", device.port)

        def send(panel, reset=False):
            reply = device.send_next(panel, reset=reset)
            print(f"  next(reset={reset}) -> revision {reply['revision']}")

        def check(number, expected):
            actual = json.loads(
                device.debug_command(f"panel get {number}")
            )
            assert actual["panel"] == number
            assert actual["d"] == expected.d
            assert actual["z"] == expected.z
            assert actual["x"] == expected.x
            assert actual["logical_failure"] == expected.logical_failure
            print(f"  panel {number}: PASS")

        print("\n1. Reset with a distinctive panel")
        first = Panel(
            d=["on", "x", "z", "y", "off", "on", "off", "x", "z"],
            z=["on", "flagged", "off", "on"],
            x=["flagged", "on", "off", "flagged"],
            logical_failure=True,
        )
        send(first, reset=True)
        check(10, first)
        check(9, Panel())

        print("\n2. Shift a blank panel")
        send(Panel())
        check(9, first)
        check(10, Panel())

        print("\n3. Send ten distinct visual panels")
        patterns = ["on", "x", "z", "y", "off"]
        sequence = []

        for i in range(10):
            p = Panel(
                d=[patterns[(i + j) % 5] for j in range(9)],
                z=["flagged" if j == i % 4 else "off"
                   for j in range(4)],
                x=["on" if j == (i + 1) % 4 else "off"
                   for j in range(4)],
                logical_failure=(i % 3 == 0),
            )
            sequence.append(p)
            send(p)

        for index, expected in enumerate(sequence, start=1):
            check(index, expected)

        print("\n4. Reset again; previous panels must disappear")
        final = Panel(d=["y"] * 9, logical_failure=True)
        send(final, reset=True)
        check(10, final)

        for index in range(1, 10):
            check(index, Panel())

        print("\nALL PANEL TESTS PASSED")


if __name__ == "__main__":
    main()
