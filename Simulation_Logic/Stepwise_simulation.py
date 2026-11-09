"""
Record and simulate a Qiskit circuit one instruction at a time.

Each history entry contains a diagram of the complete circuit prefix, and
measurement outcomes are grouped by syndrome-extraction round.
"""

from __future__ import annotations

import json
import re
from threading import Lock
from typing import Any

from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator

from .fault_injection import inject_fault


class CircuitDiagram:
    def __init__(self, circuit: QuantumCircuit):
        self.circuit = circuit

    def count(self, event_type: str | None = None) -> int:
        if event_type is None:
            return len(self.circuit.data)
        return int(self.circuit.count_ops().get(event_type, 0))

    def draw(self) -> str:
        diagram = str(self.circuit.draw(output="text"))
        print(diagram)
        return diagram


class StepwiseSimulation:
    """Capture circuit-prefix diagrams, syndrome measurements, and faults."""

    def __init__(self):
        self.circuit: QuantumCircuit | None = None
        self.circuit_state: QuantumCircuit | None = None
        self.events: list[Any] = []
        self.steps: list[dict[str, Any]] = []
        self.rounds: list[dict[str, Any]] = []
        self.circuit_structures: list[dict[str, Any]] = []
        self._pending_faults: list[dict[str, Any]] = []
        self._next_step_index = 0
        self._fault_lock = Lock()

    def build_initial_circuit_state(self, circuit: QuantumCircuit) -> None:
        if not isinstance(circuit, QuantumCircuit):
            raise TypeError("circuit must be a qiskit.QuantumCircuit")
        self.circuit = circuit
        self.circuit_state = circuit.copy_empty_like()
        self.events.clear()
        self.steps.clear()
        self.rounds.clear()
        self.circuit_structures.clear()
        with self._fault_lock:
            self._pending_faults.clear()
        self._next_step_index = 0

    def run_rounds(
        self,
        num_rounds: int = 4,
        shots: int = 1,
        record_steps: bool = True,
    ) -> list[dict[str, Any]]:
        """Record up to ``num_rounds`` and run the resulting circuit for syndromes."""
        if self.circuit is None:
            raise RuntimeError("Build a circuit state before running the simulation")
        if not isinstance(num_rounds, int) or isinstance(num_rounds, bool):
            raise TypeError("num_rounds must be an integer")
        if num_rounds < 1:
            raise ValueError("num_rounds must be at least 1")
        if not isinstance(shots, int) or isinstance(shots, bool):
            raise TypeError("shots must be an integer")
        if shots < 1:
            raise ValueError("shots must be at least 1")
        if not isinstance(record_steps, bool):
            raise TypeError("record_steps must be a boolean")

        self.circuit_state = self.circuit.copy_empty_like()
        self.steps.clear()
        self.rounds.clear()
        self.circuit_structures.clear()
        self._next_step_index = 0
        round_index = 1
        completed_rounds: set[int] = set()
        marked_rounds = any(
            instruction.operation.name == "barrier"
            and re.fullmatch(r"round_\d+_start", instruction.operation.label or "")
            for instruction in self.circuit.data
        )

        for instruction in self.circuit.data:
            label = instruction.operation.label or ""
            round_start = re.fullmatch(r"round_(\d+)_start", label)
            if round_start:
                next_round = int(round_start.group(1)) + 1
                if next_round > num_rounds:
                    break
                if round_index not in completed_rounds and self.steps:
                    self._record_circuit_structure("round", round_index)
                    completed_rounds.add(round_index)
                round_index = next_round
            elif not marked_rounds and instruction.operation.name == "barrier":
                if self.steps:
                    if round_index not in completed_rounds:
                        self._record_circuit_structure("round", round_index)
                        completed_rounds.add(round_index)
                    round_index += 1
                    if round_index > num_rounds:
                        break

            faults = (
                self._apply_scheduled_faults(round_index)
                if not marked_rounds or round_start
                else []
            )
            if record_steps:
                self._record_fault_steps(faults, round_index)

            qubit_indices = [
                self.circuit.find_bit(qubit).index for qubit in instruction.qubits
            ]
            clbit_indices = [
                self.circuit.find_bit(clbit).index for clbit in instruction.clbits
            ]
            self.circuit_state.append(
                instruction.operation,
                [self.circuit_state.qubits[index] for index in qubit_indices],
                [self.circuit_state.clbits[index] for index in clbit_indices],
            )

            if record_steps:
                diagram = str(self.circuit_state.draw(output="text"))
                self.steps.append(
                    {
                        "step": self._next_step_index,
                        "round": round_index,
                        "operation": instruction.operation.name,
                        "qubits": qubit_indices,
                        "classical_bits": clbit_indices,
                        "faults": [],
                        "diagram": diagram,
                    }
                )
            self._record_measurements(instruction, round_index)
            if record_steps and re.fullmatch(r"round_\d+_end", label):
                self._record_circuit_structure("round", round_index)
                completed_rounds.add(round_index)
            self._next_step_index += 1

        final_faults = self._apply_scheduled_faults(round_index)
        if record_steps:
            self._record_fault_steps(final_faults, round_index)
        if record_steps and self.steps and round_index not in completed_rounds:
            self._record_circuit_structure("round", round_index)
        self._simulate_measurements(shots)
        return self.steps

    def detect_event(self, event_data: Any) -> None:
        """Receive an event and schedule supported X/Z/H faults for the next step."""
        if not isinstance(event_data, dict):
            self.events.append(event_data)
            return

        change = event_data.get("change", {})
        state = event_data.get("state", {})
        qubit = event_data.get("qubit")
        gate = event_data.get("gate")
        if isinstance(change, dict) and change.get("control") == "qubit_button":
            if change.get("action") not in (None, "pressed"):
                self.events.append(event_data)
                return
            qubit = change.get("index", qubit)
        if isinstance(state, dict):
            gate = state.get("error_selector", gate)
        if qubit is None and gate is None:
            self.events.append(event_data)
            return
        if not isinstance(qubit, int) or isinstance(qubit, bool):
            raise ValueError("Fault events must identify an integer qubit index")
        if not isinstance(gate, str) or gate not in {"X", "Z", "H"}:
            raise ValueError("Fault events must select one of X, Z, or H")
        if self.circuit is not None and not 0 <= qubit < self.circuit.num_qubits:
            raise ValueError(f"Fault qubit index {qubit} is outside the circuit")

        fault = {"qubit": qubit, "gate": gate}
        with self._fault_lock:
            self.events.append(event_data)
            self._pending_faults.append(fault)

    def _apply_scheduled_faults(self, round_index: int) -> list[dict[str, Any]]:
        with self._fault_lock:
            faults, self._pending_faults = self._pending_faults, []
        if self.circuit_state is None:
            if faults:
                raise RuntimeError("Build a circuit state before injecting faults")
            return []
        applied = []
        for fault in faults:
            qubit = fault["qubit"]
            if not 0 <= qubit < self.circuit_state.num_qubits:
                raise ValueError(f"Fault qubit index {qubit} is outside the circuit")
            inject_fault(self.circuit_state, qubit, fault["gate"])
            applied.append(dict(fault))
            self._record_circuit_structure(
                "injection",
                round_index,
                fault=dict(fault),
                step=self._next_step_index + len(applied) - 1,
            )
        return applied

    def _record_fault_steps(
        self, faults: list[dict[str, Any]], round_index: int
    ) -> None:
        if self.circuit_state is None:
            return
        for fault in faults:
            self.steps.append(
                {
                    "step": self._next_step_index,
                    "round": round_index,
                    "operation": f"fault_{fault['gate'].lower()}",
                    "qubits": [fault["qubit"]],
                    "classical_bits": [],
                    "faults": [fault],
                    "diagram": str(self.circuit_state.draw(output="text")),
                }
            )
            self._next_step_index += 1

    def _record_circuit_structure(
        self,
        kind: str,
        round_index: int,
        fault: dict[str, Any] | None = None,
        step: int | None = None,
    ) -> None:
        if self.circuit_state is None:
            return
        structure = {
            "kind": kind,
            "round": round_index,
            "step": self._next_step_index if step is None else step,
            "fault": fault,
            "circuit": self._serialize_circuit(self.circuit_state),
            "diagram": str(self.circuit_state.draw(output="text")),
        }
        self.circuit_structures.append(structure)

    @staticmethod
    def _serialize_circuit(circuit: QuantumCircuit) -> dict[str, Any]:
        operations = []
        for instruction in circuit.data:
            operations.append(
                {
                    "operation": instruction.operation.name,
                    "label": instruction.operation.label,
                    "qubits": [
                        circuit.find_bit(qubit).index for qubit in instruction.qubits
                    ],
                    "classical_bits": [
                        circuit.find_bit(clbit).index for clbit in instruction.clbits
                    ],
                    "parameters": [
                        parameter
                        if isinstance(parameter, (str, int, float, bool, type(None)))
                        else str(parameter)
                        for parameter in instruction.operation.params
                    ],
                }
            )
        return {
            "num_qubits": circuit.num_qubits,
            "num_clbits": circuit.num_clbits,
            "quantum_registers": [
                {"name": register.name, "size": len(register)}
                for register in circuit.qregs
            ],
            "classical_registers": [
                {"name": register.name, "size": len(register)}
                for register in circuit.cregs
            ],
            "operations": operations,
        }

    def _record_measurements(self, instruction: Any, round_index: int) -> None:
        if instruction.operation.name != "measure" or self.circuit is None:
            return
        while len(self.rounds) < round_index:
            self.rounds.append({"round": len(self.rounds) + 1, "checks": []})

        qubit = instruction.qubits[0]
        clbit = instruction.clbits[0]
        qubit_registers = self.circuit.find_bit(qubit).registers
        classical_registers = self.circuit.find_bit(clbit).registers
        qubit_register, qubit_position = qubit_registers[0]
        classical_register, classical_position = classical_registers[0]
        basis = self._measurement_basis(qubit_register.name, classical_register.name)
        checks_per_round = self._checks_per_round(basis)
        check_index = (
            qubit_position
            if qubit_register.name.startswith("ancilla_")
            else classical_position % checks_per_round
        )
        self.rounds[round_index - 1]["checks"].append(
            {
                "basis": basis,
                "check": check_index,
                "qubit": self.circuit.find_bit(qubit).index,
                "classical_bit": self.circuit.find_bit(clbit).index,
                "outcomes": [],
            }
        )

    @staticmethod
    def _measurement_basis(qubit_register: str, classical_register: str) -> str:
        register_names = f"{qubit_register}_{classical_register}".lower()
        if "_x" in register_names:
            return "X"
        if "_z" in register_names:
            return "Z"
        return "unknown"

    def _checks_per_round(self, basis: str) -> int:
        if self.circuit is None:
            return 1
        register_name = f"ancilla_{basis.lower()}"
        for register in self.circuit.qregs:
            if register.name == register_name:
                return len(register)
        return 1

    def _simulate_measurements(self, shots: int) -> None:
        if self.circuit_state is None or not self.circuit_state.num_clbits:
            return
        result = AerSimulator(method="stabilizer").run(
            self.circuit_state, shots=shots, memory=True
        ).result()
        memories = result.get_memory()
        for round_data in self.rounds:
            for check in round_data["checks"]:
                bit_index = check["classical_bit"]
                check["outcomes"] = [
                    int(memory.replace(" ", "")[-1 - bit_index])
                    for memory in memories
                ]

    def get_history(self) -> dict[str, Any]:
        """Return JSON-serializable step and syndrome history."""
        return {
            "circuit_structures": self.circuit_structures,
            "events": self.events,
            "rounds": self.rounds,
            "steps": self.steps,
        }

    def get_circuit_structures(self) -> list[dict[str, Any]]:
        """Return full circuit-prefix structures captured per round and fault."""
        return self.circuit_structures
