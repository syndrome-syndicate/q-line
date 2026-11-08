"""
Three Surface-17 patches and a lattice-surgery CNOT, simulated end to end.

Layout (data-qubit grid coordinates, x to the right, y down):

        x: 0 1 2   3   4 5 6
    y 0-2  [  C  ]
    y 3    seam CA                  (only used while C and A are merged)
    y 4-6  [  A  ] seam [  T  ]     seam AT is the column x = 3

    C = control, A = ancilla (|+>), T = target.  Every patch is the d=3 rotated
    surface code from qiskit-qec's SurfaceCodeCircuit (checked at start-up).

CNOT by lattice surgery (Horsman et al. 2012):
    1. merge C+A along the seam row (seam in |+>)  -> measures Z_C Z_A
    2. split: measure the seam row in X
    3. merge A+T along the seam column (seam in |0>) -> measures X_A X_T
    4. split: measure the seam column in Z
    5. measure every A data qubit in Z               -> Z_A
    6. Pauli-frame correction on C and T from the outcomes

Everything runs as Qiskit circuits on the Aer stabilizer simulator; the
65-qubit state is carried between steps. MWPM decoding (PyMatching) runs on
whichever set of checks is active (separate patches or merged patches).

A small CSS stabilizer tracker (`CSSTracker`) follows what the classical
controller *knows*: the expected value of every check (to form detection
events), the logical measurement outcomes, and how each logical operator moves
through merges/splits. It never sees injected errors, so comparing it with the
simulated quantum state gives a ground-truth logical-error verdict.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pymatching
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.quantum_info import Pauli
from qiskit_aer import AerSimulator
from qiskit_qec.circuits import SurfaceCodeCircuit

D = 3
PATCH_ORIGIN = {"C": (0, 0), "A": (0, 4), "T": (4, 4)}
SEAMS = {"CA": [(x, 3) for x in range(3)], "AT": [(3, y) for y in range(4, 7)]}
GENERATORS = ("XC", "ZC", "XT", "ZT")  # input logical generators we track
INPUT_STATES = ("|0>", "|1>", "|+>", "|->")
CYCLE = ("Z checks", "X checks", "Decode + correct")


# ---------------------------------------------------------------- GF(2) utils
def gf2_solve(rows: list[np.ndarray], target: np.ndarray):
    """Indices i with XOR(rows[i]) == target, or None if not in the span."""
    n = len(target)
    m = len(rows)
    if m == 0:
        return [] if not target.any() else None
    mat = np.concatenate([np.array(rows, dtype=np.uint8), np.eye(m, dtype=np.uint8)], axis=1)
    pivots, r = [], 0
    for col in range(n):
        hits = np.flatnonzero(mat[r:, col])
        if hits.size == 0:
            continue
        piv = r + hits[0]
        mat[[r, piv]] = mat[[piv, r]]
        others = np.flatnonzero(mat[:, col])
        others = others[others != r]
        mat[others] ^= mat[r]
        pivots.append(col)
        r += 1
        if r == m:
            break
    t = np.concatenate([target.astype(np.uint8), np.zeros(m, dtype=np.uint8)])
    for i, col in enumerate(pivots):
        if t[col]:
            t ^= mat[i]
    if t[:n].any():
        return None
    return list(np.flatnonzero(t[n:]))


def _odd(a, b) -> bool:
    return bool(np.bitwise_and(a, b).sum() % 2)


# ------------------------------------------------------------- CSS tracker
@dataclass(eq=False)
class Op:
    kind: str           # "X" or "Z"
    vec: np.ndarray     # support over data qubits
    bit: int            # expected sign: <op> = (-1)**bit  (times v(combo) for logicals)
    combo: np.ndarray | None = None  # logicals only: which input generators it represents

    def mul(self, other: "Op"):
        self.vec = self.vec ^ other.vec
        self.bit ^= other.bit
        if self.combo is not None and other.combo is not None:
            self.combo = self.combo ^ other.combo


class CSSTracker:
    """Classical knowledge of a CSS stabilizer state.

    K: known stabilizers (with signs).  L: tracked logical operators, i.e. the
    Heisenberg images of the input logical generators.
    """

    def __init__(self, n: int):
        self.n = n
        self.K: list[Op] = [Op("Z", self.unit(q), 0) for q in range(n)]  # all |0>
        self.L: list[Op] = []
        self.lost: list[str] = []

    def unit(self, q):
        v = np.zeros(self.n, dtype=np.uint8)
        v[q] = 1
        return v

    @staticmethod
    def other(kind):
        return "Z" if kind == "X" else "X"

    def _span(self, kind, vec, with_logicals=False):
        pool = [o for o in self.K if o.kind == kind]
        if with_logicals:
            pool += [o for o in self.L if o.kind == kind]
        sol = gf2_solve([o.vec for o in pool], vec)
        if sol is None:
            return None
        return [pool[i] for i in sol]

    def predict(self, kind, vec) -> int | None:
        ops = self._span(kind, vec)
        if ops is None:
            return None
        return int(sum(o.bit for o in ops) % 2)

    def decompose(self, kind, vec):
        """vec = product of K and L ops -> (sign bit, combo of input generators)."""
        ops = self._span(kind, vec, with_logicals=True)
        if ops is None:
            return None
        bit = int(sum(o.bit for o in ops) % 2)
        combo = np.zeros(len(GENERATORS), dtype=np.uint8)
        for o in ops:
            if o.combo is not None:
                combo ^= o.combo
        return bit, combo

    def measure(self, kind, vec, outcome) -> int | None:
        """Record a measurement. Returns the predicted bit, or None if random."""
        pred = self.predict(kind, vec)
        if pred is not None:
            return pred
        ok = self.other(kind)
        anti_k = [o for o in self.K if o.kind == ok and _odd(o.vec, vec)]
        anti_l = [o for o in self.L if o.kind == ok and _odd(o.vec, vec)]
        if anti_k:
            piv = anti_k[0]
            for o in anti_k[1:] + anti_l:
                o.mul(piv)
            self.K.remove(piv)
        elif anti_l:  # measuring a logical operator: that information is consumed
            piv = anti_l[0]
            for o in anti_l[1:]:
                o.mul(piv)
            self.L.remove(piv)
            self.lost.append(str(piv.combo))
        self.K.append(Op(kind, vec.copy(), int(outcome)))
        return None

    def apply_pauli(self, kind, vec):
        """An intentional Pauli applied by the controller (not an error)."""
        for o in self.K + self.L:
            if o.kind != kind and _odd(o.vec, vec):
                o.bit ^= 1

    def isolate(self, q, kind):
        """After measuring/resetting qubit q in `kind`, make that a single generator."""
        e = self.unit(q)
        ops = self._span(kind, e)
        single = ops[0]
        for o in ops[1:]:
            single.mul(o)
        for o in self.K + self.L:
            if o is not single and o.kind == kind and o.vec[q]:
                o.mul(single)

    def reset(self, q, basis):
        """Physical reset of qubit q into |0> (basis Z) or |+> (basis X)."""
        e = self.unit(q)
        pred = self.measure(basis, e, 0)
        if pred == 1:
            self.apply_pauli(self.other(basis), e)
        self.isolate(q, basis)

    def release_logical(self, kind, rep, conj_rep, combo, conj_combo):
        """Split a prepared logical eigenstate out of K into tracked logicals."""
        bit = self.predict(kind, rep)
        anti = [o for o in self.K if o.kind == kind and _odd(o.vec, conj_rep)]
        piv = anti[0]
        for o in anti[1:]:
            o.mul(piv)
        self.K.remove(piv)
        self.L.append(Op(kind, rep.copy(), bit, combo))
        self.L.append(Op(self.other(kind), conj_rep.copy(), 0, conj_combo))


# --------------------------------------------------------------- geometry
@dataclass
class Check:
    kind: str
    coord: tuple       # plaquette coordinate (top-left data corner)
    qubits: list       # data indices in CX order
    anc: int = -1
    vec: np.ndarray | None = None

    @property
    def key(self):
        return (self.kind, self.coord)


def region_checks(x0, y0, w, h, index):
    """Rotated surface code on a w x h block of data qubits (qiskit-qec convention)."""
    checks = []
    for y in range(-1, h):
        for x in range(-1, w):
            gx, gy = x0 + x, y0 + y
            kind = "X" if (gx + gy) % 2 == 0 else "Z"
            bulk = 0 <= x < w - 1 and 0 <= y < h - 1
            if not bulk:
                if not (0 <= x < w - 1 or 0 <= y < h - 1):
                    continue
                if x in (-1, w - 1) and kind != "Z":
                    continue
                if y in (-1, h - 1) and kind != "X":
                    continue
            corners = {"TL": (gx, gy), "TR": (gx + 1, gy), "BL": (gx, gy + 1), "BR": (gx + 1, gy + 1)}
            order = ("TL", "TR", "BL", "BR") if kind == "X" else ("TL", "BL", "TR", "BR")
            qubits = [index[corners[c]] for c in order
                      if x0 <= corners[c][0] < x0 + w and y0 <= corners[c][1] < y0 + h]
            checks.append(Check(kind, (gx, gy), qubits))
    return checks


def validate_against_qiskit_qec():
    """Our generator must reproduce qiskit-qec's d=3 plaquettes exactly."""
    code = SurfaceCodeCircuit(d=3, T=1)
    index = {(x, y): x + 3 * y for y in range(3) for x in range(3)}
    ours = {(c.kind, tuple(c.qubits)) for c in region_checks(0, 0, 3, 3, index)}
    ref = {("Z", tuple(q for q in p if q is not None)) for p in code.zplaqs}
    ref |= {("X", tuple(q for q in p if q is not None)) for p in code.xplaqs}
    assert ours == ref, f"layout mismatch:\n{ours}\n{ref}"
    assert code._logicals["z"][0] == [0, 1, 2] and code._logicals["x"][0] == [0, 3, 6]


