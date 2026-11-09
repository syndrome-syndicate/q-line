import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Circle
import matplotlib.animation as animation

DATA_POSITIONS = [(column + 0.5, row + 0.5) for row in range(3) for column in range(3)]
Z_POSITIONS = [(0, 2), (1, 1), (2, 2), (3, 1)]
X_POSITIONS = [(1, 0), (1, 2), (2, 1), (2, 3)]

# Data-qubit indices adjacent to each check on the 3x3 rotated surface-code patch.
Z_CHECK_SUPPORTS = [(3, 6), (0, 1, 3, 4), (4, 5, 7, 8), (2, 5)]
X_CHECK_SUPPORTS = [(0, 1), (3, 4, 6, 7), (1, 2, 4, 5), (7, 8)]
FAULT_COLOR = "red"


class CircuitVisualizer:
    def __init__(self, circuit):
        self.circuit = circuit
        self.fig, self.ax = plt.subplots()
        self.faulted_data: set[int] = set()
        self.active_data: set[int] = set()
        self.reacting_z_checks: set[int] = set()
        self.reacting_x_checks: set[int] = set()
        self.animation = None
        self.current_step = None

    def setup_board(self):
        self.ax.clear()
        for coordinate in (1, 2):
            self.ax.axhline(coordinate, color="black", linewidth=0.5)
            self.ax.axvline(coordinate, color="black", linewidth=0.5)
        self.ax.set_xlim(-0.25, 3.25)
        self.ax.set_ylim(3.25, -0.25)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.set_aspect("equal")
        self.ax.set_title(f"{self.circuit}", fontsize=16, fontweight="bold")

    def place_data_qubits(self):
        for index, center in enumerate(DATA_POSITIONS):
            color = (
                FAULT_COLOR
                if index in self.faulted_data
                else "#4FC3F7" if index in self.active_data else "grey"
            )
            self.ax.add_patch(Circle(center, 0.22, color=color, zorder=2))
            self.ax.text(
                *center, str(index), ha="center", va="center", color="white", zorder=3
            )

    def place_z_stabilizers(self):
        self._place_stabilizers(
            Z_POSITIONS, self.reacting_z_checks, "#1E88E5", "Z", Z_CHECK_SUPPORTS
        )

    def place_x_stabilizers(self):
        self._place_stabilizers(
            X_POSITIONS, self.reacting_x_checks, "#FB8C00", "X", X_CHECK_SUPPORTS
        )

    def _place_stabilizers(self, positions, reacting, color, basis, supports):
        for index, position in enumerate(positions):
            fill = FAULT_COLOR if index in reacting else color
            self.ax.add_patch(Circle(position, 0.15, color=fill, zorder=2))
            self.ax.text(
                *position, basis, ha="center", va="center", color="white",
                fontsize=7, zorder=3
            )
            for data_index in supports[index]:
                data_position = DATA_POSITIONS[data_index]
                self.ax.plot(
                    [position[0], data_position[0]],
                    [position[1], data_position[1]],
                    color=color,
                    linewidth=0.6,
                    alpha=0.45,
                    zorder=1,
                )

    def apply_event(self, event_data: dict) -> None:
        """Apply an X/Z/Y/H fault and redraw the targeted data qubit and checks."""
        if not isinstance(event_data, dict):
            raise TypeError("event_data must be a dictionary")

        change = event_data.get("change")
        state = event_data.get("state")
        change = change if isinstance(change, dict) else {}
        state = state if isinstance(state, dict) else {}
        if change.get("control") == "qubit_button" and change.get("action") not in (
            None,
            "pressed",
        ):
            return

        qubit = change.get("index", event_data.get("qubit"))
        if qubit is None:
            location = event_data.get("qubit_location")
            if isinstance(location, str) and location.startswith("qubit_"):
                qubit = location.removeprefix("qubit_")
        try:
            qubit = int(qubit)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Fault event must identify a data-qubit index from 0 to 8"
            ) from error
        if not 0 <= qubit < len(DATA_POSITIONS):
            raise ValueError(f"Data-qubit index {qubit} is outside the range 0 to 8")

        gate = (
            state.get("error_selector")
            or event_data.get("gate")
            or event_data.get("error_selector")
            or event_data.get("classification")
            or event_data.get("type")
        )
        if not isinstance(gate, str):
            raise ValueError("Fault event must specify an X, Z, Y, or H gate")
        gate = gate.upper().split(".")[-1]
        if gate not in {"X", "Z", "Y", "H"}:
            raise ValueError(f"Unsupported fault type: {gate}")

        self.faulted_data.add(qubit)
        if gate == "X":
            self._toggle_adjacent_checks(qubit, Z_CHECK_SUPPORTS, self.reacting_z_checks)
        elif gate == "Z":
            self._toggle_adjacent_checks(qubit, X_CHECK_SUPPORTS, self.reacting_x_checks)

        self.redraw()

    def show_step(self, step, frame_index, total_frames, faults):
        self.current_step = step
        self.faulted_data.clear()
        self.active_data = {
            qubit
            for qubit in step.get("qubits", [])
            if isinstance(qubit, int) and 0 <= qubit < len(DATA_POSITIONS)
        }
        self.reacting_z_checks.clear()
        self.reacting_x_checks.clear()
        for fault in faults:
            qubit = fault["qubit"]
            if 0 <= qubit < len(DATA_POSITIONS):
                self.faulted_data.add(qubit)
                if fault["gate"] == "X":
                    self._toggle_adjacent_checks(
                        qubit, Z_CHECK_SUPPORTS, self.reacting_z_checks
                    )
                elif fault["gate"] == "Z":
                    self._toggle_adjacent_checks(
                        qubit, X_CHECK_SUPPORTS, self.reacting_x_checks
                    )

        self.redraw()
        operation = step.get("operation", "unknown")
        qubits = step.get("qubits", [])
        self.ax.set_title(
            f"Round {step.get('round', '?')} | Step {frame_index + 1}/{total_frames}: "
            f"{operation} {qubits}",
            fontsize=11,
        )
        self.fig.canvas.draw_idle()

    @staticmethod
    def _toggle_adjacent_checks(qubit, supports, reacting):
        for check_index, support in enumerate(supports):
            if qubit in support:
                if check_index in reacting:
                    reacting.remove(check_index)
                else:
                    reacting.add(check_index)

    def redraw(self):
        self.setup_board()
        self.place_data_qubits()
        self.place_z_stabilizers()
        self.place_x_stabilizers()
        self.fig.canvas.draw_idle()


