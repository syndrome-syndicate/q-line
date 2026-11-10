import unittest

import numpy as np
from qiskit_aer import AerSimulator

from Simulation_Logic.hardware import (
    Fault,
    bitstrings_to_array,
    build_memory_circuit,
    decode_shots,
    default_cases,
    merge_rz_through_cz,
    parse_fault,
    shot_frames,
)

ROUNDS = 3


DECODER_SETTINGS = (("offline", 0), ("realtime", 0), ("realtime", 1), ("realtime", 2))


def run_ideal(faults, shots=40, rounds=ROUNDS, decoder="realtime", window=1):
    circuit = build_memory_circuit(rounds, faults)
    result = AerSimulator(method="stabilizer").run(circuit, shots=shots, memory=True, seed_simulator=3).result()
    rows = [m.replace(" ", "") for m in result.get_memory()]
    # memory string order: md mz mx (last register first)
    n = 4 * rounds
    md = bitstrings_to_array([r[: 9] for r in rows])
    mz = bitstrings_to_array([r[9: 9 + n] for r in rows])
    mx = bitstrings_to_array([r[9 + n:] for r in rows])
    return decode_shots(rounds, mx, mz, md, decoder, window)


class HardwareExperimentTests(unittest.TestCase):
    def test_every_decoder_handles_the_builtin_cases(self):
        for decoder, window in DECODER_SETTINGS:
            for case in default_cases(ROUNDS):
                decoded = run_ideal(case.faults, shots=8, decoder=decoder, window=window)
                expected_failure = case.name == "x_D1_D4"
                self.assertTrue((decoded.logical_failure == expected_failure).all(),
                                f"{case.name} {decoder} {window}")

    def test_realtime_decoder_waits_for_the_next_round(self):
        # Z1 misread in round 2: pending after round 2, explained after round 3 with no data fix.
        decoded = run_ideal([Fault("M", "Z1", 2)], shots=1, window=1)
        self.assertEqual(decoded.pending_z[0, 1].tolist(), [0, 1, 0, 0])
        self.assertFalse(decoded.pending_z[0, 2].any())
        self.assertFalse(decoded.corr_x.any())
        self.assertEqual(decoded.commit_x.tolist(), [1, 2, 3, 3])  # round r fixed after round r+1
        names = [name for name, _ in shot_frames(decoded, 0)]
        frames = dict(shot_frames(decoded, 0))
        self.assertEqual(frames[names[6]]["Sz"], ["off", "flagged", "off", "off"])  # round 2 decode: pending
        self.assertEqual(frames[names[9]]["Sz"], ["off"] * 4)                       # round 3 decode: resolved
        self.assertEqual(frames[names[9]]["Data"], ["on"] * 9)
        self.assertIn("decides round 2", names[9])

        # Window 0 has no look-ahead: it "fixes" a data qubit in round 2 and undoes it in round 3.
        greedy = run_ideal([Fault("M", "Z1", 2)], shots=1, window=0)
        self.assertEqual(greedy.corr_x[0, 1].sum(), 1)
        self.assertTrue((greedy.corr_x[0, 1] == greedy.corr_x[0, 2]).all())
        self.assertFalse(greedy.logical_failure[0])

    def test_realtime_frames_show_the_correction_when_it_is_committed(self):
        decoded = run_ideal([Fault("X", 4, 2)], shots=1, window=1)
        frames = shot_frames(decoded, 0)
        self.assertEqual(len(frames), 1 + 3 * ROUNDS + 2)
        self.assertEqual(frames[6][1]["Data"], ["on"] * 9)        # round 2 decode: still waiting
        self.assertEqual(frames[6][1]["Sz"], ["off", "flagged", "flagged", "off"])
        self.assertEqual(frames[9][1]["Data"][4], "x")            # round 3 decode: X on D5 fixed
        self.assertEqual(frames[9][1]["Sz"], ["off"] * 4)

    def test_parse_fault(self):
        self.assertEqual(parse_fault("x:d5@2"), Fault("X", 4, 2))
        self.assertEqual(parse_fault("M:Z1@3"), Fault("M", "Z1", 3))
        with self.assertRaises(ValueError):
            parse_fault("X:D0@2")

    def test_ideal_builtin_cases_behave_as_designed(self):
        for case in default_cases(ROUNDS):
            decoded = run_ideal(case.faults)
            expected_failure = case.name == "x_D1_D4"
            self.assertTrue((decoded.logical_failure == expected_failure).all(), case.name)
            if case.name == "idle":
                self.assertFalse(decoded.has_detections().any())

    def test_every_single_data_error_is_corrected(self):
        for q in range(9):
            for kind in "XYZ":
                for round_ in range(1, ROUNDS + 2):
                    decoded = run_ideal([Fault(kind, q, round_)], shots=4)
                    self.assertFalse(decoded.logical_failure.any(), f"{kind} D{q + 1} @{round_}")

    def test_data_and_measurement_errors_leave_different_signatures(self):
        data = run_ideal([Fault("X", 4, 2)], shots=1)
        self.assertEqual(data.det_z[0, 1].tolist(), [0, 1, 1, 0])  # round 2 only
        self.assertFalse(data.det_z[0, 2].any())
        self.assertEqual(data.corr_x[0, 1].tolist(), [0, 0, 0, 0, 1, 0, 0, 0, 0])

        meas = run_ideal([Fault("M", "Z1", 2)], shots=1)
        self.assertEqual(meas.det_z[0, 1].tolist(), [0, 1, 0, 0])  # round 2 ...
        self.assertEqual(meas.det_z[0, 2].tolist(), [0, 1, 0, 0])  # ... and round 3
        self.assertFalse(meas.corr_x.any())  # no data error inferred

    def test_frames_have_led_format_and_verdict_on_last_frame(self):
        decoded = run_ideal([Fault("X", 0, 2), Fault("X", 3, 2)], shots=1)
        frames = shot_frames(decoded, 0)
        self.assertEqual(len(frames), 1 + 3 * ROUNDS + 2)
        self.assertTrue(frames[0][1]["reset"])
        self.assertTrue(frames[-1][1]["logical failure"])
        self.assertFalse(any(frame["logical failure"] for _, frame in frames[:-1]))
        for _, frame in frames:
            self.assertEqual(set(frame), {"Data", "Sz", "Sx", "logical failure", "reset"})
            self.assertTrue(set(frame["Data"]) <= {"on", "x", "y", "z"})

    def test_rz_merge_keeps_the_circuit_and_makes_it_clifford(self):
        from qiskit import QuantumCircuit
        from qiskit.quantum_info import Operator

        circuit = QuantumCircuit(2)
        circuit.rz(np.pi / 4, 0)
        circuit.cz(0, 1)
        circuit.rz(np.pi / 4, 0)
        circuit.sx(0)
        merged = merge_rz_through_cz(circuit)
        self.assertTrue(Operator(merged).equiv(Operator(circuit)))
        angles = [float(i.operation.params[0]) for i in merged.data if i.operation.name == "rz"]
        self.assertEqual(angles, [np.pi / 2])


if __name__ == "__main__":
    unittest.main()
