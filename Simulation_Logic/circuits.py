"""
Build repeated syndrome-extraction rounds for a rotated distance-3 surface code.
"""

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

Z_CHECK_SUPPORTS = ((3, 6), (0, 1, 3, 4), (4, 5, 7, 8), (2, 5))
X_CHECK_SUPPORTS = ((0, 1), (3, 4, 6, 7), (1, 2, 4, 5), (7, 8))


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

    # Prepare |0_L> as the uniform superposition of the X-check supports.
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

    for round_index in range(num_rounds):
        circuit.barrier(label=f"round_{round_index}_start")

        circuit.h(ancilla_x)
        for check_index, support in enumerate(X_CHECK_SUPPORTS):
            for data_index in support:
                circuit.cx(ancilla_x[check_index], data[data_index])
        circuit.h(ancilla_x)
        for check_index in range(4):
            circuit.measure(
                ancilla_x[check_index], classical_x[4 * round_index + check_index]
            )
        circuit.reset(ancilla_x)

        for check_index, support in enumerate(Z_CHECK_SUPPORTS):
            for data_index in support:
                circuit.cx(data[data_index], ancilla_z[check_index])
        for check_index in range(4):
            circuit.measure(
                ancilla_z[check_index], classical_z[4 * round_index + check_index]
            )
        circuit.reset(ancilla_z)
        circuit.barrier(label=f"round_{round_index}_end")

    circuit.barrier(label="final_reset")
    circuit.reset(data)
    circuit.reset(ancilla_x)
    circuit.reset(ancilla_z)
    return circuit


if __name__ == "__main__":
    print(create_surface_code_circuit())