# ----------------------------------------------------------------- engine
@dataclass
class StepResult:
    step: str
    message: str
    kind: str | None = None                  # "Z"/"X" for check rounds
    correction: dict = field(default_factory=dict)
    matches: list = field(default_factory=list)  # [(kind, check_a, check_b|None)]


class LatticeSurgeryMemory:
    def __init__(self, inputs=("|+>", "|0>"), merge_rounds=1, seed=None):
        validate_against_qiskit_qec()
        self.merge_rounds = merge_rounds
        self.sim = AerSimulator(method="stabilizer", seed_simulator=seed)

        # data qubits
        coords = []
        for (ox, oy) in PATCH_ORIGIN.values():
            coords += [(ox + x, oy + y) for y in range(D) for x in range(D)]
        for seam in SEAMS.values():
            coords += seam
        self.coords = coords
        self.index = {c: i for i, c in enumerate(coords)}
        self.n_data = len(coords)
        self.patch_qubits = {
            p: [self.index[(ox + x, oy + y)] for y in range(D) for x in range(D)]
            for p, (ox, oy) in PATCH_ORIGIN.items()
        }
        self.seam_qubits = {s: [self.index[c] for c in cs] for s, cs in SEAMS.items()}

        # canonical logical representatives: Z on top row, X on left column
        self.rep = {}
        for p, (ox, oy) in PATCH_ORIGIN.items():
            self.rep[("Z", p)] = self._vec([self.index[(ox + x, oy)] for x in range(D)])
            self.rep[("X", p)] = self._vec([self.index[(ox, oy + y)] for y in range(D)])

        # check configurations
        patch = {p: region_checks(ox, oy, D, D, self.index) for p, (ox, oy) in PATCH_ORIGIN.items()}
        self.configs = {
            "idle": patch["C"] + patch["A"] + patch["T"],
            "ZZ": region_checks(0, 0, 3, 7, self.index) + patch["T"],
            "XX": region_checks(0, 4, 7, 3, self.index) + patch["C"],
            "noA": patch["C"] + patch["T"],
        }
        keys = sorted({c.key for cfg in self.configs.values() for c in cfg})
        self.anc_index = {k: i for i, k in enumerate(keys)}
        for cfg in self.configs.values():
            for c in cfg:
                c.anc = self.anc_index[c.key]
                c.vec = self._vec(c.qubits)
        self.n_anc = len(keys)
        self.qr_data = QuantumRegister(self.n_data, "data")
        self.qr_anc = QuantumRegister(self.n_anc, "anc")

        self._matchers = {}
        self.reset(inputs)

    # ---------------------------------------------------------- helpers
    def _vec(self, qubits):
        v = np.zeros(self.n_data, dtype=np.uint8)
        v[list(qubits)] = 1
        return v

    def _new_circuit(self, n_bits=0):
        qc = QuantumCircuit(self.qr_data, self.qr_anc)
        if n_bits:
            qc.add_register(ClassicalRegister(n_bits, "m"))
        if self.state is not None:
            qc.set_stabilizer(self.state)
        return qc

    def _run(self, qc):
        qc.save_stabilizer(label="state")
        result = self.sim.run(qc, shots=1, memory=True).result()
        self.state = result.data()["state"]
        if qc.num_clbits:
            return [int(b) for b in reversed(result.get_memory()[0])]
        return None

    def expectation(self, kind, vec) -> float:
        label = ["I"] * (self.n_data + self.n_anc)
        for q in np.flatnonzero(vec):
            label[q] = kind
        return float(np.real(self.state.expectation_value(Pauli("".join(reversed(label))))))

    @property
    def checks(self):
        return self.configs[self.config]

    @property
    def active_data(self):
        return sorted({q for c in self.checks for q in c.qubits})

    def matcher(self, kind):
        key = (self.config, kind)
        if key not in self._matchers:
            cs = [c for c in self.checks if c.kind == kind]
            cols = self.active_data
            h = np.zeros((len(cs), len(cols)), dtype=np.uint8)
            for i, c in enumerate(cs):
                for q in c.qubits:
                    h[i, cols.index(q)] = 1
            self._matchers[key] = (pymatching.Matching.from_check_matrix(h), cs, cols)
        return self._matchers[key]

    # ------------------------------------------------------------ reset
    def reset(self, inputs=None):
        if inputs is not None:
            self.inputs = dict(zip(("C", "T"), inputs))
        self.state = None
        self.tracker = CSSTracker(self.n_data)
        self.frame = {}
        self.config = "idle"
        self.cycle = 1
        self.cnots_done = 0
        self.cnot_pending = False
        self.in_surgery = False
        self.logical_failed = False
        self.failure_note = ""
        self.last_out = {}   # check key -> last raw outcome
        self.last_det = {}   # check key -> last detection event
        self.parities = {}   # logical measurement results of the current CNOT
        self.queue = deque()
        self.pending = []    # (check, outcome) awaiting decoding before being recorded

        # |+> on every patch that needs it, then one silent round to project.
        self._run(self._new_circuit())
        plus = ["A"] + [p for p in ("C", "T") if self.inputs[p] in ("|+>", "|->")]
        qc = self._new_circuit()
        for p in plus:
            for q in self.patch_qubits[p]:
                qc.h(self.qr_data[q])
                self.tracker.reset(q, "X")
        self._run(qc)
        self._round("Z")
        self._round("X")
        self._flush_pending()
        self.last_out, self.last_det = {}, {}

        # Turn the prepared eigenstates of C and T into tracked logicals.
        self.v = {}
        for p in ("C", "T"):
            s = self.inputs[p]
            zg = np.array([g == f"Z{p}" for g in GENERATORS], dtype=np.uint8)
            xg = np.array([g == f"X{p}" for g in GENERATORS], dtype=np.uint8)
            if s in ("|0>", "|1>"):
                self.tracker.release_logical("Z", self.rep[("Z", p)], self.rep[("X", p)], zg, xg)
                self.v[f"Z{p}"], self.v[f"X{p}"] = (1 if s == "|0>" else -1), 0
                if s == "|1>":
                    self._physical_pauli("X", self.rep[("X", p)])
            else:
                self.tracker.release_logical("X", self.rep[("X", p)], self.rep[("Z", p)], xg, zg)
                self.v[f"X{p}"], self.v[f"Z{p}"] = (1 if s == "|+>" else -1), 0
                if s == "|->":
                    self._physical_pauli("Z", self.rep[("Z", p)])
        self.init_message = (f"Prepared C={self.inputs['C']}, T={self.inputs['T']}, A=|+> "
                             f"(each patch projected by one round of checks).")

    # ------------------------------------------------------ primitives
    def _physical_pauli(self, kind, vec):
        qc = self._new_circuit()
        for q in np.flatnonzero(vec):
            {"X": qc.x, "Z": qc.z, "Y": qc.y}[kind](self.qr_data[int(q)])
        self._run(qc)

    def _apply_paulis(self, paulis: dict):
        if paulis:
            qc = self._new_circuit()
            for q, p in paulis.items():
                {"X": qc.x, "Z": qc.z, "Y": qc.y}[p](self.qr_data[q])
            self._run(qc)

    @staticmethod
    def _compose(a, b):
        bits = {None: (0, 0), "X": (1, 0), "Z": (0, 1), "Y": (1, 1)}
        x, z = bits[a][0] ^ bits[b][0], bits[a][1] ^ bits[b][1]
        return {(0, 0): None, (1, 0): "X", (0, 1): "Z", (1, 1): "Y"}[(x, z)]

    def _update_frame(self, paulis: dict):
        for q, p in paulis.items():
            new = self._compose(self.frame.get(q), p)
            if new:
                self.frame[q] = new
            else:
                self.frame.pop(q, None)

    def _round(self, kind):
        """Measure every active check of one type through its ancilla."""
        cs = [c for c in self.checks if c.kind == kind]
        qc = self._new_circuit(len(cs))
        anc = [self.qr_anc[c.anc] for c in cs]
        if kind == "X":
            qc.h(anc)
        for layer in range(4):
            for c in cs:
                if layer < len(c.qubits):
                    d = self.qr_data[c.qubits[layer]]
                    a = self.qr_anc[c.anc]
                    qc.cx(d, a) if kind == "Z" else qc.cx(a, d)
        if kind == "X":
            qc.h(anc)
        qc.measure(anc, qc.cregs[0])
        qc.reset(anc)
        out = self._run(qc)
        new = 0
        for c, o in zip(cs, out):
            pred = self.tracker.predict(kind, c.vec)
            self.last_out[c.key] = o
            self.last_det[c.key] = 0 if pred is None else o ^ pred
            if pred is None:
                # A check with no reference yet (e.g. a new seam check). Its value is
                # recorded after decoding, so an error the decoder finds in this
                # cycle is not baked into the reference.
                self.pending.append((c, o))
                new += 1
        return cs, new

    def _flush_pending(self, corr=None):
        corr = corr or {}
        ex = self._vec([q for q, p in corr.items() if p in ("X", "Y")])
        ez = self._vec([q for q, p in corr.items() if p in ("Z", "Y")])
        for c, o in self.pending:
            flip = _odd(c.vec, ez if c.kind == "X" else ex)
            self.tracker.measure(c.kind, c.vec, o ^ flip)
        self.pending = []

    def _measure_qubits(self, qubits, basis, fix=None):
        qc = self._new_circuit(len(qubits))
        for i, q in enumerate(qubits):
            if basis == "X":
                qc.h(self.qr_data[q])
            qc.measure(self.qr_data[q], qc.cregs[0][i])
        out = self._run(qc)
        if fix is not None:
            out = fix(out)
        for q, o in zip(qubits, out):
            self.tracker.measure(basis, self.tracker.unit(q), o)
            self.tracker.isolate(q, basis)
        return out

    def _reset_qubits(self, qubits, basis):
        qc = self._new_circuit()
        for q in qubits:
            qc.reset(self.qr_data[q])
            if basis == "X":
                qc.h(self.qr_data[q])
            self.tracker.reset(q, basis)
            self.frame.pop(q, None)
        self._run(qc)

    def _value(self, kind, vec) -> str:
        bit = self.tracker.predict(kind, vec)
        return "?" if bit is None else ("+1" if bit == 0 else "-1")

    # ---------------------------------------------------------- program
    def request_cnot(self):
        """Start lattice surgery right after the current cycle's decode step."""
        q = list(self.queue)
        keep = q[: q.index("Decode + correct") + 1] if q and q[0] != "Z checks" else []
        self.queue = deque(keep)
        self.cnot_pending = True

    def _refill(self):
        if self.cnot_pending:
            self.cnot_pending = False
            r = list(CYCLE) * self.merge_rounds
            self.queue.extend(["Merge C+A (ZZ)"] + r + ["Split C | A", "Merge A+T (XX)"] + r
                              + ["Split A | T", "Measure A + frame fix", "Re-prepare A |+>"])
        self.queue.extend(CYCLE)

    def upcoming(self, n=8):
        while len(self.queue) < n:
            self._refill()
        return list(self.queue)[:n]

    @property
    def next_step(self):
        return self.upcoming(1)[0]

    def inject(self, q, pauli):
        if q not in self.active_data:
            return f"D{q} is not active right now (idle seam qubit); nothing injected."
        self._apply_paulis({q: pauli})
        self._update_frame({q: pauli})
        return f"Injected {pauli} on {self.label(q)}."

    def label(self, q):
        for p, qs in self.patch_qubits.items():
            if q in qs:
                return f"{p}{qs.index(q)}"
        for s, qs in self.seam_qubits.items():
            if q in qs:
                return f"seam{s}{qs.index(q)}"
        return str(q)

    def step(self) -> StepResult:
        name = self.upcoming(1)[0]
        self.queue.popleft()
        handler = {
            "Z checks": lambda: self._check_step("Z"),
            "X checks": lambda: self._check_step("X"),
            "Decode + correct": self._decode_step,
            "Merge C+A (ZZ)": self._merge_ca,
            "Split C | A": self._split_ca,
            "Merge A+T (XX)": self._merge_at,
            "Split A | T": self._split_at,
            "Measure A + frame fix": self._measure_a,
            "Re-prepare A |+>": self._reprep_a,
        }[name]
        return handler()

    # ------------------------------------------------------------ steps
    def _check_step(self, kind):
        cs, new = self._round(kind)
        flagged = [self.check_name(c) for c in cs if self.last_det.get(c.key)]
        msg = f"{kind} checks: " + (f"{', '.join(flagged)} flipped." if flagged else "no flips.")
        if new:
            msg += f" ({new} new checks gave random first values; now the reference.)"
        return StepResult(f"{kind} checks", msg, kind=kind)

    def check_name(self, c):
        return f"{c.kind}{c.coord}"

    def _decode_step(self):
        res = StepResult("Decode + correct", "")
        cols = self.active_data
        corr = {}
        unknown = {c.key for c, _ in self.pending}
        for kind, fix in (("Z", "X"), ("X", "Z")):
            m, cs, cols = self.matcher(kind)
            if any(c.key in unknown for c in cs):
                # Checks measured for the first time have no reference, so they carry
                # no information this round: decode with the remaining checks only.
                cs = [c for c in cs if c.key not in unknown]
                h = np.array([[q in c.qubits for q in cols] for c in cs], dtype=np.uint8)
                m = pymatching.Matching.from_check_matrix(h)
            dets = np.array([self.last_det.get(c.key, 0) for c in cs], dtype=np.uint8)
            if not dets.any():
                continue
            for q in np.flatnonzero(m.decode(dets)):
                corr[cols[q]] = self._compose(corr.get(cols[q]), fix)
            for a, b in m.decode_to_edges_array(dets):
                res.matches.append((kind, cs[a], cs[b] if b >= 0 else None))
        corr = {q: p for q, p in corr.items() if p}
        self._apply_paulis(corr)
        self._update_frame(corr)
        self._flush_pending(corr)
        res.correction = corr
        for c in self.checks:
            self.last_det[c.key] = 0
        fixes = ", ".join(f"{p} on {self.label(q)}" for q, p in sorted(corr.items()))
        res.message = f"MWPM: {fixes}." if corr else "MWPM: nothing to correct."
        if self.config == "ZZ":
            zz = self._value("Z", self.rep[("Z", "C")] ^ self.rep[("Z", "A")])
            self.parities["ZZ"] = zz
            res.message += f"  Z_C Z_A = {zz}"
        if self.config == "XX":
            xx = self._value("X", self.rep[("X", "A")] ^ self.rep[("X", "T")])
            self.parities["XX"] = xx
            res.message += f"  X_A X_T = {xx}"
        self._verdict()
        self.cycle += not self.in_surgery
        return res

    def _merge_ca(self):
        self.last_out, self.last_det = {}, {}
        self.in_surgery = True
        self.parities = {}
        self._reset_qubits(self.seam_qubits["CA"], "X")
        self.config = "ZZ"
        return StepResult("Merge C+A (ZZ)", "Seam row prepared in |+>; C and A now form one "
                          "3x7 patch. Its new Z checks multiply to Z_C Z_A.")

    def _split_ca(self):
        self.last_out, self.last_det = {}, {}
        out = self._measure_qubits(self.seam_qubits["CA"], "X")
        self.config = "idle"
        return StepResult("Split C | A", f"Seam row measured in X: {out}. C and A separate again "
                          f"(Z_C Z_A = {self.parities.get('ZZ', '?')}).")

    def _merge_at(self):
        self.last_out, self.last_det = {}, {}
        self._reset_qubits(self.seam_qubits["AT"], "Z")
        self.config = "XX"
        return StepResult("Merge A+T (XX)", "Seam column prepared in |0>; A and T now form one "
                          "7x3 patch. Its new X checks multiply to X_A X_T.")

    def _split_at(self):
        self.last_out, self.last_det = {}, {}
        out = self._measure_qubits(self.seam_qubits["AT"], "Z")
        self.config = "idle"
        return StepResult("Split A | T", f"Seam column measured in Z: {out}. A and T separate "
                          f"again (X_A X_T = {self.parities.get('XX', '?')}).")

    def _measure_a(self):
        self.last_out, self.last_det = {}, {}
        qa = self.patch_qubits["A"]
        z_checks = [c for c in self.configs["idle"] if c.kind == "Z" and set(c.qubits) <= set(qa)]
        expected = [self.tracker.predict("Z", c.vec) for c in z_checks]
        flipped = []

        def decode_readout(out):
            # Rebuild A's Z checks from the measured bits and decode them, so a
            # bit-flip on A just before readout does not corrupt Z_A.
            bits = np.array(out, dtype=np.uint8)
            h = np.array([[q in c.qubits for q in qa] for c in z_checks], dtype=np.uint8)
            dets = (h @ bits + np.array(expected)) % 2
            if dets.any():
                fix = pymatching.Matching.from_check_matrix(h).decode(dets.astype(np.uint8))
                bits ^= fix.astype(np.uint8)
                flipped.extend(self.label(qa[i]) for i in np.flatnonzero(fix))
            return [int(b) for b in bits]

        self._measure_qubits(qa, "Z", fix=decode_readout)
        za = self._value("Z", self.rep[("Z", "A")])
        self.config = "noA"
        fixes = self._frame_correction()
        self.cnots_done += 1
        self.in_surgery = False
        msg = f"A measured in Z: Z_A = {za}"
        if flipped:
            msg += f" (readout decoded: flipped {', '.join(flipped)})"
        msg += f".  Pauli-frame fix: {fixes or 'none needed'}."
        if self.tracker.lost:
            msg += f"  WARNING: lost logical info {self.tracker.lost}"
        self._verdict()
        return StepResult("Measure A + frame fix", msg)

    def _reprep_a(self):
        self.last_out, self.last_det = {}, {}
        self._reset_qubits(self.patch_qubits["A"], "X")
        self.config = "idle"
        return StepResult("Re-prepare A |+>", "A reset to |+>; its Z checks take fresh random "
                          "values on the next round. CNOT complete.")

    # ------------------------------------------------- logical bookkeeping
    @staticmethod
    def cnot_map(bits, k):
        xc, zc, xt, zt = bits
        for _ in range(k % 2):
            xt ^= xc
            zc ^= zt
        return (xc, zc, xt, zt)

    def logical_vec(self, bits):
        """Canonical physical operator for logical bits (xC, zC, xT, zT): (X vec, Z vec)."""
        xc, zc, xt, zt = bits
        xv = xc * self.rep[("X", "C")] ^ xt * self.rep[("X", "T")]
        zv = zc * self.rep[("Z", "C")] ^ zt * self.rep[("Z", "T")]
        return xv.astype(np.uint8), zv.astype(np.uint8)

    GEN_BITS = {"XC": (1, 0, 0, 0), "ZC": (0, 1, 0, 0), "XT": (0, 0, 1, 0), "ZT": (0, 0, 0, 1)}

    def _frame_correction(self):
        """Choose logical Paulis on C/T so canonical operators match the ideal CNOT."""
        k = self.cnots_done + 1
        delta, rows = [], []
        targets = []
        for gi, g in enumerate(GENERATORS):
            img = self.cnot_map(self.GEN_BITS[g], k)
            xv, zv = self.logical_vec(img)
            kind, vec = ("X", xv) if xv.any() else ("Z", zv)
            dec = self.tracker.decompose(kind, vec)
            want = np.zeros(len(GENERATORS), dtype=np.uint8)
            want[gi] = 1
            if dec is None or not np.array_equal(dec[1], want):
                self.tracker.lost.append(f"{g} image mismatch")
                return "ERROR"
            delta.append(dec[0])
            targets.append((kind, vec))
        # anticommutation of each candidate logical Pauli with each target image
        cands = [("X", self.rep[("X", "C")], "X_L on C"), ("Z", self.rep[("Z", "C")], "Z_L on C"),
                 ("X", self.rep[("X", "T")], "X_L on T"), ("Z", self.rep[("Z", "T")], "Z_L on T")]
        mat = np.array([[int(ck != tk and _odd(cv, tv)) for (ck, cv, _) in cands]
                        for (tk, tv) in targets], dtype=np.uint8)
        sol = gf2_solve([mat[:, j] for j in range(4)], np.array(delta, dtype=np.uint8))
        applied = []
        for j in sol:
            ck, cv, name = cands[j]
            self._physical_pauli(ck, cv)
            self.tracker.apply_pauli(ck, cv)
            applied.append(name)
        # re-anchor tracked logicals on the canonical operators
        self.tracker.L = []
        for gi, (kind, vec) in enumerate(targets):
            combo = np.zeros(len(GENERATORS), dtype=np.uint8)
            combo[gi] = 1
            self.tracker.L.append(Op(kind, vec.copy(), 0, combo))
        return ", ".join(applied)

    def _residual_settled(self) -> bool:
        """True when the tracked residual error commutes with every active check."""
        ex = self._vec([q for q, p in self.frame.items() if p in ("X", "Y")])
        ez = self._vec([q for q, p in self.frame.items() if p in ("Z", "Y")])
        for c in self.checks:
            if _odd(c.vec, ez if c.kind == "X" else ex):
                return False
        return True

    def _verdict(self):
        """Compare the simulated state with everything the controller expects."""
        if not self._residual_settled():
            return
        inactive = set(range(self.n_data)) - set(self.active_data)
        bad = []
        for o in self.tracker.K:
            if inactive & set(np.flatnonzero(o.vec)):
                continue
            if round(self.expectation(o.kind, o.vec)) != (-1) ** o.bit:
                bad.append("stabilizer")
                break
        for o in self.tracker.L:
            v = 1
            for g, used in zip(GENERATORS, o.combo):
                if used:
                    v *= self.v[g]
            if v and round(self.expectation(o.kind, o.vec)) != v * (-1) ** o.bit:
                bad.append(f"logical {''.join(g for g, u in zip(GENERATORS, o.combo) if u)}")
        if bad:
            if not self.logical_failed:
                self.failure_note = f"state disagrees with ideal ({', '.join(bad)})"
            self.logical_failed = True
        else:
            self.frame = {}  # residual acts trivially on the encoded state

    def observables(self):
        """[(name, ideal, simulated)] for canonical logical operators of C and T."""
        rows = []
        for name, bits in (("Z_C", (0, 1, 0, 0)), ("X_C", (1, 0, 0, 0)), ("Z_T", (0, 0, 0, 1)),
                           ("X_T", (0, 0, 1, 0)), ("Z_C Z_T", (0, 1, 0, 1)),
                           ("X_C X_T", (1, 0, 1, 0))):
            back = self.cnot_map(bits, self.cnots_done)
            ideal = 1
            for (x, z), p in (((back[0], back[1]), "C"), ((back[2], back[3]), "T")):
                if x and z:
                    ideal = 0
                elif x:
                    ideal *= self.v[f"X{p}"]
                elif z:
                    ideal *= self.v[f"Z{p}"]
            xv, zv = self.logical_vec(bits)
            kind, vec = ("X", xv) if xv.any() else ("Z", zv)
            sim = None if self.in_surgery else round(self.expectation(kind, vec))
            rows.append((name, ideal, sim))
        return rows


if __name__ == "__main__":
    import itertools

    ok = True
    for ins in itertools.product(INPUT_STATES, repeat=2):
        for seed in range(3):
            m = LatticeSurgeryMemory(inputs=ins, seed=seed)
            for _ in range(3):
                m.step()
            for _ in range(2):  # two CNOTs = identity again
                m.request_cnot()
                while True:
                    r = m.step()
                    if r.step == "Re-prepare A |+>":
                        break
                for _ in range(3):
                    m.step()
                bad = [(n, i, s) for n, i, s in m.observables() if i != s]
                if bad or m.logical_failed or m.tracker.lost:
                    ok = False
                    print("FAIL", ins, seed, m.cnots_done, bad, m.failure_note, m.tracker.lost)
    print("noiseless CNOT check:", "PASS" if ok else "FAIL")
