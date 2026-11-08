"""
Surface-17 quantum memory engine.

Distance-3 rotated surface code (9 data + 4 Z-ancillas + 4 X-ancillas = 17 qubits)

* Code layout, stabilizers, CX schedule and logical operators come from
  qiskit-qec's ``SurfaceCodeCircuit``.
* Every syndrome round is a real Qiskit circuit executed on the Aer stabilizer
  simulator. The full 17-qubit quantum state is carried from one step to the
  next (save_stabilizer -> set_stabilizer), so the code genuinely "idles" as a
  quantum memory between steps.
* Decoding is minimum-weight perfect matching (PyMatching) on the check
  matrices built from qiskit-qec's stabilizers. The correction is applied back
  to the simulated quantum state as Pauli gates.

The cycle is split into separately executable steps:

    Z checks  ->  X checks  ->  Decode + correct  ->  (repeat)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pymatching
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.quantum_info import Pauli
from qiskit_aer import AerSimulator
from qiskit_qec.circuits import SurfaceCodeCircuit

STEPS = ("Z checks", "X checks", "Decode + correct")


@dataclass
class StepResult:
    """What happened during one step, for the UI to render."""

    step: str
    cycle: int
    # Raw ancilla outcomes for the checks measured in this step (0 -> +1, 1 -> -1)
    z_outcomes: list[int] | None = None
    x_outcomes: list[int] | None = None
    # Detection events (syndrome differs from the reference) for this step
    z_detections: list[int] | None = None
    x_detections: list[int] | None = None
    # Corrections applied by the decoder: {data qubit: "X" | "Z" | "Y"}
    correction: dict[int, str] = field(default_factory=dict)
    # Pairs of matched checks returned by MWPM, per basis; -1 means boundary
    z_matches: list[tuple[int, int]] = field(default_factory=list)
    x_matches: list[tuple[int, int]] = field(default_factory=list)
    message: str = ""


class Surface17Memory:
    """A d=3 rotated surface code idling as a quantum memory in |0_L>."""

    def __init__(self, seed: int | None = None):
        # --- code definition from qiskit-qec --------------------------------
        self.code = SurfaceCodeCircuit(d=3, T=1, basis="z")
        self.d = self.code.d
        self.n_data = self.code.n
        self.zplaqs = self.code.zplaqs  # data qubits per Z check, in CX order
        self.xplaqs = self.code.xplaqs  # data qubits per X check, in CX order
        self.zplaq_coords = self.code._zplaq_coords
        self.xplaq_coords = self.code._xplaq_coords
        self.z_stabs = self.code.z_stabilizer_ops
        self.x_stabs = self.code.x_stabilizer_ops
        self.logical_z = self.code._logicals["z"][0]  # Z_L support
        self.logical_x = self.code._logicals["x"][0]  # X_L support
        self.n_z = len(self.zplaqs)
        self.n_x = len(self.xplaqs)

        # --- 17-qubit register layout (same naming as qiskit-qec) ------------
        self.qr_data = QuantumRegister(self.n_data, "code_qubit")
        self.qr_z = QuantumRegister(self.n_z, "zplaq_qubit")
        self.qr_x = QuantumRegister(self.n_x, "xplaq_qubit")

        # --- MWPM decoders ----------------------------------------------------
        # Z checks detect X errors; X checks detect Z errors.
        self.hz = self._check_matrix(self.z_stabs)
        self.hx = self._check_matrix(self.x_stabs)
        self.match_z = pymatching.Matching.from_check_matrix(self.hz)
        self.match_x = pymatching.Matching.from_check_matrix(self.hx)

        self.sim = AerSimulator(method="stabilizer", seed_simulator=seed)
        self.reset()

    # ------------------------------------------------------------------ setup
    def _check_matrix(self, stabs):
        h = np.zeros((len(stabs), self.n_data), dtype=np.uint8)
        for i, s in enumerate(stabs):
            h[i, s] = 1
        return h

    def _new_circuit(self, n_bits: int = 0) -> QuantumCircuit:
        qc = QuantumCircuit(self.qr_data, self.qr_z, self.qr_x)
        if n_bits:
            qc.add_register(ClassicalRegister(n_bits, "m"))
        if self.state is not None:
            qc.set_stabilizer(self.state)
        return qc

    def _run(self, qc: QuantumCircuit) -> list[int] | None:
        """Execute on Aer (1 shot), persist the post-measurement state."""
        qc.save_stabilizer(label="state")
        result = self.sim.run(qc, shots=1, memory=True).result()
        self.state = result.data()["state"]
        if qc.num_clbits:
            bits = result.get_memory()[0]
            return [int(b) for b in reversed(bits)]  # little-endian -> index order
        return None

    def reset(self):
        """Prepare |0_L>: |0>^9, project onto the X checks, gauge-fix with Z's."""
        self.state = None
        self.cycle = 1
        self.step_index = 0
        self.frame = {}  # tracked residual Pauli error {qubit: "X"/"Z"/"Y"}
        self.logical_failed = False
        self.logical_kind = ""
        self.history = []  # per completed cycle: (z_detections, x_detections)
        self.last_z = [0] * self.n_z
        self.last_x = [0] * self.n_x
        self.ref_z = [0] * self.n_z
        self.ref_x = [0] * self.n_x

        # Data qubits start in |0> so every Z check is already +1.
        # The X checks are random: measure them once and fix them to +1.
        self._run(self._new_circuit())
        x_out = self._measure_checks("X")
        fix = self.match_x.decode(np.array(x_out, dtype=np.uint8))
        qc = self._new_circuit()
        for q in np.flatnonzero(fix):
            qc.z(self.qr_data[int(q)])
        self._run(qc)
        self.init_message = (
            f"Encoded |0_L>: X checks gave {x_out}, gauge-fixed with Z on "
            f"{[int(q) for q in np.flatnonzero(fix)] or 'nothing'}."
        )

    # ------------------------------------------------------------ primitives
    def _measure_checks(self, basis: str) -> list[int]:
        """One round of Z- or X-stabilizer measurement through the ancillas."""
        plaqs = self.zplaqs if basis == "Z" else self.xplaqs
        anc = self.qr_z if basis == "Z" else self.qr_x
        qc = self._new_circuit(len(plaqs))
        if basis == "X":
            qc.h(anc)
        for layer in range(4):  # qiskit-qec's 4-layer CX schedule
            for p, plaq in enumerate(plaqs):
                q = plaq[layer]
                if q is None:
                    continue
                if basis == "Z":
                    qc.cx(self.qr_data[q], anc[p])
                else:
                    qc.cx(anc[p], self.qr_data[q])
        if basis == "X":
            qc.h(anc)
        qc.measure(anc, qc.cregs[0])
        qc.reset(anc)
        return self._run(qc)

    def _apply_paulis(self, paulis: dict[int, str]):
        if not paulis:
            return
        qc = self._new_circuit()
        for q, p in paulis.items():
            {"X": qc.x, "Z": qc.z, "Y": qc.y}[p](self.qr_data[q])
        self._run(qc)

    @staticmethod
    def _compose(a: str | None, b: str) -> str | None:
        """Multiply single-qubit Paulis, ignoring phase."""
        bits = {None: (0, 0), "X": (1, 0), "Z": (0, 1), "Y": (1, 1)}
        x = bits[a][0] ^ bits[b][0]
        z = bits[a][1] ^ bits[b][1]
        return {(0, 0): None, (1, 0): "X", (0, 1): "Z", (1, 1): "Y"}[(x, z)]

    def _update_frame(self, paulis: dict[int, str]):
        for q, p in paulis.items():
            new = self._compose(self.frame.get(q), p)
            if new is None:
                self.frame.pop(q, None)
            else:
                self.frame[q] = new

    # --------------------------------------------------------- public API
    @property
    def next_step(self) -> str:
        return STEPS[self.step_index]

    def inject(self, qubit: int, pauli: str) -> str:
        """Apply a single-qubit Pauli error to a data qubit right now."""
        self._apply_paulis({qubit: pauli})
        self._update_frame({qubit: pauli})
        return f"Injected {pauli} error on data qubit D{qubit}."

    def step(self) -> StepResult:
        """Run the next step of the QEC cycle."""
        name = STEPS[self.step_index]
        res = StepResult(step=name, cycle=self.cycle)

        if name == "Z checks":
            out = self._measure_checks("Z")
            self.last_z = out
            res.z_outcomes = out
            res.z_detections = [a ^ b for a, b in zip(out, self.ref_z)]
            flagged = [f"Z{i}" for i, v in enumerate(res.z_detections) if v]
            res.message = (
                f"Z checks: {', '.join(flagged)} flipped -> X-type error detected."
                if flagged
                else "Z checks: all +1 (no bit flips)."
            )

        elif name == "X checks":
            out = self._measure_checks("X")
            self.last_x = out
            res.x_outcomes = out
            res.x_detections = [a ^ b for a, b in zip(out, self.ref_x)]
            flagged = [f"X{i}" for i, v in enumerate(res.x_detections) if v]
            res.message = (
                f"X checks: {', '.join(flagged)} flipped -> Z-type error detected."
                if flagged
                else "X checks: all +1 (no phase flips)."
            )

        else:  # Decode + correct
            dz = np.array([a ^ b for a, b in zip(self.last_z, self.ref_z)], dtype=np.uint8)
            dx = np.array([a ^ b for a, b in zip(self.last_x, self.ref_x)], dtype=np.uint8)
            res.z_detections = dz.tolist()
            res.x_detections = dx.tolist()
            self.history.append((dz.tolist(), dx.tolist()))

            corr_x = self.match_z.decode(dz)  # X corrections from Z syndrome
            corr_z = self.match_x.decode(dx)  # Z corrections from X syndrome
            res.z_matches = self._matches(self.match_z, dz)
            res.x_matches = self._matches(self.match_x, dx)
            for q in range(self.n_data):
                p = None
                if corr_x[q]:
                    p = self._compose(p, "X")
                if corr_z[q]:
                    p = self._compose(p, "Z")
                if p:
                    res.correction[q] = p

            self._apply_paulis(res.correction)
            self._update_frame(res.correction)

            # Expected syndrome after correction becomes the new reference.
            self.ref_z = [int(v) for v in (np.array(self.last_z) ^ (self.hz @ corr_x % 2))]
            self.ref_x = [int(v) for v in (np.array(self.last_x) ^ (self.hx @ corr_z % 2))]

            self._check_logical()
            if res.correction:
                fixes = ", ".join(f"{p} on D{q}" for q, p in sorted(res.correction.items()))
                res.message = f"MWPM decoder: apply {fixes}."
            else:
                res.message = "MWPM decoder: no detection events, nothing to correct."
            if self.logical_failed:
                res.message += f"  LOGICAL ERROR ({self.logical_kind})!"
            self.cycle += 1

        self.step_index = (self.step_index + 1) % len(STEPS)
        return res

    @staticmethod
    def _matches(matching, dets) -> list[tuple[int, int]]:
        if not dets.any():
            return []
        return [tuple(int(v) for v in e) for e in matching.decode_to_edges_array(dets)]

    def _check_logical(self):
        """Is the residual error (injected + corrections) a logical operator?

        Only meaningful when the residual has a trivial syndrome, i.e. right
        after a successful decode. Residuals that are stabilizers are dropped
        from the frame since they act trivially on the code space.
        """
        if self._frame_syndrome_nontrivial():
            return
        x_part = {q for q, p in self.frame.items() if p in ("X", "Y")}
        z_part = {q for q, p in self.frame.items() if p in ("Z", "Y")}
        flips_z_l = len(x_part & set(self.logical_z)) % 2 == 1  # X_L-type error
        flips_x_l = len(z_part & set(self.logical_x)) % 2 == 1  # Z_L-type error
        if flips_z_l or flips_x_l:
            kinds = []
            if flips_z_l:
                kinds.append("logical X - bit flip")
            if flips_x_l:
                kinds.append("logical Z - phase flip")
            self.logical_failed = True
            self.logical_kind = " + ".join(kinds)
        else:
            self.frame = {}  # residual is a stabilizer: equivalent to identity

    def _frame_syndrome_nontrivial(self) -> bool:
        ex = np.zeros(self.n_data, dtype=np.uint8)
        ez = np.zeros(self.n_data, dtype=np.uint8)
        for q, p in self.frame.items():
            ex[q] = p in ("X", "Y")
            ez[q] = p in ("Z", "Y")
        return bool((self.hz @ ex % 2).any() or (self.hx @ ez % 2).any())

    def logical_z_expectation(self) -> float:
        """<Z_L> read directly from the simulated 17-qubit quantum state."""
        label = ["I"] * (self.n_data + self.n_z + self.n_x)
        for q in self.logical_z:
            label[q] = "Z"
        return float(np.real(self.state.expectation_value(Pauli("".join(reversed(label))))))


if __name__ == "__main__":
    # Headless smoke test: inject a single error and watch it get corrected.
    mem = Surface17Memory(seed=7)
    print(mem.init_message)
    for _ in range(3):
        print(f"[cycle {mem.cycle}] {mem.step().message}")
    print(mem.inject(4, "Y"))
    for _ in range(6):
        print(f"[cycle {mem.cycle}] {mem.step().message}")
    print("logical failed:", mem.logical_failed, " <Z_L> =", mem.logical_z_expectation())
    print(mem.inject(0, "X"), mem.inject(3, "X"))
    for _ in range(6):
        print(f"[cycle {mem.cycle}] {mem.step().message}")
    print("logical failed:", mem.logical_failed, mem.logical_kind, " <Z_L> =", mem.logical_z_expectation())
