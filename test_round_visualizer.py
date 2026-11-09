import json
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from Round_visualizer import CircuitVisualizer, animate_rounds


class RoundVisualizerAnimationTests(unittest.TestCase):
    def setUp(self):
        self.visualizer = CircuitVisualizer("test circuit")

    def test_animation_replays_recorded_steps_and_accumulates_faults(self):
        history = {
            "steps": [
                {
                    "round": 1,
                    "operation": "fault_x",
                    "qubits": [0],
                    "faults": [{"qubit": 0, "gate": "X"}],
                },
                {"round": 1, "operation": "cx", "qubits": [1], "faults": []},
            ]
        }

        animation = animate_rounds(self.visualizer, history, interval=1)

        self.assertEqual(animation.save_count, 2)
        animation._func(0)
        self.assertEqual(self.visualizer.faulted_data, {0})
        self.assertEqual(self.visualizer.reacting_z_checks, {1})
        self.assertEqual(self.visualizer.active_data, {0})
        animation._func(1)
        self.assertEqual(self.visualizer.faulted_data, {0})
        self.assertEqual(self.visualizer.reacting_z_checks, {1})
        self.assertEqual(self.visualizer.active_data, {1})
        self.assertEqual(self.visualizer.current_step["operation"], "cx")

    def test_animation_reads_json_history_file(self):
        history = {
            "steps": [
                {"round": 2, "operation": "h", "qubits": [2], "faults": []}
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(history), encoding="utf-8")

            animation = animate_rounds(self.visualizer, path, interval=1)
            animation._func(0)

        self.assertEqual(self.visualizer.active_data, {2})
        self.assertIn("Round 2", self.visualizer.ax.get_title())

    def test_animation_rejects_malformed_fault_record(self):
        with self.assertRaises(ValueError):
            animate_rounds(
                self.visualizer,
                {"steps": [{"faults": [{"qubit": "bad", "gate": "X"}]}]},
            )


if __name__ == "__main__":
    unittest.main()
