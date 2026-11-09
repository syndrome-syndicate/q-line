"""Run, save, and replay step-by-step surface-code circuit simulations."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from Round_visualizer import CircuitVisualizer, animate_rounds
from Simulation_Logic import build_round_steps, simulate_history  # noqa: F401  (re-exported)


def parse_fault(value: str) -> tuple[int, str]:
    try:
        qubit_text, gate = value.split(":", maxsplit=1)
        qubit = int(qubit_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "fault must use QUBIT:GATE format, for example 5:Z for D5"
        ) from error
    gate = gate.upper()
    if not 1 <= qubit <= 9 or gate not in {"X", "Y", "Z"}:
        raise argparse.ArgumentTypeError("fault must be D1..D9 (1-9) with X, Y or Z")
    return qubit - 1, gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Live surface-code memory (default) or replay of a saved run (--history)."
    )
    parser.add_argument(
        "--history",
        type=Path,
        help="replay an existing JSON run instead of starting a new simulation",
    )
    parser.add_argument(
        "--fault",
        type=parse_fault,
        action="append",
        default=[],
        metavar="QUBIT:GATE",
        help="inject a fault at the start (repeatable)",
    )
    parser.add_argument("--interval", type=int, default=500, help="milliseconds per step while playing")
    parser.add_argument("--seed", type=int, default=1, help="Aer seed (keeps re-runs consistent)")
    parser.add_argument("--no-led", action="store_true", help="don't connect to the LED panel")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.interval < 1:
        raise SystemExit("--interval must be at least 1")

    if args.history is None:
        # Live mode: real step-by-step simulation, writes LED frames.
        from Data_Log.Pico_Link import PicoLink
        from Live_visualizer import LiveVisualizer

        led = None if args.no_led else PicoLink()
        app = LiveVisualizer(args.interval, args.seed, "data_to_pico", args.fault, led=led)
        plt.show()
        return app

    visualizer = CircuitVisualizer("Surface-code circuit replay")
    history_path = args.history.expanduser().resolve()
    if not history_path.is_file():
        raise FileNotFoundError(f"Simulation history not found: {history_path}")
    animation = animate_rounds(visualizer, history_path, interval=args.interval, repeat=False)
    print(f"Replaying saved simulation: {history_path}")
    # Keep a reference alive until the GUI event loop finishes.
    visualizer.animation = animation
    plt.show()


if __name__ == "__main__":
    main()
