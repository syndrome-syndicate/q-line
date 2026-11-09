"""
Build repeated syndrome-extraction rounds for a rotated distance-3 surface code.
"""

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

# Layout of the LED panel. Data qubits are labelled D1..D9 on the panel and
# indexed 0..8 here, row by row:
#     D1 D2 D3        0 1 2
#     D4 D5 D6   ->   3 4 5
#     D7 D8 D9        6 7 8
# Z0 = D1 D4 (left edge)     X0 = D2 D3 (top edge)
# Z1 = D2 D3 D5 D6           X1 = D1 D2 D4 D5
# Z2 = D4 D5 D7 D8           X2 = D5 D6 D8 D9
# Z3 = D6 D9 (right edge)    X3 = D7 D8 (bottom edge)
Z_CHECK_SUPPORTS = ((0, 3), (1, 2, 4, 5), (3, 4, 6, 7), (5, 8))
X_CHECK_SUPPORTS = ((1, 2), (0, 1, 3, 4), (4, 5, 7, 8), (6, 7))

# Where each check sits on the board, in grid units (data qubit k is at the
# centre of cell (column + 0.5, row + 0.5)).
Z_CHECK_POSITIONS = ((0, 1), (2, 1), (1, 2), (3, 2))
X_CHECK_POSITIONS = ((2, 0), (1, 1), (2, 2), (1, 3))


def data_label(qubit: int) -> str:
    """Panel label of data qubit index 0..8."""
    return f"D{qubit + 1}"


def prepare_logical_zero(circuit: QuantumCircuit, data) -> None:
    """Prepare |0_L> as the uniform superposition of the X-check supports."""
    x_rows = [
        sum(1 << data_index for data_index in support)
        for support in X_CHECK_SUPPORTS
    ]
    pivots = []
    pivot_row = 0
    for column in range(9):
        selected = next(
            (row for row in range(pivot_row, len(x_rows)) if x_rows[row] >> column & 1),
            None,
        )
        if selected is None:
            continue
        x_rows[pivot_row], x_rows[selected] = x_rows[selected], x_rows[pivot_row]
        for row in range(len(x_rows)):
            if row != pivot_row and x_rows[row] >> column & 1:
                x_rows[row] ^= x_rows[pivot_row]
        pivots.append(column)
        pivot_row += 1

    for row_index, pivot in enumerate(pivots):
        circuit.h(data[pivot])
        for column in range(9):
            if column != pivot and x_rows[row_index] >> column & 1:
                circuit.cx(data[pivot], data[column])


def append_x_checks(circuit: QuantumCircuit, data, ancilla_x, clbits) -> None:
    """Measure the 4 X checks into ``clbits`` and reset their ancillas."""
    circuit.h(ancilla_x)
    for check_index, support in enumerate(X_CHECK_SUPPORTS):
        for data_index in support:
            circuit.cx(ancilla_x[check_index], data[data_index])
    circuit.h(ancilla_x)
    for check_index in range(4):
        circuit.measure(ancilla_x[check_index], clbits[check_index])
    circuit.reset(ancilla_x)


def append_z_checks(circuit: QuantumCircuit, data, ancilla_z, clbits) -> None:
    """Measure the 4 Z checks into ``clbits`` and reset their ancillas."""
    for check_index, support in enumerate(Z_CHECK_SUPPORTS):
        for data_index in support:
            circuit.cx(data[data_index], ancilla_z[check_index])
    for check_index in range(4):
        circuit.measure(ancilla_z[check_index], clbits[check_index])
    circuit.reset(ancilla_z)


def create_surface_code_circuit(num_rounds: int = 3) -> QuantumCircuit:
    if not isinstance(num_rounds, int) or isinstance(num_rounds, bool):
        raise TypeError("num_rounds must be an integer")
    if num_rounds < 1:
        raise ValueError("num_rounds must be at least 1")

    data = QuantumRegister(9, "data")
    ancilla_x = QuantumRegister(4, "ancilla_x")
    ancilla_z = QuantumRegister(4, "ancilla_z")
    classical_x = ClassicalRegister(4 * num_rounds, "classical_x")
    classical_z = ClassicalRegister(4 * num_rounds, "classical_z")
    circuit = QuantumCircuit(data, ancilla_x, ancilla_z, classical_x, classical_z)

    prepare_logical_zero(circuit, data)

    for round_index in range(num_rounds):
        circuit.barrier(label=f"round_{round_index}_start")
        bits = slice(4 * round_index, 4 * round_index + 4)
        append_x_checks(circuit, data, ancilla_x, classical_x[bits])
        circuit.barrier(label=f"round_{round_index}_mid")
        append_z_checks(circuit, data, ancilla_z, classical_z[bits])
        circuit.barrier(label=f"round_{round_index}_end")

    circuit.barrier(label="final_reset")
    circuit.reset(data)
    circuit.reset(ancilla_x)
    circuit.reset(ancilla_z)
    return circuit


if __name__ == "__main__":
    print(create_surface_code_circuit())
