"""Automatically connect to a real Pico or launch the local emulator."""

import socket
import subprocess
import sys
import time
from pathlib import Path

from display_device import (
    DisplayDevice as RealDevice,
    Panel,
    discover,
)
from emulator_client import DisplayDevice as EmulatorDevice


VID = 0x2E8A
PID = 0x0009

EMULATOR_HOST = "127.0.0.1"
EMULATOR_PORT = 8765


def emulator_running():
    try:
        with socket.create_connection(
            (EMULATOR_HOST, EMULATOR_PORT),
            timeout=0.2,
        ):
            return True
    except OSError:
        return False


def start_emulator():
    if emulator_running():
        return

    script = Path(__file__).resolve().parent / "emulator.py"

    if not script.is_file():
        raise FileNotFoundError(f"Missing emulator: {script}")

    process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(script.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + 10.0

    while time.monotonic() < deadline:
        if emulator_running():
            return

        if process.poll() is not None:
            raise RuntimeError(
                "Emulator exited during startup. "
                "Run 'uv run emulator.py' to inspect the error."
            )

        time.sleep(0.1)

    raise TimeoutError(
        "Emulator did not become available on localhost:8765"
    )


class DisplayDevice:
    @classmethod
    def connect(cls, vid=VID, pid=PID, on_message=None):
        try:
            port = discover(vid=vid, pid=pid)
        except RuntimeError as exc:
            # Fall back only when no matching device exists.
            # Multiple devices or other discovery errors are not
            # silently treated as missing hardware.
            if not str(exc).startswith(
                "No matching display device found"
            ):
                raise

            print("No physical display device detected.")
            print("Starting local emulator...")

            start_emulator()

            device = EmulatorDevice.connect(
                on_message=on_message
            )

            print("Connected to emulator.")
            return device

        print(f"Physical display device detected: {port}")

        # If the device exists but cannot be opened,
        # propagate the error rather than using the emulator.
        return RealDevice(
            port,
            on_message=on_message,
        )
