"""
Distance -5 surf. code circuit construct using Qiskit modules/packages
"""
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

def create_surface_code_circuit(num_rounds: int = 3) -> QuantumCircuit:
    if not isinstance(num_rounds, int) or isinstance(num_rounds, bool):
        raise TypeError("num_rounds must be an integer")
    if num_rounds < 1:
        raise ValueError("num_rounds must be at least 1")

    # Define quantum registers
    # use 25 data qubits for distance-5 surface code in accordance with prompt 2 constraints

    data_reg = QuantumRegister(25, 'data')
    ancilla_x = QuantumRegister(12, 'ancilla_x')
    ancilla_z = QuantumRegister(12, 'ancilla_z')
    # Keep one persistent classical bit per check per round.
    classical_z = ClassicalRegister(12 * num_rounds, 'classical_z')
    classical_x = ClassicalRegister(12 * num_rounds, 'classical_x')

    # Create the quantum circuit
    circuit = QuantumCircuit(data_reg, ancilla_x, ancilla_z, classical_z, classical_x)

    for round_idx in range(num_rounds):
        circuit.barrier(label=f"round_{round_idx}_start")
        for i in range(12):
            circuit.cx(data_reg[i], ancilla_x[i])
            circuit.cx(data_reg[i], ancilla_z[i])
        for i in range(12):
            bit_index = round_idx * 12 + i
            circuit.measure(ancilla_x[i], classical_x[bit_index])
            circuit.measure(ancilla_z[i], classical_z[bit_index])
        circuit.barrier(label=f"round_{round_idx}_measurements")
        circuit.reset(ancilla_x)
        circuit.reset(ancilla_z)
        circuit.barrier(label=f"round_{round_idx}_end")
    return circuit

if __name__ == "__main__":
    circuit = create_surface_code_circuit()
    print(circuit)