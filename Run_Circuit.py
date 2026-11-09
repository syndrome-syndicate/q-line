"""Run, save, and replay step-by-step surface-code circuit simulations."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pymatching

from Data_Log.Experiment_Logger import ExperimentLogger
from Round_visualizer import (
    CircuitVisualizer,
    X_CHECK_SUPPORTS,
    Z_CHECK_SUPPORTS,
    animate_rounds,
)
from Simulation_Logic import StepwiseSimulation, create_surface_code_circuit


def parse_fault(value: str) -> tuple[int, str]:
    try:
        qubit_text, gate = value.split(":", maxsplit=1)
        qubit = int(qubit_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "fault must use QUBIT:GATE format, for example 4:Z"
        ) from error
    gate = gate.upper()
    if qubit < 0 or gate not in {"X", "Z", "H"}:
        raise argparse.ArgumentTypeError("fault gate must be X, Z, or H and qubit nonnegative")
    return qubit, gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a circuit run and animate its saved steps."
    )
    parser.add_argument(
        "--history",
        type=Path,
        help="replay an existing JSON run instead of starting a new simulation",
    )
    parser.add_argument("--rounds", type=int, default=3, help="rounds to simulate")
    parser.add_argument(
        "--fault",
        type=parse_fault,
        action="append",
        default=[],
        metavar="QUBIT:GATE",
        help="inject a fault before the first circuit step (repeatable)",
    )
    parser.add_argument("--interval", type=int, default=10, help="milliseconds per frame")
    return parser


def _check_matrix(supports: tuple[tuple[int, ...], ...]) -> np.ndarray:
    matrix = np.zeros((len(supports), 9), dtype=np.uint8)
    for check_index, support in enumerate(supports):
        matrix[check_index, list(support)] = 1
    return matrix


def build_round_steps(
    rounds: list[dict],
    events: list[dict],
) -> list[dict]:
    """Reduce recorded measurements into X, Z, decode, and reset display frames."""
    if not rounds:
        raise ValueError("simulation history contains no measured rounds")

    match_z = pymatching.Matching.from_check_matrix(_check_matrix(Z_CHECK_SUPPORTS))
    match_x = pymatching.Matching.from_check_matrix(_check_matrix(X_CHECK_SUPPORTS))
    previous = {"X": [0] * len(X_CHECK_SUPPORTS), "Z": [0] * len(Z_CHECK_SUPPORTS)}
    steps = []
    cumulative_faults = [
        {"qubit": event["qubit"], "gate": event["gate"]}
        for event in events
        if isinstance(event, dict)
        and isinstance(event.get("qubit"), int)
        and event.get("gate") in {"X", "Z", "H"}
        and 0 <= event["qubit"] < 9
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
            basis: [
                outcome ^ prior
                for outcome, prior in zip(raw[basis], previous[basis])
            ]
            for basis in ("X", "Z")
        }

        steps.append(
            {
                "step": len(steps),
                "round": round_number,
                "phase": "X checks",
                "syndromes": {"X": [i for i, bit in enumerate(detections["X"]) if bit]},
                "outcomes": {"X": raw["X"]},
                "faults": cumulative_faults,
            }
        )
        steps.append(
            {
                "step": len(steps),
                "round": round_number,
                "phase": "Z checks",
                "syndromes": {"Z": [i for i, bit in enumerate(detections["Z"]) if bit]},
                "outcomes": {"Z": raw["Z"]},
                "faults": cumulative_faults,
            }
        )

        correction_x = match_z.decode(np.asarray(detections["Z"], dtype=np.uint8))
        correction_z = match_x.decode(np.asarray(detections["X"], dtype=np.uint8))
        corrections = []
        for qubit, (apply_x, apply_z) in enumerate(zip(correction_x, correction_z)):
            if apply_x or apply_z:
                corrections.append(
                    {
                        "qubit": qubit,
                        "pauli": "Y" if apply_x and apply_z else "X" if apply_x else "Z",
                    }
                )
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
                "faults": cumulative_faults,
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


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.rounds < 1:
        raise SystemExit("--rounds must be at least 1")
    if args.interval < 1:
        raise SystemExit("--interval must be at least 1")

    visualizer = CircuitVisualizer("Surface-code circuit replay")
    if args.history is not None:
        history_path = args.history.expanduser().resolve()
        if not history_path.is_file():
            raise FileNotFoundError(f"Simulation history not found: {history_path}")
        animation = animate_rounds(
            visualizer, history_path, interval=args.interval, repeat=False
        )
        print(f"Replaying saved simulation: {history_path}")
    else:
        circuit = create_surface_code_circuit(num_rounds=args.rounds)
        simulation = StepwiseSimulation()
        simulation.build_initial_circuit_state(circuit)
        for qubit, gate in args.fault:
            if qubit >= 9:
                raise SystemExit(f"data-qubit index must be between 0 and 8: {qubit}")
            simulation.detect_event({"qubit": qubit, "gate": gate})
        simulation.run_rounds(num_rounds=args.rounds, record_steps=False)
        history = simulation.get_history()
        history["steps"] = build_round_steps(history["rounds"], history["events"])

        log_file = ExperimentLogger("logs").log_experiment(history)
        animation = animate_rounds(
            visualizer, log_file, interval=args.interval, repeat=False
        )
        print(f"Saved simulation history: {log_file}")

    # Keep a reference alive until the GUI event loop finishes.
    visualizer.animation = animation
    plt.show()

if __name__ == "__main__":
    main()
