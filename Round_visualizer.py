import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Button

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
        self.corrected_data: set[int] = set()
        self.reacting_z_checks: set[int] = set()
        self.reacting_x_checks: set[int] = set()
        self.active_basis: str | None = None
        self.check_outcomes: list[int] = []
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
            if index in self.corrected_data:
                self.ax.add_patch(
                    Circle(
                        center,
                        0.27,
                        facecolor="none",
                        edgecolor="#2E9E4F",
                        linewidth=2,
                        zorder=2,
                    )
                )
            self.ax.text(
                *center, str(index), ha="center", va="center", color="white", zorder=3
            )

    def place_z_stabilizers(self):
        self._place_stabilizers(
            Z_POSITIONS,
            self.reacting_z_checks,
            "#1E88E5",
            "Z",
            Z_CHECK_SUPPORTS,
            self.check_outcomes if self.active_basis == "Z" else [],
        )

    def place_x_stabilizers(self):
        self._place_stabilizers(
            X_POSITIONS,
            self.reacting_x_checks,
            "#FB8C00",
            "X",
            X_CHECK_SUPPORTS,
            self.check_outcomes if self.active_basis == "X" else [],
        )

    def _place_stabilizers(self, positions, reacting, color, basis, supports, outcomes):
        for index, position in enumerate(positions):
            fill = FAULT_COLOR if index in reacting else color
            self.ax.add_patch(Circle(position, 0.15, color=fill, zorder=2))
            if index < len(outcomes):
                label = "+1" if outcomes[index] == 0 else "-1"
            else:
                label = basis
            self.ax.text(
                *position,
                label,
                ha="center",
                va="center",
                color="white",
                fontsize=6 if label != basis else 7,
                fontweight="bold",
                zorder=3,
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
        if "phase" in step:
            self.show_round_step(step, frame_index, total_frames)
            return
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

    def show_round_step(self, step, frame_index, total_frames):
        self.current_step = step
        self.active_data.clear()
        self.active_basis = None
        self.check_outcomes = []
        self.faulted_data = {
            fault["qubit"]
            for fault in step.get("faults", [])
            if isinstance(fault.get("qubit"), int)
            and 0 <= fault["qubit"] < len(DATA_POSITIONS)
        }
        self.corrected_data = {
            correction["qubit"]
            for correction in step.get("corrections", [])
            if isinstance(correction.get("qubit"), int)
            and 0 <= correction["qubit"] < len(DATA_POSITIONS)
        }
        syndromes = step.get("syndromes", {})
        self.reacting_x_checks = set(syndromes.get("X", []))
        self.reacting_z_checks = set(syndromes.get("Z", []))
        phase_basis = {"X checks": "X", "Z checks": "Z"}.get(step.get("phase"))
        self.active_basis = phase_basis
        outcomes = step.get("outcomes", {})
        self.check_outcomes = outcomes.get(phase_basis, []) if phase_basis else []
        self.redraw()
        self.ax.set_title(
            f"Round {step.get('round', '?')} | Step {frame_index + 1}/{total_frames}: "
            f"{step['phase']}",
            fontsize=11,
        )
        self.fig.canvas.draw_idle()

    def show_circuit_step(self, step, frame_index, total_frames):
        """Render the complete Qiskit circuit prefix stored for this step."""
        self.current_step = step
        diagram = step.get("diagram")
        if not isinstance(diagram, str) or not diagram:
            circuit = step.get("circuit")
            operations = circuit.get("operations") if isinstance(circuit, dict) else None
            if not isinstance(operations, list):
                raise ValueError("recorded step must include a circuit diagram")
            diagram = "\n".join(
                f"{operation.get('operation', 'unknown')} "
                f"q={operation.get('qubits', [])} "
                f"c={operation.get('classical_bits', [])}"
                for operation in operations
            )

        self.ax.clear()
        self.active_basis = None
        self.check_outcomes = []
        self.faulted_data.clear()
        self.active_data.clear()
        self.corrected_data.clear()
        self.reacting_x_checks.clear()
        self.reacting_z_checks.clear()
        self.ax.axis("off")
        lines = diagram.splitlines() or [diagram]
        longest_line = max(map(len, lines))
        self.fig.set_size_inches(
            min(36, max(12, longest_line * 0.09)),
            min(24, max(6, len(lines) * 0.18)),
            forward=True,
        )
        self.ax.text(
            0.01,
            0.99,
            diagram,
            transform=self.ax.transAxes,
            va="top",
            ha="left",
            family="monospace",
            fontsize=max(4, min(9, 500 / max(longest_line, 1))),
        )
        operation = step.get("operation", step.get("kind", "circuit state"))
        fault = step.get("fault")
        detail = f" | fault {fault['gate']} on qubit {fault['qubit']}" if fault else ""
        self.ax.set_title(
            f"Round {step.get('round', '?')} | Step {frame_index + 1}/{total_frames}: "
            f"{operation}{detail}",
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


class StepPlayback:
    """Button-controlled playback of recorded round and circuit steps."""

    def __init__(self, visualizer, steps, interval):
        self.visualizer = visualizer
        self.steps = steps
        self.index = 0
        self.playing = False
        self.selected_qubit = 0
        self.selected_gate = "X"

        visualizer.fig.subplots_adjust(bottom=0.34)
        self.qubit_buttons = []
        for qubit in range(len(DATA_POSITIONS)):
            button_ax = visualizer.fig.add_axes(
                [0.075 + qubit * 0.1, 0.255, 0.075, 0.055]
            )
            button = Button(button_ax, f"D{qubit}")
            button.on_clicked(
                lambda _event, selected=qubit: self.select_qubit(selected)
            )
            self.qubit_buttons.append(button)

        self.gate_buttons = {}
        for index, gate in enumerate(("X", "Z", "H")):
            button_ax = visualizer.fig.add_axes([0.075 + index * 0.09, 0.16, 0.07, 0.06])
            button = Button(button_ax, gate)
            button.on_clicked(lambda _event, selected=gate: self.select_gate(selected))
            self.gate_buttons[gate] = button
        inject_ax = visualizer.fig.add_axes([0.36, 0.16, 0.14, 0.06])
        self.inject_button = Button(inject_ax, "Inject fault")
        self.inject_button.on_clicked(self.inject_fault)

        previous_ax = visualizer.fig.add_axes([0.55, 0.16, 0.12, 0.06])
        play_ax = visualizer.fig.add_axes([0.69, 0.16, 0.12, 0.06])
        next_ax = visualizer.fig.add_axes([0.83, 0.16, 0.12, 0.06])
        self.previous_button = Button(previous_ax, "Previous")
        self.play_button = Button(play_ax, "Play")
        self.next_button = Button(next_ax, "Next")
        self.previous_button.on_clicked(self.previous_step)
        self.play_button.on_clicked(self.toggle_play)
        self.next_button.on_clicked(self.next_step)

        self.timer = visualizer.fig.canvas.new_timer(interval=interval)
        self.timer.add_callback(self._advance_playback)
        self._update_selection_buttons()
        self.show_step()

    def select_qubit(self, qubit):
        self.selected_qubit = qubit
        self._update_selection_buttons()

    def select_gate(self, gate):
        self.selected_gate = gate
        self._update_selection_buttons()

    def _update_selection_buttons(self):
        for qubit, button in enumerate(self.qubit_buttons):
            button.ax.set_facecolor(
                "#A5D6A7" if qubit == self.selected_qubit else "0.95"
            )
        for gate, button in self.gate_buttons.items():
            button.ax.set_facecolor(
                "#FFCC80" if gate == self.selected_gate else "0.95"
            )
        self.visualizer.fig.canvas.draw_idle()

    def inject_fault(self, _event=None):
        current_step = self.steps[self.index]
        round_number = current_step.get("round")
        if current_step.get("phase") == "Reset":
            self.inject_button.label.set_text("Select a check step")
            return

        fault = {"qubit": self.selected_qubit, "gate": self.selected_gate}
        target_phase = {"X": "Z checks", "Z": "X checks"}.get(self.selected_gate)
        target_index = next(
            (
                step_index
                for step_index, step in enumerate(self.steps)
                if step_index > self.index
                and step.get("round") == round_number
                and step.get("phase") == target_phase
            ),
            None,
        )

        for step in self.steps[self.index :]:
            faults = step.setdefault("faults", [])
            if fault not in faults:
                faults.append(dict(fault))

        if target_index is not None:
            basis = "Z" if self.selected_gate == "X" else "X"
            supports = Z_CHECK_SUPPORTS if basis == "Z" else X_CHECK_SUPPORTS
            target_step = self.steps[target_index]
            syndrome = target_step.setdefault("syndromes", {}).setdefault(basis, [])
            for check_index, support in enumerate(supports):
                if self.selected_qubit in support:
                    if check_index in syndrome:
                        syndrome.remove(check_index)
                    else:
                        syndrome.append(check_index)
            syndrome.sort()
            decode_step = next(
                (
                    step
                    for step in self.steps[target_index + 1 :]
                    if step.get("round") == round_number
                    and step.get("phase") == "Decode"
                ),
                None,
            )
            if decode_step is not None:
                decode_step.setdefault("syndromes", {})[basis] = list(syndrome)
                self._update_decoder_correction(decode_step)

        self.inject_button.label.set_text(
            f"{self.selected_gate} fault on D{self.selected_qubit}"
        )
        self.show_step()

    @staticmethod
    def _update_decoder_correction(step):
        import numpy as np
        import pymatching

        def check_matrix(supports):
            matrix = np.zeros((len(supports), len(DATA_POSITIONS)), dtype=np.uint8)
            for check_index, support in enumerate(supports):
                matrix[check_index, list(support)] = 1
            return matrix

        syndrome_x = np.zeros(len(X_CHECK_SUPPORTS), dtype=np.uint8)
        syndrome_z = np.zeros(len(Z_CHECK_SUPPORTS), dtype=np.uint8)
        syndrome_x[step["syndromes"].get("X", [])] = 1
        syndrome_z[step["syndromes"].get("Z", [])] = 1
        correction_x = pymatching.Matching.from_check_matrix(
            check_matrix(Z_CHECK_SUPPORTS)
        ).decode(syndrome_z)
        correction_z = pymatching.Matching.from_check_matrix(
            check_matrix(X_CHECK_SUPPORTS)
        ).decode(syndrome_x)
        step["corrections"] = [
            {
                "qubit": qubit,
                "pauli": (
                    "Y"
                    if correction_x[qubit] and correction_z[qubit]
                    else "X"
                    if correction_x[qubit]
                    else "Z"
                ),
            }
            for qubit in range(len(DATA_POSITIONS))
            if correction_x[qubit] or correction_z[qubit]
        ]

    def show_step(self):
        step = self.steps[self.index]
        if step.get("phase"):
            self.visualizer.show_round_step(step, self.index, len(self.steps))
        elif step.get("diagram") or step.get("circuit"):
            self.visualizer.show_circuit_step(step, self.index, len(self.steps))
        else:
            faults = [
                fault
                for prior_step in self.steps[: self.index + 1]
                for fault in prior_step.get("faults", [])
            ]
            self.visualizer.show_step(step, self.index, len(self.steps), faults)
        self.previous_button.ax.set_facecolor(
            "0.85" if self.index == 0 else "0.95"
        )
        self.next_button.ax.set_facecolor(
            "0.85" if self.index == len(self.steps) - 1 else "0.95"
        )
        self.visualizer.fig.canvas.draw_idle()

    def previous_step(self, _event=None):
        self.timer.stop()
        self.playing = False
        self.play_button.label.set_text("Play")
        self.index = max(0, self.index - 1)
        self.show_step()

    def next_step(self, _event=None):
        self.timer.stop()
        self.playing = False
        self.play_button.label.set_text("Play")
        self.index = min(len(self.steps) - 1, self.index + 1)
        self.show_step()

    def toggle_play(self, _event=None):
        if self.playing:
            self.timer.stop()
            self.playing = False
            self.play_button.label.set_text("Play")
        else:
            if self.index == len(self.steps) - 1:
                self.index = 0
                self.show_step()
            self.playing = True
            self.play_button.label.set_text("Pause")
            self.timer.start()
        self.visualizer.fig.canvas.draw_idle()

    def _advance_playback(self):
        if self.index >= len(self.steps) - 1:
            self.timer.stop()
            self.playing = False
            self.play_button.label.set_text("Play")
            return False
        self.index += 1
        self.show_step()
        return True


def animate_rounds(visualizer, history, interval=10, repeat=False):
    """Replay stored circuit steps from history, a JSON file, or step list."""
    if isinstance(history, (str, Path)):
        with Path(history).open(encoding="utf-8") as file:
            history = json.load(file)
    elif hasattr(history, "get_history"):
        history = history.get_history()

    steps = history.get("steps") if isinstance(history, dict) else history
    if not steps and isinstance(history, dict):
        steps = history.get("circuit_structures")
    if not isinstance(steps, list) or not steps:
        raise ValueError(
            "history must contain non-empty recorded 'steps' or 'circuit_structures'"
        )
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
        fault = step.get("fault")
        if fault is not None and (
            not isinstance(fault, dict)
            or not isinstance(fault.get("qubit"), int)
            or fault.get("gate") not in {"X", "Z", "H"}
        ):
            raise ValueError("circuit-structure faults must contain an integer qubit and X, Z, or H gate")

    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise ValueError("interval must be a positive integer number of milliseconds")

    visualizer.animation = StepPlayback(visualizer, steps, interval)
    return visualizer.animation


if __name__ == "__main__":
    visualizer = CircuitVisualizer("Surface-code data and checks")
    visualizer.redraw()
    plt.show()