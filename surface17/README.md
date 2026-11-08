# Surface-17 memory visualizer

Interactive view of a distance-3 rotated surface code (9 data + 8 ancilla qubits)
idling as a quantum memory in |0_L>.

```
python surface17/visualizer.py              # optional: --interval 0.8 --seed 1
```

The QEC cycle is split into three steps, each one press of **Next step**:

1. **Z checks**: the 4 amber ancillas measure ZZZZ / ZZ (catch X errors)
2. **X checks**: the 4 cyan ancillas measure XXXX / XX (catch Z errors)
3. **Decode + correct**: MWPM (PyMatching) turns the detection events into a
   Pauli correction, which is applied to the simulated qubits

**Play / Pause** auto-runs the cycle. While paused, pick X / Z / Y and click a data
qubit to inject that error, then step to see which checks flag it and how it is
fixed. The indicator turns red when the residual error is a logical operator
(e.g. inject X on D0 and D3: MWPM "corrects" D6 and completes a logical X).
Keys: `space` play/pause, `n` next step, `r` reset, `x`/`z`/`y` error type.

## Three patches + lattice-surgery CNOT

```
python surface17/lattice_surgery.py         # optional: --interval 0.8 --merge-rounds 1 --seed 1
```

Three Surface-17 patches (C = control, A = ancilla in |+>, T = target) each idle as a
memory running Z checks → X checks → Decode + correct. Press **CNOT** (key `c`) and,
at the next cycle boundary, the program runs:

| Step | What happens |
|---|---|
| Merge C+A (ZZ) | seam row reset to \|+>; C and A become one 3×7 patch |
| checks + decode | the new seam Z checks multiply to Z_C Z_A |
| Split C \| A | seam row measured in X |
| Merge A+T (XX) | seam column reset to \|0>; A and T become one 7×3 patch |
| checks + decode | the new seam X checks multiply to X_A X_T |
| Split A \| T | seam column measured in Z |
| Measure A + frame fix | A measured in Z (readout decoded with A's Z checks), then a logical Pauli fix on C/T |
| Re-prepare A \|+> | A ready for the next CNOT |

Choose the inputs for C and T (|0>, |1>, |+>, |->). The table shows ideal and simulated
values of Z_C, X_C, Z_T, X_T, Z_C Z_T, X_C X_T. For example, C=|+>, T=|0> gives a Bell
state after the CNOT, with Z_C Z_T = X_C X_T = +1. You can inject errors on any active
data qubit at any point, including seam qubits during a merge.

`multipatch.py` holds the engine. Run it directly to check the noiseless CNOT for all
16 input pairs.

**Logical-error verdict.** A small CSS stabilizer tracker records what the controller
expects: every check value, the logical parities, and how the logical operators move
through merges and splits. The tracker never sees injected errors. After each decode,
the Aer state is compared with it, and any disagreement turns the light red. An error
that does not change the logical state (e.g. X_L on |+>) is not counted as a failure.

**Known simplification.** Decoding is round by round (space-like MWPM), not a full
space-time decode over d rounds. A single error injected right before a split, on a
seam qubit, can therefore still cause a logical failure. Real lattice surgery avoids
this with d merged rounds and space-time decoding.

## How it works
- `engine.py`: code layout, stabilizers, CX schedule and logicals come from
  qiskit-qec's `SurfaceCodeCircuit(d=3)`. Each step is a Qiskit circuit run on the
  Aer stabilizer simulator; the 17-qubit state is carried between steps
  (`save_stabilizer` / `set_stabilizer`). Decoding uses PyMatching on the check
  matrices built from qiskit-qec's stabilizers. The logical flag is cross-checked
  with ⟨Z_L⟩ read from the simulated state.
- `visualizer.py`: matplotlib UI (board, step indicator, logical flag, detection
  history, log).

## Setup (Windows)
qiskit-qec has no PyPI release and needs a C++ build (Visual Studio C++ tools).
It also needs qiskit 1.x, which means Python ≤ 3.12 for matching Aer wheels.

```
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe pip -r surface17/requirements.txt
# pip (not uv) for qiskit-qec: uv trips over a submodule with over-long paths
set CMAKE_POLICY_VERSION_MINIMUM=3.5        # PowerShell: $env:CMAKE_POLICY_VERSION_MINIMUM="3.5"
.venv/Scripts/python -m pip install git+https://github.com/qiskit-community/qiskit-qec.git
.venv/Scripts/python -m pip uninstall -y qiskit-terra qiskit-ibm-provider   # pulled in by qiskit-qec, clash with qiskit 1.x
```