def animate_rounds(visualizer, history, interval=500, repeat=False):
    """Animate recorded simulation steps from history, a JSON file, or step list."""
    if isinstance(history, (str, Path)):
        with Path(history).open(encoding="utf-8") as file:
            history = json.load(file)
    elif hasattr(history, "get_history"):
        history = history.get_history()

    steps = history.get("steps") if isinstance(history, dict) else history
    if not isinstance(steps, list) or not steps:
        raise ValueError("history must contain a non-empty 'steps' list")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("every recorded step must be a dictionary")
        if not isinstance(step.get("faults", []), list):
            raise ValueError("each step's faults field must be a list")
        for fault in step.get("faults", []):
            if (
                not isinstance(fault, dict)
                or not isinstance(fault.get("qubit"), int)
                or fault.get("gate") not in {"X", "Z", "H"}
            ):
                raise ValueError("faults must contain an integer qubit and X, Z, or H gate")

    def update(frame_index):
        faults = [
            fault
            for step in steps[: frame_index + 1]
            for fault in step.get("faults", [])
        ]
        visualizer.show_step(steps[frame_index], frame_index, len(steps), faults)
        return tuple(visualizer.ax.patches) + tuple(visualizer.ax.texts)

    visualizer.animation = FuncAnimation(
        visualizer.fig,
        update,
        frames=len(steps),
        interval=interval,
        repeat=repeat,
        blit=False,
    )
    return visualizer.animation


if __name__ == "__main__":
    visualizer = CircuitVisualizer("Surface-code data and checks")
    visualizer.redraw()
    plt.show()
