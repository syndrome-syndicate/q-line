"""
Live distance-3 surface-code memory, one QEC step at a time.

Uses the layout and check circuits from ``circuits.py``. Every step is a real
Qiskit circuit run on the Aer stabilizer simulator, and the 17-qubit state is
carried from one step to the next (save_stabilizer -> set_stabilizer), so
injected errors stay on the qubits until the decoder's correction removes them.

    X checks  ->  Z checks  ->  Decode + correct  ->  (repeat)

Decoding is MWPM (PyMatching). The correction is applied to the simulated
state, and the residual error (injected + corrections) is tracked to flag
logical failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pymatching
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.quantum_info import Pauli
from qiskit_aer import AerSimulator

from .circuits import (
    X_CHECK_SUPPORTS,
    Z_CHECK_SUPPORTS,
    append_x_checks,
    data_label,
    append_z_checks,
    prepare_logical_zero,
)

STEPS = ("X checks", "Z checks", "Decode + correct")
PAULIS = ("X", "Y", "Z")
# Logical operators of this layout (each commutes with every check).
LOGICAL_Z = (0, 1, 2)  # top row, D1 D2 D3
LOGICAL_X = (0, 3, 6)  # left column, D1 D4 D7
NUM_DATA = 9


def _check_matrix(supports) -> np.ndarray:
    matrix = np.zeros((len(supports), NUM_DATA), dtype=np.uint8)
    for check_index, support in enumerate(supports):
        matrix[check_index, list(support)] = 1
    return matrix


def compose_pauli(a: str | None, b: str | None) -> str | None:
    """Multiply single-qubit Paulis, ignoring phase."""
    bits = {None: (0, 0), "X": (1, 0), "Z": (0, 1), "Y": (1, 1)}
    x = bits[a][0] ^ bits[b][0]
    z = bits[a][1] ^ bits[b][1]
    return {(0, 0): None, (1, 0): "X", (0, 1): "Z", (1, 1): "Y"}[(x, z)]


@dataclass
class StepResult:
    """What happened during one step, for the UI and the LED frames."""

    step: str
    cycle: int
    # Raw ancilla outcomes per basis (0 -> +1, 1 -> -1)
    outcomes: dict[str, list[int]] = field(default_factory=dict)
    # Detection events per basis (check differs from its expected value)
    detections: dict[str, list[int]] = field(default_factory=dict)
    # Checks flagged earlier in this cycle and not yet decoded, per basis
    pending: dict[str, list[int]] = field(default_factory=dict)
    # Decoder correction {data qubit: "X" | "Y" | "Z"}
    correction: dict[int, str] = field(default_factory=dict)
    message: str = ""


class SurfaceCodeMemory:
    """A d=3 rotated surface code idling as a quantum memory in |0_L>."""

    def __init__(self, seed: int | None = None):
        self.data = QuantumRegister(NUM_DATA, "data")
        self.ancilla_x = QuantumRegister(len(X_CHECK_SUPPORTS), "ancilla_x")
        self.ancilla_z = QuantumRegister(len(Z_CHECK_SUPPORTS), "ancilla_z")
        self.hx = _check_matrix(X_CHECK_SUPPORTS)
        self.hz = _check_matrix(Z_CHECK_SUPPORTS)
        # Z checks see X errors; X checks see Z errors.
        self.match_z = pymatching.Matching.from_check_matrix(self.hz)
        self.match_x = pymatching.Matching.from_check_matrix(self.hx)
        self.sim = AerSimulator(method="stabilizer", seed_simulator=seed)
        self.state = None
        self.reset()

    # ------------------------------------------------------------ simulation
    def _circuit(self, num_bits: int = 0) -> QuantumCircuit:
        circuit = QuantumCircuit(self.data, self.ancilla_x, self.ancilla_z)
        if num_bits:
            circuit.add_register(ClassicalRegister(num_bits, "m"))
        if self.state is not None:
            circuit.set_stabilizer(self.state)
        return circuit

    def _run(self, circuit: QuantumCircuit) -> list[int] | None:
        """Run one shot on Aer and keep the post-measurement state."""
        circuit.save_stabilizer(label="state")
        result = self.sim.run(circuit, shots=1, memory=True).result()
        self.state = result.data()["state"]
        if circuit.num_clbits:
            return [int(bit) for bit in reversed(result.get_memory()[0])]
        return None

    def _measure(self, basis: str) -> list[int]:
        circuit = self._circuit(4)
        if basis == "X":
            append_x_checks(circuit, self.data, self.ancilla_x, circuit.cregs[0])
        else:
            append_z_checks(circuit, self.data, self.ancilla_z, circuit.cregs[0])
        return self._run(circuit)

    def _apply_paulis(self, paulis: dict[int, str]) -> None:
        if not paulis:
            return
        circuit = self._circuit()
        for qubit, pauli in paulis.items():
            {"X": circuit.x, "Y": circuit.y, "Z": circuit.z}[pauli](self.data[qubit])
        self._run(circuit)

    def _update_errors(self, paulis: dict[int, str]) -> None:
        for qubit, pauli in paulis.items():
            new = compose_pauli(self.errors.get(qubit), pauli)
            if new is None:
                self.errors.pop(qubit, None)
            else:
                self.errors[qubit] = new

    # ------------------------------------------------------------ public API
    def reset(self) -> None:
        """Fresh qubits, re-encoded into |0_L>. Every check starts at +1."""
        self.state = None
        circuit = self._circuit()
        prepare_logical_zero(circuit, self.data)
        self._run(circuit)
        self.cycle = 1
        self.step_index = 0
        self.errors: dict[int, str] = {}  # residual Pauli error per data qubit
        self.logical_failed = False
        self.logical_kind = ""
        self.last = {"X": [0] * 4, "Z": [0] * 4}
        self.reference = {"X": [0] * 4, "Z": [0] * 4}
        self.last_result: StepResult | None = None
        self.pending: dict[str, list[int]] = {}  # flags waiting for this cycle's decode

    @property
    def next_step(self) -> str:
        return STEPS[self.step_index]

    def inject(self, qubit: int, pauli: str) -> str:
        """Apply a single-qubit Pauli error to a data qubit right now."""
        pauli = pauli.upper()
        if pauli not in PAULIS:
            raise ValueError(f"error must be one of {PAULIS}, got {pauli!r}")
        if not 0 <= qubit < NUM_DATA:
            raise ValueError(f"data qubit index must be 0-8, got {qubit}")
        self._apply_paulis({qubit: pauli})
        self._update_errors({qubit: pauli})
        return f"Injected {pauli} on {data_label(qubit)}."

    def step(self) -> StepResult:
        """Run the next step of the QEC cycle."""
        name = STEPS[self.step_index]
        result = StepResult(step=name, cycle=self.cycle)

        if name in ("X checks", "Z checks"):
            basis = name[0]
            outcomes = self._measure(basis)
            self.last[basis] = outcomes
            detections = [a ^ b for a, b in zip(outcomes, self.reference[basis])]
            result.outcomes[basis] = outcomes
            result.detections[basis] = detections
            self.pending[basis] = detections
            result.pending = {b: list(d) for b, d in self.pending.items()}
            flagged = [f"{basis}{i}" for i, bit in enumerate(detections) if bit]
            caught = "Z-type" if basis == "X" else "X-type"
            result.message = (
                f"{name}: {', '.join(flagged)} flagged -> {caught} error."
                if flagged
                else f"{name}: all +1."
            )
        else:
            dx = np.array(
                [a ^ b for a, b in zip(self.last["X"], self.reference["X"])], dtype=np.uint8
            )
            dz = np.array(
                [a ^ b for a, b in zip(self.last["Z"], self.reference["Z"])], dtype=np.uint8
            )
            result.detections = {"X": dx.tolist(), "Z": dz.tolist()}
            fix_x = self.match_z.decode(dz)  # X corrections from Z checks
            fix_z = self.match_x.decode(dx)  # Z corrections from X checks
            for qubit in range(NUM_DATA):
                pauli = compose_pauli("X" if fix_x[qubit] else None, "Z" if fix_z[qubit] else None)
                if pauli:
                    result.correction[qubit] = pauli
            self._apply_paulis(result.correction)
            self._update_errors(result.correction)
            # After the correction every check should read its old value XOR the flip.
            self.reference["X"] = [int(v) for v in np.array(self.last["X"]) ^ (self.hx @ fix_z % 2)]
            self.reference["Z"] = [int(v) for v in np.array(self.last["Z"]) ^ (self.hz @ fix_x % 2)]
            self._check_logical()
            self.pending = {}  # every flag of this cycle has now been decoded

            if result.correction:
                fixes = ", ".join(f"{p} on {data_label(q)}" for q, p in sorted(result.correction.items()))
                result.message = f"MWPM: apply {fixes}."
            else:
                result.message = "MWPM: nothing flagged, no correction."
            if self.logical_failed:
                result.message += f" LOGICAL ERROR ({self.logical_kind})."
            self.cycle += 1

        self.step_index = (self.step_index + 1) % len(STEPS)
        self.last_result = result
        return result

    # --------------------------------------------------------- logical check
    def _residual_syndrome_nontrivial(self) -> bool:
        ex = np.zeros(NUM_DATA, dtype=np.uint8)
        ez = np.zeros(NUM_DATA, dtype=np.uint8)
        for qubit, pauli in self.errors.items():
            ex[qubit] = pauli in ("X", "Y")
            ez[qubit] = pauli in ("Z", "Y")
        return bool((self.hz @ ex % 2).any() or (self.hx @ ez % 2).any())

    def _check_logical(self) -> None:
        """Residual with trivial syndrome: a stabilizer (fine) or a logical (failure).

        Errors injected after the last checks are still unseen, so the residual
        can have a non-trivial syndrome; it is left alone until it is caught.
        """
        if self._residual_syndrome_nontrivial():
            return
        x_part = {q for q, p in self.errors.items() if p in ("X", "Y")}
        z_part = {q for q, p in self.errors.items() if p in ("Z", "Y")}
        flips_z_l = len(x_part & set(LOGICAL_Z)) % 2 == 1
        flips_x_l = len(z_part & set(LOGICAL_X)) % 2 == 1
        if flips_z_l or flips_x_l:
            kinds = []
            if flips_z_l:
                kinds.append("logical X, bit flip")
            if flips_x_l:
                kinds.append("logical Z, phase flip")
            self.logical_failed = True
            self.logical_kind = " + ".join(kinds)
        else:
            self.errors = {}  # residual is a stabilizer: same as no error

    def logical_z_expectation(self) -> float:
        """<Z_L> read from the simulated state (+1 = still |0_L>)."""
        label = ["I"] * (NUM_DATA + 8)
        for qubit in LOGICAL_Z:
            label[qubit] = "Z"
        pauli = Pauli("".join(reversed(label)))
        return float(np.real(self.state.expectation_value(pauli)))


if __name__ == "__main__":
    memory = SurfaceCodeMemory(seed=7)
    for _ in range(3):
        print(f"[cycle {memory.cycle}] {memory.step().message}")
    print(memory.inject(4, "Y"))
    for _ in range(3):
        print(f"[cycle {memory.cycle}] {memory.step().message}")
    print("logical failed:", memory.logical_failed, " <Z_L> =", memory.logical_z_expectation())
    print(memory.inject(0, "X"), memory.inject(3, "X"))
    for _ in range(3):
        print(f"[cycle {memory.cycle}] {memory.step().message}")
    print("logical failed:", memory.logical_failed, memory.logical_kind,
          " <Z_L> =", memory.logical_z_expectation())
