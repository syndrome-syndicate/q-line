"""
Re-simulate a surface-code run with faults placed at specific points in time.

The playback window calls ``simulate_history`` every time a fault is injected,
so the syndromes and corrections it shows always come from a fresh Aer run.

Timed faults carry the display step they were injected at plus where they land
in the circuit:
    {"qubit": 2, "gate": "Z", "round": 1, "after": "X", "step": 0}
``after="X"`` means right after round 1's X checks (before its Z checks);
``after="Z"`` means after round 1's Z checks (before round 2).
Faults without ``round``/``after`` are applied before the first round.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pymatching
from qiskit import QuantumCircuit

from .circuits import X_CHECK_SUPPORTS, Z_CHECK_SUPPORTS, create_surface_code_circuit
from .fault_injection import inject_fault
from .Stepwise_simulation import StepwiseSimulation

PHASES = ("X checks", "Z checks", "Decode")
FAULT_GATES = {"X", "Z", "H"}


def _check_matrix(supports) -> np.ndarray:
    matrix = np.zeros((len(supports), 9), dtype=np.uint8)
    for check_index, support in enumerate(supports):
        matrix[check_index, list(support)] = 1
    return matrix


def fault_location(step: dict[str, Any]) -> tuple[int, str] | None:
    """Where a fault injected while ``step`` is shown lands in the circuit."""
    phase = step.get("phase")
    if phase == "X checks":
        return step["round"], "X"
    if phase in ("Z checks", "Decode"):
        return step["round"], "Z"
    return None


def _insert_timed_faults(circuit: QuantumCircuit, timed_faults) -> QuantumCircuit:
    """Copy ``circuit`` and add each timed fault after its round_*_mid/end barrier."""
    by_barrier: dict[str, list[dict[str, Any]]] = {}
    for fault in timed_faults:
        suffix = "mid" if fault["after"] == "X" else "end"
        by_barrier.setdefault(f"round_{fault['round'] - 1}_{suffix}", []).append(fault)

    faulted = circuit.copy_empty_like()
    for instruction in circuit.data:
        faulted.append(instruction)
        label = instruction.operation.label or ""
        if instruction.operation.name == "barrier" and label in by_barrier:
            for fault in by_barrier.pop(label):
                inject_fault(faulted, fault["qubit"], fault["gate"])
    if by_barrier:
        raise ValueError(f"no barrier for faults at {sorted(by_barrier)}")
    return faulted


def build_round_steps(rounds: list[dict], events: list[dict]) -> list[dict]:
    """Reduce recorded measurements into X, Z, decode, and reset display frames.

    Faults with a ``step`` key are shown from that step on; faults without one
    (injected before the run) are shown on every step.
    """
    if not rounds:
        raise ValueError("simulation history contains no measured rounds")

    match_z = pymatching.Matching.from_check_matrix(_check_matrix(Z_CHECK_SUPPORTS))
    match_x = pymatching.Matching.from_check_matrix(_check_matrix(X_CHECK_SUPPORTS))
    previous = {"X": [0] * len(X_CHECK_SUPPORTS), "Z": [0] * len(Z_CHECK_SUPPORTS)}
    faults = [
        event
        for event in events
        if isinstance(event, dict)
        and isinstance(event.get("qubit"), int)
        and event.get("gate") in FAULT_GATES
        and 0 <= event["qubit"] < 9
    ]
    steps: list[dict] = []

    def visible_faults(step_index: int) -> list[dict]:
        return [
            {"qubit": fault["qubit"], "gate": fault["gate"]}
            for fault in faults
            if fault.get("step", -1) <= step_index
        ]

    for round_data in rounds:
        round_number = round_data["round"]
        checks_by_basis = {
            basis: sorted(
                (check for check in round_data["checks"] if check["basis"] == basis),
                key=lambda check: check["check"],
            )
            for basis in ("X", "Z")
        }
        raw = {
            basis: [
                check["outcomes"][0] if check["outcomes"] else 0
                for check in checks_by_basis[basis]
            ]
            for basis in ("X", "Z")
        }
        if any(len(raw[basis]) != len(previous[basis]) for basis in ("X", "Z")):
            raise ValueError(f"round {round_number} has incomplete stabilizer measurements")
        detections = {
            basis: [outcome ^ prior for outcome, prior in zip(raw[basis], previous[basis])]
            for basis in ("X", "Z")
        }

        for basis in ("X", "Z"):
            steps.append(
                {
                    "step": len(steps),
                    "round": round_number,
                    "phase": f"{basis} checks",
                    "syndromes": {
                        basis: [i for i, bit in enumerate(detections[basis]) if bit]
                    },
                    "outcomes": {basis: raw[basis]},
                    "faults": visible_faults(len(steps)),
                }
            )

        correction_x = match_z.decode(np.asarray(detections["Z"], dtype=np.uint8))
        correction_z = match_x.decode(np.asarray(detections["X"], dtype=np.uint8))
        corrections = [
            {"qubit": qubit, "pauli": "Y" if cx and cz else "X" if cx else "Z"}
            for qubit, (cx, cz) in enumerate(zip(correction_x, correction_z))
            if cx or cz
        ]
        steps.append(
            {
                "step": len(steps),
                "round": round_number,
                "phase": "Decode",
                "syndromes": {
                    basis: [i for i, bit in enumerate(detections[basis]) if bit]
                    for basis in ("X", "Z")
                },
                "corrections": corrections,
                "faults": visible_faults(len(steps)),
            }
        )
        previous = raw

    steps.append(
        {
            "step": len(steps),
            "round": rounds[-1]["round"],
            "phase": "Reset",
            "syndromes": {"X": [], "Z": []},
            "corrections": [],
            "faults": [],
        }
    )
    return steps


def simulate_history(
    num_rounds: int,
    faults: list[dict[str, Any]] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run the circuit on Aer with the given faults and return a playback history."""
    faults = [dict(fault) for fault in faults or []]
    for fault in faults:
        if fault.get("gate") not in FAULT_GATES or not 0 <= fault.get("qubit", -1) < 9:
            raise ValueError(f"unsupported fault {fault}")
    timed = [fault for fault in faults if "round" in fault]
    initial = [fault for fault in faults if "round" not in fault]

    circuit = _insert_timed_faults(create_surface_code_circuit(num_rounds), timed)
    simulation = StepwiseSimulation()
    simulation.build_initial_circuit_state(circuit)
    for fault in initial:
        simulation.detect_event({"qubit": fault["qubit"], "gate": fault["gate"]})
    simulation.run_rounds(num_rounds=num_rounds, record_steps=False, seed=seed)

    history = simulation.get_history()
    history["events"] = faults
    history["num_rounds"] = num_rounds
    history["seed"] = seed
    history["steps"] = build_round_steps(history["rounds"], faults)
    return history
