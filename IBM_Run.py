"""
Run the surface-code memory experiment on a simulator or IBM hardware and save
LED frames for Replay mode.

    python IBM_Run.py                                    # ideal + noisy fake IBM devices
    python IBM_Run.py --backend fake_torino --rounds 3 --shots 4000
    python IBM_Run.py --case "my_case=X:D5@2,M:Z1@3"     # your own planned faults
    python IBM_Run.py --list-backends

Real hardware (uses QPU time; needs a saved IBM Quantum account,
QiskitRuntimeService.save_account(...)):

    python IBM_Run.py --backend ibm_torino --hardware    # submits ONE job with every case
    python IBM_Run.py --retrieve replay_runs/IBM_runs/<run folder>   # if it was interrupted

Backends:
    ideal          noiseless Aer simulator (checks the logic: planned faults behave as designed)
    fake_<name>    noisy local copy of an IBM device (connectivity + calibrated noise), e.g.
                   fake_torino, fake_fez, fake_marrakesh (Heron), fake_brisbane, fake_sherbrooke
    ibm_<name>     the real device (only with --hardware)

Noise for fake backends (--noise):
    pauli (default)  the device's calibrated gate and readout errors as Pauli noise, on Aer's
                     stabilizer simulator: seconds per case.
    full             the device noise model incl. relaxation during gates: minutes per 100 shots.
    Neither adds decoherence for qubits sitting idle (e.g. while others are measured
    mid-circuit), so expect the real device to do worse than either.

Transpiling: several transpiler seeds are tried and the one with the fewest two-qubit
gates whose circuits stay Clifford is kept (falling back to a lower optimization
level if needed). The same rule is used for real hardware, so the circuit that was
simulated is the circuit that is sent.

Output:
    replay_runs/simulations/<date>_<backend>_r<rounds>/    (ideal and fake backends)
    replay_runs/IBM_runs/<date>_<backend>_r<rounds>/        (real hardware)
        summary.json                  every case: logical error rate, detection rates, circuit size
        <case>/case.json              the case's faults and numbers
        <case>/shots.json             every shot's raw bits (to re-decode later)
        <case>/<category>_shot<N>/    frame_*.json for Replay mode + steps.json (what each frame is)
    Categories: clean (no detection events), corrected (events, decoded fine),
    logical_failure (decoded wrong).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from Simulation_Logic.hardware import (
    Case,
    bitstrings_to_array,
    build_memory_circuit,
    decode_shots,
    default_cases,
    merge_rz_through_cz,
    parse_fault,
    pick_shots,
    shot_frames,
    summarize,
    validate_faults,
)

REPLAY_ROOT = Path("replay_runs")
SIMULATIONS = REPLAY_ROOT / "simulations"
IBM_RUNS = REPLAY_ROOT / "IBM_runs"
DEFAULT_BACKENDS = ("ideal", "fake_torino", "fake_brisbane")


# ------------------------------------------------------------------- backends
def fake_backend_names() -> list[str]:
    from qiskit_ibm_runtime import fake_provider

    names = []
    for attr in dir(fake_provider):
        if attr.startswith("Fake") and not attr.endswith("V1") and attr[4:5].isupper():
            cls = getattr(fake_provider, attr)
            try:
                if cls().num_qubits >= 17:
                    names.append("fake_" + attr[4:].lower())
            except Exception:
                continue
    return sorted(names)


def get_backend(name: str, hardware: bool):
    if name == "ideal":
        from qiskit_aer import AerSimulator

        return AerSimulator()
    if name.startswith("fake_"):
        from qiskit_ibm_runtime import fake_provider

        wanted = name[len("fake_"):].lower()
        for attr in dir(fake_provider):
            if attr.startswith("Fake") and attr[4:].lower() == wanted:
                return getattr(fake_provider, attr)()
        raise SystemExit(f"unknown fake backend {name!r}; see --list-backends")
    if name.startswith("ibm_"):
        if not hardware:
            raise SystemExit(
                f"{name} is real hardware and uses QPU time. Add --hardware to submit."
            )
        from qiskit_ibm_runtime import QiskitRuntimeService

        return QiskitRuntimeService().backend(name)
    raise SystemExit(f"unknown backend {name!r}: use ideal, fake_<name> or ibm_<name>")


def is_hardware(name: str) -> bool:
    return name.startswith("ibm_")


# ------------------------------------------------------------------ cases/CLI
def parse_case(text: str, rounds: int) -> Case:
    """'name=X:D5@2,M:Z1@3' -> Case."""
    if "=" not in text:
        raise SystemExit(f"bad --case {text!r}: use name=FAULT,FAULT (e.g. mine=X:D5@2)")
    name, spec = text.split("=", 1)
    faults = [parse_fault(part) for part in spec.split(",") if part.strip()]
    validate_faults(faults, rounds)
    return Case(name.strip(), ", ".join(f.describe() for f in faults) or "no planned fault", faults)


def select_cases(args) -> list[Case]:
    cases = [] if args.only_custom else default_cases(args.rounds)
    if args.cases:
        wanted = set(args.cases.split(","))
        unknown = wanted - {case.name for case in cases}
        if unknown:
            names = ", ".join(case.name for case in default_cases(args.rounds))
            raise SystemExit(f"unknown case(s) {sorted(unknown)}; built-in cases: {names}")
        cases = [case for case in cases if case.name in wanted]
    cases += [parse_case(text, args.rounds) for text in args.case]
    if not cases:
        raise SystemExit("no cases selected")
    return cases


# ------------------------------------------------------------------- running
def _is_clifford(circuit) -> bool:
    try:
        merge_rz_through_cz(circuit)
        return True
    except ValueError:
        return False


def transpile_cases(circuits, backend, name, optimization_level, seed, tries=8):
    """Pick the transpilation: Clifford circuits first, then fewest two-qubit gates.

    Returns (isa_circuits, choice) where choice records the level and seed used.
    """
    if name == "ideal":
        return circuits, {"optimization_level": None, "seed_transpiler": None}
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    for level in range(optimization_level, 0, -1):
        # rank seeds on the first circuit (all cases share the same structure) ...
        ranked = []
        for transpiler_seed in range(seed, seed + tries):
            manager = generate_preset_pass_manager(
                backend=backend, optimization_level=level, seed_transpiler=transpiler_seed)
            first = manager.run(circuits[0])
            if _is_clifford(first):
                ranked.append((circuit_stats(first)["two_qubit_gates"], transpiler_seed))
        # ... then use the best seed whose circuits are Clifford for every case
        for two_qubit, transpiler_seed in sorted(ranked):
            manager = generate_preset_pass_manager(
                backend=backend, optimization_level=level, seed_transpiler=transpiler_seed)
            isa = manager.run(circuits)
            if all(_is_clifford(circuit) for circuit in isa):
                print(f"[{name}] level {level}, transpiler seed {transpiler_seed}: "
                      f"{two_qubit} two-qubit gates")
                return isa, {"optimization_level": level, "seed_transpiler": transpiler_seed}
        print(f"[{name}] level {level}: no Clifford transpilation in {tries} seeds, trying lower")
    raise SystemExit("could not find a Clifford transpilation")


def circuit_stats(circuit) -> dict:
    ops = circuit.count_ops()
    two_qubit = sum(count for op, count in ops.items() if op in ("cx", "cz", "ecr", "swap"))
    layout = None
    if getattr(circuit, "layout", None) is not None:
        try:
            layout = circuit.layout.final_index_layout()[:17]
        except Exception:
            layout = None
    return {"depth": circuit.depth(), "two_qubit_gates": int(two_qubit),
            "ops": {k: int(v) for k, v in ops.items()}, "physical_qubits": layout}


def simulator_for(backend, name, noise):
    """What actually runs the circuits: the backend itself, or a Pauli-noise stabilizer copy."""
    if name.startswith("fake_") and noise == "pauli":
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel

        model = NoiseModel.from_backend(backend, thermal_relaxation=False)
        return AerSimulator(method="stabilizer", noise_model=model), True
    return backend, False


def submit(backend, name, isa_circuits, shots, seed):
    from qiskit_ibm_runtime import SamplerV2

    sampler = SamplerV2(mode=backend)
    if not is_hardware(name) and seed is not None:
        try:
            sampler.options.simulator.seed_simulator = seed
        except Exception:
            pass
    return sampler.run(isa_circuits, shots=shots)


def extract_bits(result, count):
    """[(mx, mz, md) bit arrays] for each circuit in the job result."""
    bits = []
    for index in range(count):
        data = result[index].data
        bits.append(tuple(bitstrings_to_array(getattr(data, reg).get_bitstrings())
                          for reg in ("mx", "mz", "md")))
    return bits


def save_case(folder: Path, case: Case, rounds: int, bits, per_category: int, stats: dict) -> dict:
    mx, mz, md = bits
    decoded = decode_shots(rounds, mx, mz, md)
    numbers = summarize(decoded)
    chosen = pick_shots(decoded, per_category)
    folder.mkdir(parents=True, exist_ok=True)

    info = {**case.to_json(), "rounds": rounds, **numbers, "circuit": stats,
            "saved_shots": chosen}
    (folder / "case.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    raw = {"rounds": rounds, "registers": "mx, mz: check c of round r is bit 4*(r-1)+c; md: D1..D9",
           "mx": ["".join(map(str, row)) for row in mx],
           "mz": ["".join(map(str, row)) for row in mz],
           "md": ["".join(map(str, row)) for row in md]}
    (folder / "shots.json").write_text(json.dumps(raw), encoding="utf-8")

    for category, shot_list in chosen.items():
        for shot in shot_list:
            shot_dir = folder / f"{category}_shot{shot:05d}"
            shot_dir.mkdir(exist_ok=True)
            frames = shot_frames(decoded, shot)
            for number, (_, frame) in enumerate(frames):
                (shot_dir / f"frame_{number:04d}.json").write_text(
                    json.dumps(frame, indent=2), encoding="utf-8")
            steps = {f"frame_{number:04d}.json": step for number, (step, _) in enumerate(frames)}
            (shot_dir / "steps.json").write_text(json.dumps(
                {"case": case.name, "shot": shot, "category": category,
                 "logical_failure": bool(decoded.logical_failure[shot]), "steps": steps},
                indent=2), encoding="utf-8")
    return {"name": case.name, "description": case.description, **numbers,
            "two_qubit_gates": stats["two_qubit_gates"], "depth": stats["depth"],
            "saved_shots": {k: len(v) for k, v in chosen.items()}}


def process_results(run_dir: Path, meta: dict, result) -> None:
    cases = [Case(c["name"], c["description"], [parse_fault(_fault_text(f)) for f in c["faults"]])
             for c in meta["cases"]]
    all_bits = extract_bits(result, len(cases))
    summaries = []
    for case, bits, stats in zip(cases, all_bits, meta["circuits"]):
        summaries.append(save_case(run_dir / case.name, case, meta["rounds"], bits,
                                   meta["per_category"], stats))
    summary = {**{k: v for k, v in meta.items() if k not in ("circuits",)}, "results": summaries}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print_table(meta["backend"], summaries)
    print(f"Frames saved under {run_dir}")


def _fault_text(fault: dict) -> str:
    target = fault["target"]
    if fault["kind"] != "M":
        target = f"D{target + 1}"
    return f"{fault['kind']}:{target}@{fault['round']}"


def print_table(backend: str, summaries: list[dict]) -> None:
    print(f"\n{backend}")
    print(f"  {'case':12} {'logical err':>11} {'no events':>9} {'2q gates':>8} {'depth':>6}")
    for s in summaries:
        print(f"  {s['name']:12} {s['logical_error_rate']:11.3f} "
              f"{s['shots_without_detections'] / s['shots']:9.3f} {s['two_qubit_gates']:8d} {s['depth']:6d}")


def run_backend(name: str, cases: list[Case], args) -> Path:
    backend = get_backend(name, args.hardware)
    circuits = [build_memory_circuit(args.rounds, case.faults) for case in cases]
    print(f"\n[{name}] transpiling {len(circuits)} circuits ...")
    isa, choice = transpile_cases(circuits, backend, name, args.optimization_level, args.seed)
    stats = [circuit_stats(circuit) for circuit in isa]
    runner, pauli = simulator_for(backend, name, args.noise)
    if pauli:  # same circuits, rz rotations slid together so the stabilizer method accepts them
        isa = [merge_rz_through_cz(circuit) for circuit in isa]

    root = IBM_RUNS if is_hardware(name) else SIMULATIONS
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = "_fullnoise" if name.startswith("fake_") and args.noise == "full" else ""
    run_dir = root / f"{stamp}_{name}_r{args.rounds}{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    meta = {"backend": name, "rounds": args.rounds, "shots": args.shots,
            "per_category": args.per_category, **choice, "seed": args.seed, "created": stamp,
            "noise": ("none" if name == "ideal" else "real device" if is_hardware(name)
                      else "pauli (calibrated gate + readout errors, no idle decoherence)"
                      if pauli else "full device noise model"),
            "cases": [case.to_json() for case in cases], "circuits": stats}

    shots = args.shots if name != "ideal" else min(args.shots, 200)  # ideal: no noise to sample
    meta["shots"] = shots
    started = time.time()
    job = submit(runner, name, isa, shots, args.seed)
    if is_hardware(name):
        meta["job_id"] = job.job_id()
        (run_dir / "job.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"[{name}] submitted job {meta['job_id']}; waiting (queue time does not use QPU time).")
        print(f"         If this stops, fetch it later: python IBM_Run.py --retrieve {run_dir}")
    result = job.result()
    meta["wall_seconds"] = round(time.time() - started, 1)
    if is_hardware(name):
        try:
            meta["metrics"] = json.loads(json.dumps(job.metrics(), default=str))  # includes QPU usage
        except Exception:
            pass
    process_results(run_dir, meta, result)
    return run_dir


def retrieve(run_dir: Path) -> None:
    meta = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
    from qiskit_ibm_runtime import QiskitRuntimeService

    job = QiskitRuntimeService().job(meta["job_id"])
    print(f"Job {meta['job_id']}: {job.status()}")
    process_results(run_dir, meta, job.result())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__[__doc__.index("Real hardware"):])
    parser.add_argument("--backend", action="append",
                        help=f"repeatable; default: {', '.join(DEFAULT_BACKENDS)}")
    parser.add_argument("--rounds", type=int, default=3, help="QEC rounds before the readout (default 3)")
    parser.add_argument("--shots", type=int, default=4000, help="shots per case (ideal uses <= 200)")
    parser.add_argument("--cases", help="comma-separated built-in cases to run (default: all)")
    parser.add_argument("--case", action="append", default=[], metavar="NAME=FAULTS",
                        help="extra case, e.g. mine=X:D5@2,M:Z1@3 (repeatable)")
    parser.add_argument("--only-custom", action="store_true", help="run only the --case cases")
    parser.add_argument("--per-category", type=int, default=3,
                        help="shots saved as frame folders per category (default 3)")
    parser.add_argument("--optimization-level", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--noise", choices=("pauli", "full"), default="pauli",
                        help="noise model for fake backends (default pauli: fast)")
    parser.add_argument("--seed", type=int, default=7, help="transpiler / simulator seed")
    parser.add_argument("--hardware", action="store_true", help="allow ibm_* backends (uses QPU time)")
    parser.add_argument("--retrieve", type=Path, metavar="RUN_FOLDER",
                        help="fetch and decode a submitted hardware job")
    parser.add_argument("--list-backends", action="store_true")
    args = parser.parse_args(argv)

    if args.list_backends:
        print("ideal\n" + "\n".join(fake_backend_names()))
        print("ibm_<name> (real devices on your IBM Quantum account, with --hardware)")
        return
    if args.retrieve:
        retrieve(args.retrieve)
        return
    if args.rounds < 1:
        raise SystemExit("--rounds must be at least 1")

    cases = select_cases(args)
    for name in args.backend or DEFAULT_BACKENDS:
        run_backend(name, cases, args)


if __name__ == "__main__":
    main()
