"""
LED-panel frames for the Pico.

One frame is the whole array as the laptop shows it:

    {
      "Data": ["on", "x", ...],        # D1..D9: "on" | "x" | "y" | "z"
      "Sz":   ["off", "on", ...],      # 4 Z checks:   "off" | "on" | "flagged"
      "Sx":   ["off", ...],            # 4 X checks:   "off" | "on" | "flagged"
      "logical failure": false,
      "reset": false                   # true -> show fresh, pristine qubits
    }

Order: Data[0..8] is D1..D9 (rows D1 D2 D3 / D4 D5 D6 / D7 D8 D9); Sz[i] / Sx[i]
are checks Z1..Z4 / X1..X4 (array indices 0..3):
    Z1 = D1 D4        Z2 = D4 D5 D7 D8   Z3 = D2 D3 D5 D6   Z4 = D6 D9
    X0 = D2 D3        X1 = D1 D2 D4 D5   X2 = D5 D6 D8 D9   X3 = D7 D8
(defined in Simulation_Logic/circuits.py).

Checks are "on" while they are being measured in the shown step. A check that
flagged stays "flagged" from the step it was measured until the decode step of
that cycle (inclusive), even while the other type of check is being measured.
Everything else is "off".

Each run of the visualizer writes its frames to data_to_pico/<date_time>/.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

NUM_DATA = 9
NUM_CHECKS = 4


def make_frame(
    errors: dict[int, str],
    result: Any = None,
    logical_failure: bool = False,
    reset: bool = False,
) -> dict[str, Any]:
    """Build one frame.

    errors: current Pauli error per data qubit, e.g. {4: "X"}.
    result: the last StepResult (or None right after a reset).
    """
    frame = {
        "Data": [errors.get(q, "on").lower() for q in range(NUM_DATA)],
        "Sz": ["off"] * NUM_CHECKS,
        "Sx": ["off"] * NUM_CHECKS,
        "logical failure": bool(logical_failure),
        "reset": bool(reset),
    }
    if reset or result is None:
        return frame

    decoding = result.step.startswith("Decode")
    for basis in ("X", "Z"):
        key = f"S{basis.lower()}"
        if basis in result.detections:  # measured now, or used by the decoder now
            idle = "off" if decoding else "on"
            frame[key] = ["flagged" if bit else idle for bit in result.detections[basis]]
        elif basis in getattr(result, "pending", {}):  # flagged earlier this cycle
            frame[key] = ["flagged" if bit else "off" for bit in result.pending[basis]]
    return frame


FRAME_KEYS = ("Data", "Sz", "Sx", "logical failure", "reset")


def load_frames(folder: str | Path) -> list[tuple[Path, dict[str, Any]]]:
    """Read every frame_*.json in a run folder, in order."""
    folder = Path(folder)
    files = sorted(folder.glob("frame_*.json"))
    if not files:
        raise ValueError(f"no frame_*.json files in {folder}")
    frames = []
    for path in files:
        frame = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in FRAME_KEYS if key not in frame]
        if missing:
            raise ValueError(f"{path.name} is missing {missing}")
        if len(frame["Data"]) != NUM_DATA or len(frame["Sz"]) != NUM_CHECKS or len(frame["Sx"]) != NUM_CHECKS:
            raise ValueError(f"{path.name} has the wrong number of qubits or checks")
        frames.append((path, frame))
    return frames


class PicoFrameWriter:
    """Save frames as data_to_pico/<YYYY-MM-DD_HH-MM-SS>/frame_0000.json, ..."""

    def __init__(self, root: str | Path = "data_to_pico"):
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.directory = Path(root) / stamp
        suffix = 1
        while self.directory.exists():
            self.directory = Path(root) / f"{stamp}_{suffix}"
            suffix += 1
        self.directory.mkdir(parents=True)
        self.count = 0

    def remove_if_empty(self) -> None:
        """Drop the run folder if nothing was saved (e.g. a replay-only session)."""
        try:
            self.directory.rmdir()  # only succeeds when the folder is empty
        except OSError:
            pass

    def write(self, frame: dict[str, Any]) -> Path:
        path = self.directory / f"frame_{self.count:04d}.json"
        path.write_text(json.dumps(frame, indent=2), encoding="utf-8")
        self.count += 1
        return path
