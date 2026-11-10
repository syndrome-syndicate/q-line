"""
Hardware-style surface-code memory experiment, decoded afterwards.

This is what can run on a real IBM device (and on noisy fake backends that copy
one): the whole experiment is a single circuit, nothing is paused or applied
mid-run, and decoding happens on the laptop.

    data qubits start in |0>          (every Z check is +1; the first X-check
                                       round projects onto the code, |0_L>)
    N rounds of X checks, Z checks    (mid-circuit measurement + reset)
    measure all 9 data qubits in Z    (gives the final Z checks and Z_L)

Planned faults can be added at fixed points: a data error (X/Y/Z on a data qubit
before round r; r = N + 1 means just before the final readout) or a measurement
error (flip a check's result in round r).

Decoding is space-time MWPM. Detection events compare each round with the
previous one, so a data error flags a check from one round on, while a
measurement error flags the same check in two consecutive rounds.

Two decoders (decode_shots(decoder=...)):

    "realtime" (default)  what a decoder running next to the quantum computer does.
                          After every round it decodes only the rounds measured so far
                          and commits (fixes for good) the corrections for rounds that are
                          ``window`` rounds old; newer flags stay pending until later
                          rounds show whether they last (data error) or flip back
                          (measurement error). window=0 fixes each round from that
                          round alone (no look-ahead, like Live mode); window=1 waits
                          one round. Committed corrections are never revised.
    "offline"             one MWPM over the whole shot after the run (all rounds and
                          the final readout at once): the best possible decision, but
                          only available after the experiment.

Corrections are Pauli-frame corrections: tracked in software and applied to the
final readout, which is equivalent to applying them to the qubits (and is how real
QEC handles them), so the same recorded shots can be decoded either way.
The logical verdict uses the final readout: Z_L = D1 D2 D3 parity, corrected by
the decoder's X corrections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pymatching
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from .circuits import (
    X_CHECK_SCHEDULE,
    X_CHECK_SUPPORTS,
    Z_CHECK_SCHEDULE,
    Z_CHECK_SUPPORTS,
    data_label,
)
from .memory import LOGICAL_Z, compose_pauli

NUM_DATA = 9
NUM_CHECKS = 4


# --------------------------------------------------------------------- faults
@dataclass(frozen=True)
class Fault:
    """A planned error.

    kind "X" / "Y" / "Z": data error on data qubit ``target`` (0..8) before round ``round``.
    kind "M": measurement error on check ``target`` ("X0".."Z3") in round ``round``.
    """

    kind: str
    target: int | str
    round: int

    def describe(self) -> str:
        if self.kind == "M":
            return f"measurement error on {self.target} in round {self.round}"
        return f"{self.kind} on {data_label(self.target)} before round {self.round}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "target": self.target, "round": self.round,
                "description": self.describe()}


def parse_fault(text: str) -> Fault:
    """'X:D5@2' (data error on D5 before round 2) or 'M:Z1@2' (measurement error)."""
    match = re.fullmatch(r"\s*([XYZM]):([A-Z]\d)@(\d+)\s*", text.upper())
    if not match:
        raise ValueError(f"bad fault {text!r}: use X:D5@2, Y:D1@3, Z:D9@2 or M:Z1@2")
    kind, target, round_ = match.group(1), match.group(2), int(match.group(3))
    if kind == "M":
        if target[0] not in "XZ" or not 0 <= int(target[1]) < NUM_CHECKS:
            raise ValueError(f"bad check {target!r} in {text!r}: use X0..X3 or Z0..Z3")
        return Fault("M", target, round_)
    if target[0] != "D" or not 1 <= int(target[1]) <= NUM_DATA:
        raise ValueError(f"bad data qubit {target!r} in {text!r}: use D1..D9")
    return Fault(kind, int(target[1]) - 1, round_)


@dataclass
class Case:
    name: str
    description: str
    faults: list[Fault] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"name": self.name, "description": self.description,
                "faults": [fault.to_json() for fault in self.faults]}


def default_cases(rounds: int) -> list[Case]:
    """The standard set of cases; faults go in round 2 (or 1 if there is only 1 round)."""
    r = min(2, rounds)
    cases = [
        Case("idle", "no planned fault: only the device's own noise"),
        Case("x_D5", f"X on D5 before round {r} (bulk bit flip)", [Fault("X", 4, r)]),
        Case("z_D3", f"Z on D3 before round {r} (corner phase flip)", [Fault("Z", 2, r)]),
        Case("y_D5", f"Y on D5 before round {r} (both kinds at once)", [Fault("Y", 4, r)]),
        Case("meas_Z1", f"measurement error on Z1 in round {r}: same check flags twice, "
             "no data error", [Fault("M", "Z1", r)]),
        Case("meas_X2", f"measurement error on X2 in round {r}", [Fault("M", "X2", r)]),
        Case("x_D1_D4", f"X on D1 and D4 before round {r}: MWPM completes a logical X "
             "(expected logical failure)", [Fault("X", 0, r), Fault("X", 3, r)]),
        Case("x_D9_late", "X on D9 just before the final readout: only the readout sees it",
             [Fault("X", 8, rounds + 1)]),
    ]
    if rounds < 2:
        cases = [case for case in cases if not case.name.startswith("meas_X")]
    return cases


def validate_faults(faults: list[Fault], rounds: int) -> None:
    for fault in faults:
        last = rounds if fault.kind == "M" else rounds + 1
        if not 1 <= fault.round <= last:
            raise ValueError(f"{fault.describe()}: round must be 1..{last} with {rounds} rounds")


# -------------------------------------------------------------------- circuit
def build_memory_circuit(rounds: int, faults: list[Fault] = ()) -> QuantumCircuit:
    """The full memory experiment as one circuit.

    Classical registers: mx (4 per round), mz (4 per round), md (9 data qubits).
    Bit 4*(r-1) + c of mx / mz is check c in round r.
    """
    validate_faults(list(faults), rounds)
    data = QuantumRegister(NUM_DATA, "data")
    ancilla_x = QuantumRegister(NUM_CHECKS, "ancilla_x")
    ancilla_z = QuantumRegister(NUM_CHECKS, "ancilla_z")
    mx = ClassicalRegister(NUM_CHECKS * rounds, "mx")
    mz = ClassicalRegister(NUM_CHECKS * rounds, "mz")
    md = ClassicalRegister(NUM_DATA, "md")
    circuit = QuantumCircuit(data, ancilla_x, ancilla_z, mx, mz, md)

    def data_faults(round_):
        for fault in faults:
            if fault.kind != "M" and fault.round == round_:
                {"X": circuit.x, "Y": circuit.y, "Z": circuit.z}[fault.kind](data[fault.target])

    def flip_measurements(basis, ancillas, round_):
        for fault in faults:
            if fault.kind == "M" and fault.round == round_ and fault.target[0] == basis:
                circuit.x(ancillas[int(fault.target[1])])

    for round_ in range(1, rounds + 1):
        circuit.barrier(label=f"round_{round_}")
        data_faults(round_)
        bits = slice(NUM_CHECKS * (round_ - 1), NUM_CHECKS * round_)

        circuit.h(ancilla_x)
        for layer in range(4):
            for check, order in enumerate(X_CHECK_SCHEDULE):
                if order[layer] is not None:
                    circuit.cx(ancilla_x[check], data[order[layer]])
        circuit.h(ancilla_x)
        flip_measurements("X", ancilla_x, round_)
        circuit.measure(ancilla_x, mx[bits])

        for layer in range(4):
            for check, order in enumerate(Z_CHECK_SCHEDULE):
                if order[layer] is not None:
                    circuit.cx(data[order[layer]], ancilla_z[check])
        flip_measurements("Z", ancilla_z, round_)
        circuit.measure(ancilla_z, mz[bits])
        if round_ < rounds:
            circuit.reset(ancilla_x)
            circuit.reset(ancilla_z)

    circuit.barrier(label="readout")
    data_faults(rounds + 1)
    circuit.measure(data, md)
    return circuit


def merge_rz_through_cz(circuit: QuantumCircuit) -> QuantumCircuit:
    """Exactly equivalent circuit whose rz angles are all multiples of pi/2.

    The transpiler may move rz rotations through CZ gates (they commute), leaving
    e.g. rz(pi/4) + rz(pi/4) on either side of a CZ. Sliding each qubit's rz
    rotations together until the next non-commuting gate restores the Clifford
    angles, so Aer's fast stabilizer method can run the noisy simulation.
    Raises ValueError if the circuit is not Clifford.
    """
    out = circuit.copy_empty_like()
    pending = {}

    def flush(qubit):
        angle = pending.pop(qubit, 0.0)
        quarter = angle / (np.pi / 2)
        if abs(quarter - round(quarter)) > 1e-6:
            raise ValueError(f"non-Clifford rz({angle})")
        quarter = round(quarter) % 4
        if quarter:
            out.rz(quarter * np.pi / 2, qubit)

    for instruction in circuit.data:
        name, qubits = instruction.operation.name, instruction.qubits
        if name == "rz":
            pending[qubits[0]] = pending.get(qubits[0], 0.0) + float(instruction.operation.params[0])
            continue
        if name not in ("cz", "barrier"):  # rz commutes with cz (and barriers are no-ops)
            for qubit in qubits:
                flush(qubit)
        out.append(instruction)
    for qubit in list(pending):
        flush(qubit)
    return out


def bitstrings_to_array(bitstrings: list[str]) -> np.ndarray:
    """Qiskit bitstrings (bit 0 rightmost) -> array (shots, bits) with column k = bit k."""
    return np.array([[int(bit) for bit in reversed(s)] for s in bitstrings], dtype=np.uint8)


# -------------------------------------------------------------------- decoding
def _check_matrix(supports) -> np.ndarray:
    matrix = np.zeros((len(supports), NUM_DATA), dtype=np.uint8)
    for check, support in enumerate(supports):
        matrix[check, list(support)] = 1
    return matrix


HX = _check_matrix(X_CHECK_SUPPORTS)
HZ = _check_matrix(Z_CHECK_SUPPORTS)


def _space_time_matching(h: np.ndarray, layers: int, time_boundary: bool,
                         measurement_ids: bool = False) -> pymatching.Matching:
    """Matching graph over ``layers`` detection layers.

    Data error on qubit q just before layer t: fault id t*9 + q (edges inside layer t).
    Measurement error: edge between the same check in layers t and t+1 (fault id
    layers*9 + t*4 + c if measurement_ids, so a sliding window can see it; else none).
    time_boundary: the first and last layers also connect to the boundary through
    a measurement error (used when there is no perfect reference at either end).
    """
    matching = pymatching.Matching()
    for t in range(layers):
        for q in range(NUM_DATA):
            checks = [t * NUM_CHECKS + c for c in np.flatnonzero(h[:, q])]
            if len(checks) == 2:
                matching.add_edge(*checks, fault_ids={t * NUM_DATA + q}, weight=1.0,
                                  merge_strategy="smallest-weight")
            elif len(checks) == 1:
                matching.add_boundary_edge(checks[0], fault_ids={t * NUM_DATA + q}, weight=1.0,
                                           merge_strategy="smallest-weight")
        for c in range(NUM_CHECKS):
            node = t * NUM_CHECKS + c
            if t + 1 < layers:
                ids = {layers * NUM_DATA + node} if measurement_ids else set()
                matching.add_edge(node, node + NUM_CHECKS, fault_ids=ids, weight=1.0,
                                  merge_strategy="smallest-weight")
            if time_boundary and (t == 0 or t == layers - 1):
                # slightly heavier, so a single flag next to a spatial boundary is
                # read as a data error rather than a measurement error
                matching.add_boundary_edge(node, weight=1.05, merge_strategy="smallest-weight")
    return matching


def _decode_layers(matching, syndromes: np.ndarray, layers: int) -> np.ndarray:
    """Decode a batch; returns (shots, layers, 9) inferred data errors.

    Parallel boundary edges are merged, so the highest fault ids may be missing
    from the graph; the result is padded to layers*9.
    """
    flips = matching.decode_batch(syndromes)[:, : layers * NUM_DATA]
    full = np.zeros((len(syndromes), layers * NUM_DATA), np.uint8)
    full[:, : flips.shape[1]] = flips
    return full.reshape(len(syndromes), layers, NUM_DATA)


def _sliding_window(h: np.ndarray, det: np.ndarray, window: int):
    """Real-time decoding of detection layers that arrive one per time step.

    At step s (layer s just measured) MWPM runs on the not-yet-committed layers
    first..s, and the corrections for layers <= s - window are committed: data
    errors in those layers, and measurement errors that link them to a later layer
    (that later flag is then marked as explained). The last step commits the rest.

    Returns corr (shots, L, 9) committed data errors per layer, commit_at (L,) the
    step each layer was committed at, pending (shots, L, 4) checks with a flag still
    waiting for a decision after step s.
    """
    shots, layers, _ = det.shape
    corr = np.zeros((shots, layers, NUM_DATA), np.uint8)
    pending = np.zeros((shots, layers, NUM_CHECKS), np.uint8)
    commit_at = np.full(layers, -1)
    residual = det.astype(np.uint8).copy()
    graphs: dict[int, pymatching.Matching] = {}
    first = 0
    for step in range(layers):
        last = layers - 1 if step == layers - 1 else step - window
        if last >= first:
            n = step - first + 1
            if n not in graphs:
                graphs[n] = _space_time_matching(h, n, time_boundary=False, measurement_ids=True)
            width = n * NUM_DATA + (n - 1) * NUM_CHECKS
            flips = graphs[n].decode_batch(residual[:, first: step + 1].reshape(shots, -1))[:, :width]
            full = np.zeros((shots, width), np.uint8)
            full[:, : flips.shape[1]] = flips
            data = full[:, : n * NUM_DATA].reshape(shots, n, NUM_DATA)
            meas = full[:, n * NUM_DATA:].reshape(shots, n - 1, NUM_CHECKS)
            k = last - first + 1  # local layers 0..k-1 are committed now
            corr[:, first: last + 1] = data[:, :k]
            residual[:, first: last + 1] ^= ((data[:, :k] @ h.T) % 2).astype(np.uint8)
            for t in range(min(k, n - 1)):  # measurement errors starting in a committed layer
                residual[:, first + t] ^= meas[:, t]
                residual[:, first + t + 1] ^= meas[:, t]
            assert not residual[:, first: last + 1].any(), "committed layers must be fully explained"
            commit_at[first: last + 1] = step
            first = last + 1
        if first <= step:
            pending[:, step] = residual[:, first: step + 1].any(axis=1)
    return corr, commit_at, pending


@dataclass
class DecodedShots:
    rounds: int
    mx: np.ndarray        # (shots, rounds, 4) raw X-check results
    mz: np.ndarray        # (shots, rounds, 4) raw Z-check results
    md: np.ndarray        # (shots, 9) final data readout
    det_x: np.ndarray     # (shots, rounds + 1, 4) X detection events per round; round 1 = 0
    det_z: np.ndarray     # (shots, rounds + 1, 4) Z detection events; last = from readout
    corr_x: np.ndarray    # (shots, rounds + 1, 9) inferred X errors before each round / readout
    corr_z: np.ndarray    # (shots, rounds + 1, 9) inferred Z errors before each round
    logical_failure: np.ndarray  # (shots,) bool
    decoder: str = "offline"
    window: int = 0
    # Time steps: t = 0..rounds-1 is "after round t+1", t = rounds is "after the readout".
    commit_x: np.ndarray | None = None   # (rounds+1,) step at which corr_x[:, layer] was committed
    commit_z: np.ndarray | None = None   # (rounds+1,) same for corr_z (-1: never, no checks there)
    pending_x: np.ndarray | None = None  # (shots, rounds+1, 4) X flags still undecided after step t
    pending_z: np.ndarray | None = None  # (shots, rounds+1, 4)

    @property
    def label(self) -> str:
        return f"realtime (window {self.window})" if self.decoder == "realtime" else "offline"

    @property
    def shots(self) -> int:
        return len(self.md)

    def has_detections(self) -> np.ndarray:
        return self.det_x.any(axis=(1, 2)) | self.det_z.any(axis=(1, 2))


DECODERS = ("realtime", "offline")


def decode_shots(rounds: int, mx_bits: np.ndarray, mz_bits: np.ndarray, md_bits: np.ndarray,
                 decoder: str = "realtime", window: int = 1) -> DecodedShots:
    if decoder not in DECODERS:
        raise ValueError(f"decoder must be one of {DECODERS}, got {decoder!r}")
    if window < 0:
        raise ValueError("window must be >= 0")
    shots = len(md_bits)
    mx = mx_bits.reshape(shots, rounds, NUM_CHECKS)
    mz = mz_bits.reshape(shots, rounds, NUM_CHECKS)
    md = md_bits

    # Z detection layers 1..rounds+1: round 1 vs |0> (all +1), round r vs r-1,
    # and the readout's Z checks vs the last round. Perfect at both ends.
    final_z = (md @ HZ.T) % 2
    z_values = np.concatenate([np.zeros((shots, 1, NUM_CHECKS), np.uint8), mz, final_z[:, None, :]], axis=1)
    det_z = z_values[:, 1:] ^ z_values[:, :-1]                       # (shots, rounds+1, 4)

    # X detection layers 2..rounds: round 1 is random (it fixes the reference).
    det_x = np.zeros((shots, rounds + 1, NUM_CHECKS), np.uint8)
    if rounds >= 2:
        det_x[:, 1:rounds] = mx[:, 1:] ^ mx[:, :-1]

    corr_x = np.zeros((shots, rounds + 1, NUM_DATA), np.uint8)
    corr_z = np.zeros((shots, rounds + 1, NUM_DATA), np.uint8)
    steps = rounds + 1
    commit_x, commit_z = np.full(steps, -1), np.full(steps, -1)
    pending_x = np.zeros((shots, steps, NUM_CHECKS), np.uint8)
    pending_z = np.zeros((shots, steps, NUM_CHECKS), np.uint8)
    if decoder == "offline":
        match_z = _space_time_matching(HZ, rounds + 1, time_boundary=False)
        corr_x[:] = _decode_layers(match_z, det_z.reshape(shots, -1), rounds + 1)
        commit_x[:] = rounds
        pending_z[:, :rounds] = np.maximum.accumulate(det_z[:, :rounds], axis=1)
        if rounds >= 2:
            layers = rounds - 1
            match_x = _space_time_matching(HX, layers, time_boundary=True)
            syndrome_x = det_x[:, 1:rounds].reshape(shots, -1)
            corr_z[:, 1:rounds] = _decode_layers(match_x, syndrome_x, layers)
            commit_z[1:rounds] = rounds
            pending_x[:, :rounds] = np.maximum.accumulate(det_x[:, :rounds], axis=1)
    else:
        # Z checks: layer t = round t+1 vs round t, layer `rounds` = readout; arrives at step t.
        corr_x[:], commit_x[:], pending_z[:] = _sliding_window(HZ, det_z, window)
        if rounds >= 2:
            # X checks: layers rounds 2..T (round 1 only sets the reference); round r at step r-1.
            corr, commit, pending = _sliding_window(HX, det_x[:, 1:rounds], window)
            corr_z[:, 1:rounds] = corr
            commit_z[1:rounds] = commit + 1
            pending_x[:, 1:rounds] = pending

    total_x = corr_x.sum(axis=1) % 2
    z_l = (md[:, list(LOGICAL_Z)].sum(axis=1) + total_x[:, list(LOGICAL_Z)].sum(axis=1)) % 2
    return DecodedShots(rounds, mx, mz, md, det_x, det_z, corr_x, corr_z, z_l.astype(bool),
                        decoder, window if decoder == "realtime" else 0,
                        commit_x, commit_z, pending_x, pending_z)


# ---------------------------------------------------------------------- frames
STEP_NAMES = ("X checks", "Z checks", "Decode + correct")


def _states(bits, idle):
    return ["flagged" if bit else idle for bit in bits]


def shot_frames(decoded: DecodedShots, shot: int) -> list[tuple[str, dict]]:
    """LED frames for one shot: [(step name, frame), ...] in the Pico_Frames format."""
    if decoded.decoder == "realtime":
        return _realtime_frames(decoded, shot)
    rounds = decoded.rounds
    off = ["off"] * NUM_CHECKS

    def frame(errors, sz, sx, failure=False, reset=False):
        return {
            "Data": [errors.get(q, "on").lower() for q in range(NUM_DATA)],
            "Sz": list(sz),
            "Sx": list(sx),
            "logical failure": bool(failure),
            "reset": bool(reset),
        }

    def inferred(layer):
        errors = {}
        for q in range(NUM_DATA):
            pauli = compose_pauli("X" if decoded.corr_x[shot, layer, q] else None,
                                  "Z" if decoded.corr_z[shot, layer, q] else None)
            if pauli:
                errors[q] = pauli
        return errors

    frames = [("reset", frame({}, off, off, reset=True))]
    for layer in range(rounds):
        name = f"round {layer + 1}"
        errors = inferred(layer)
        dx, dz = decoded.det_x[shot, layer], decoded.det_z[shot, layer]
        frames.append((f"{name}: X checks", frame(errors, off, _states(dx, "on"))))
        frames.append((f"{name}: Z checks", frame(errors, _states(dz, "on"), _states(dx, "off"))))
        frames.append((f"{name}: decode + correct (decided after the run)",
                       frame({}, _states(dz, "off"), _states(dx, "off"))))

    dz = decoded.det_z[shot, rounds]
    failure = bool(decoded.logical_failure[shot])
    frames.append(("final readout: Z checks from the data", frame(inferred(rounds), _states(dz, "on"), off)))
    frames.append(("final decode: logical verdict", frame({}, _states(dz, "off"), off, failure=failure)))
    return frames


def _frame(errors, sz, sx, failure=False, reset=False):
    return {
        "Data": [errors.get(q, "on").lower() for q in range(NUM_DATA)],
        "Sz": list(sz),
        "Sx": list(sx),
        "logical failure": bool(failure),
        "reset": bool(reset),
    }


def _realtime_frames(decoded: DecodedShots, shot: int) -> list[tuple[str, dict]]:
    """Frames that follow the real-time decoder step by step.

    A flag stays flagged (also in the other basis's frames) until the decoder commits
    a decision about it; the decode frame then shows the corrections committed at that
    step on the data qubits and clears the flags they explain.
    """
    rounds = decoded.rounds
    off = ["off"] * NUM_CHECKS

    def flags(bits, idle):
        return ["flagged" if bit else idle for bit in bits]

    def committed(step):
        errors, fixed = {}, set()
        for layer in range(rounds + 1):
            x_now = decoded.commit_x[layer] == step
            z_now = decoded.commit_z[layer] == step
            if x_now or z_now:
                fixed.add(layer)
            for q in range(NUM_DATA):
                x = "X" if x_now and decoded.corr_x[shot, layer, q] else None
                z = "Z" if z_now and decoded.corr_z[shot, layer, q] else None
                pauli = compose_pauli(errors.get(q), compose_pauli(x, z))
                if pauli:
                    errors[q] = pauli
                else:
                    errors.pop(q, None)
        return errors, sorted(fixed)

    def describe(fixed):
        names = ["readout" if layer == rounds else f"round {layer + 1}" for layer in fixed]
        return "decides " + ", ".join(names) if names else "waits for the next round"

    none = np.zeros(NUM_CHECKS, np.uint8)
    frames = [("reset", _frame({}, off, off, reset=True))]
    held_x, held_z = none, none  # flags still pending from earlier steps
    for step in range(rounds):
        name = f"round {step + 1}"
        dx, dz = decoded.det_x[shot, step], decoded.det_z[shot, step]
        frames.append((f"{name}: X checks", _frame({}, flags(held_z, "off"), flags(dx | held_x, "on"))))
        frames.append((f"{name}: Z checks", _frame({}, flags(dz | held_z, "on"), flags(dx | held_x, "off"))))
        held_x, held_z = decoded.pending_x[shot, step], decoded.pending_z[shot, step]
        errors, fixed = committed(step)
        frames.append((f"{name}: decode + correct ({describe(fixed)})",
                       _frame(errors, flags(held_z, "off"), flags(held_x, "off"))))

    dz = decoded.det_z[shot, rounds]
    frames.append(("final readout: Z checks from the data",
                   _frame({}, flags(dz | held_z, "on"), flags(held_x, "off"))))
    errors, fixed = committed(rounds)
    failure = bool(decoded.logical_failure[shot])
    frames.append((f"final decode: logical verdict ({describe(fixed)})",
                   _frame(errors, off, off, failure=failure)))
    return frames


def summarize(decoded: DecodedShots) -> dict:
    """Numbers for case.json."""
    detections = decoded.has_detections()
    return {
        "decoder": decoded.label,
        "shots": decoded.shots,
        "logical_failures": int(decoded.logical_failure.sum()),
        "logical_error_rate": float(decoded.logical_failure.mean()),
        "shots_without_detections": int((~detections).sum()),
        "x_detection_rate_per_round": [float(v) for v in decoded.det_x[:, : decoded.rounds].mean(axis=(0, 2))],
        "z_detection_rate_per_round": [float(v) for v in decoded.det_z[:, : decoded.rounds].mean(axis=(0, 2))],
        "z_detection_rate_readout": float(decoded.det_z[:, decoded.rounds].mean()),
    }


def pick_shots(decoded: DecodedShots, per_category: int) -> dict[str, list[int]]:
    """First few shots of each kind: clean, corrected, logical_failure."""
    detections = decoded.has_detections()
    failure = decoded.logical_failure
    groups = {
        "clean": np.flatnonzero(~detections & ~failure),
        "corrected": np.flatnonzero(detections & ~failure),
        "logical_failure": np.flatnonzero(failure),
    }
    return {name: [int(i) for i in idx[:per_category]] for name, idx in groups.items()}
