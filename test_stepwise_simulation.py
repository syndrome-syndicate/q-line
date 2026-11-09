import json
import tempfile
import unittest
from pathlib import Path

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from Data_Log.Experiment_Logger import ExperimentLogger
from Simulation_Logic.Stepwise_simulation import StepwiseSimulation
from Simulation_Logic.circuits import create_surface_code_circuit


class StepwiseSimulationTests(unittest.TestCase):
    @staticmethod
    def make_two_round_circuit():
        data = QuantumRegister(1, "data")
        ancilla = QuantumRegister(1, "ancilla_z")
        outcomes = ClassicalRegister(2, "classical_z")
        circuit = QuantumCircuit(data, ancilla, outcomes)
        for round_index in range(2):
            circuit.barrier(label=f"round_{round_index}_start")
            circuit.cx(data[0], ancilla[0])
            circuit.measure(ancilla[0], outcomes[round_index])
            circuit.reset(ancilla[0])
        return circuit

    def test_records_full_prefix_and_faulted_round_measurements(self):
        circuit = self.make_two_round_circuit()
        simulation = StepwiseSimulation()
        simulation.build_initial_circuit_state(circuit)
        simulation.detect_event(
            {
                "change": {"control": "qubit_button", "index": 0},
                "state": {"error_selector": "X"},
            }
        )

        steps = simulation.run_rounds(num_rounds=2, shots=2)

        self.assertEqual(len(steps), len(circuit.data) + 1)
        self.assertEqual(steps[0]["faults"], [{"qubit": 0, "gate": "X"}])
        self.assertIn("x", steps[0]["diagram"].lower())
        self.assertEqual(len(simulation.get_history()["events"]), 1)
        self.assertEqual([round_data["round"] for round_data in simulation.rounds], [1, 2])
        structures = simulation.get_circuit_structures()
        self.assertEqual(
            [(structure["kind"], structure["round"]) for structure in structures],
            [("injection", 1), ("round", 1), ("round", 2)],
        )
        self.assertEqual(
            structures[0]["circuit"]["operations"][-1]["operation"], "x"
        )
        self.assertEqual(
            structures[0]["circuit"]["operations"][-1]["qubits"], [0]
        )
        self.assertTrue(structures[1]["circuit"]["operations"])
        self.assertEqual(
            [round_data["checks"][0]["outcomes"] for round_data in simulation.rounds],
            [[1, 1], [1, 1]],
        )

    def test_builder_allocates_classical_bits_for_each_round(self):
        circuit = create_surface_code_circuit(num_rounds=2)

        self.assertEqual(len(circuit.cregs[0]), 24)
        self.assertEqual(len(circuit.cregs[1]), 24)
        self.assertEqual(
            sum(instruction.operation.name == "barrier" for instruction in circuit.data),
            6,
        )

    def test_logger_persists_every_step_and_round(self):
        simulation = StepwiseSimulation()
        simulation.build_initial_circuit_state(self.make_two_round_circuit())
        simulation.run_rounds(num_rounds=2)

        with tempfile.TemporaryDirectory() as directory:
            logger = ExperimentLogger(directory)
            log_file = logger.log_simulation(simulation)
            with Path(log_file).open(encoding="utf-8") as file:
                saved_history = json.load(file)

        self.assertEqual(len(saved_history["steps"]), len(simulation.steps))
        self.assertEqual(saved_history["rounds"], simulation.rounds)
        self.assertEqual(saved_history["events"], simulation.events)
        self.assertEqual(
            saved_history["circuit_structures"], simulation.circuit_structures
        )
        self.assertTrue(saved_history["steps"][-1]["diagram"])

    def test_fault_event_rejects_invalid_qubit(self):
        simulation = StepwiseSimulation()
        simulation.build_initial_circuit_state(self.make_two_round_circuit())

        with self.assertRaises(ValueError):
            simulation.detect_event({"qubit": 2, "gate": "X"})

    def test_button_release_does_not_inject_a_second_fault(self):
        simulation = StepwiseSimulation()
        simulation.build_initial_circuit_state(self.make_two_round_circuit())
        simulation.detect_event(
            {
                "change": {
                    "control": "qubit_button",
                    "index": 0,
                    "action": "released",
                },
                "state": {"error_selector": "X"},
            }
        )

        steps = simulation.run_rounds(num_rounds=2)

        self.assertEqual(len(steps), 8)
        self.assertTrue(all(not step["faults"] for step in steps))


if __name__ == "__main__":
    unittest.main()
