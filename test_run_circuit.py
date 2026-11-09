import json
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from Data_Log.Experiment_Logger import ExperimentLogger
from Round_visualizer import CircuitVisualizer, animate_rounds
from Run_Circuit import build_round_steps
from Simulation_Logic import StepwiseSimulation, create_surface_code_circuit


class RoundPlaybackTests(unittest.TestCase):
    def run_simulation(self, gate):
        simulation = StepwiseSimulation()
        simulation.build_initial_circuit_state(create_surface_code_circuit(3))
        simulation.detect_event({"qubit": 0, "gate": gate})
        simulation.run_rounds(num_rounds=3, record_steps=False)
        history = simulation.get_history()
        history["steps"] = build_round_steps(history["rounds"], history["events"])
        return simulation, history

    def test_three_rounds_create_exactly_ten_semantic_steps(self):
        _, history = self.run_simulation("X")

        self.assertEqual(len(history["steps"]), 10)
        self.assertEqual(
            [step["phase"] for step in history["steps"]],
            ["X checks", "Z checks", "Decode"] * 3 + ["Reset"],
        )
        self.assertEqual(history["steps"][1]["syndromes"]["Z"], [0])
        self.assertEqual(history["steps"][0]["syndromes"]["X"], [])

    def test_z_fault_is_detected_by_adjacent_x_check(self):
        _, history = self.run_simulation("Z")

        self.assertEqual(history["steps"][0]["syndromes"]["X"], [1])
        self.assertEqual(history["steps"][1]["syndromes"]["Z"], [])

    def test_saved_history_replays_on_grid_and_resets_at_last_step(self):
        simulation, history = self.run_simulation("X")
        with tempfile.TemporaryDirectory() as directory:
            path = ExperimentLogger(directory).log_experiment(history)
            saved = json.loads(Path(path).read_text(encoding="utf-8"))
            visualizer = CircuitVisualizer("test")
            animation = animate_rounds(visualizer, saved, interval=1)
            self.assertEqual(len(animation.steps), 10)
            self.assertEqual(animation.index, 0)

            animation.next_button._observers.process("clicked", None)
            self.assertEqual(visualizer.reacting_z_checks, {0})
            self.assertEqual(visualizer.faulted_data, {0})
            self.assertEqual(visualizer.ax.get_xlim(), (-0.25, 3.25))
            self.assertEqual(visualizer.active_basis, "Z")
            self.assertEqual(len(visualizer.check_outcomes), 4)

            for _ in range(8):
                animation.next_button._observers.process("clicked", None)
            self.assertEqual(visualizer.faulted_data, set())
            self.assertEqual(visualizer.reacting_z_checks, set())
            self.assertEqual(visualizer.current_step["phase"], "Reset")
            self.assertEqual(animation.index, 9)

            animation.previous_button._observers.process("clicked", None)
            self.assertEqual(animation.index, 8)
            self.assertEqual(visualizer.current_step["phase"], "Decode")
            plt.close(visualizer.fig)

        self.assertEqual(simulation.steps, [])

    def test_qubit_and_fault_buttons_update_future_ancilla_indicators(self):
        _, history = self.run_simulation("X")
        visualizer = CircuitVisualizer("test")
        playback = animate_rounds(visualizer, history, interval=1)

        playback.qubit_buttons[2]._observers.process("clicked", None)
        playback.gate_buttons["Z"]._observers.process("clicked", None)
        playback.inject_button._observers.process("clicked", None)

        self.assertIn({"qubit": 2, "gate": "Z"}, playback.steps[0]["faults"])
        for _ in range(3):
            playback.next_button._observers.process("clicked", None)

        self.assertEqual(visualizer.current_step["phase"], "X checks")
        self.assertEqual(visualizer.reacting_x_checks, {0})
        self.assertEqual(visualizer.active_basis, "X")
        self.assertEqual(len(visualizer.check_outcomes), 4)
        self.assertEqual(visualizer.faulted_data, {0, 2})
        self.assertEqual(
            playback.steps[5]["syndromes"]["X"],
            [0],
        )
        self.assertIn({"qubit": 2, "pauli": "Z"}, playback.steps[5]["corrections"])
        plt.close(visualizer.fig)


if __name__ == "__main__":
    unittest.main()
