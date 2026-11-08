"""
Distance -5 surf. code circuit construct using Qiskit modules/packages
"""
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

def create_surface_code_circuit():
    # Define quantum registers
    # use 25 data qubits for distance-5 surface code in accordance with prompt 2 constraints

    data_reg = QuantumRegister(25, 'data')
    ancilla_x = QuantumRegister(12, 'ancilla_x')
    ancilla_z = QuantumRegister(12, 'ancilla_z')
    # Classical registers for measurement outcomes
    classical_z = ClassicalRegister(12, 'classical_z')
    classical_x = ClassicalRegister(12, 'classical_x')


    # Create the quantum circuit
    circuit = QuantumCircuit(data_reg, ancilla_x, ancilla_z, classical_z, classical_x)

    # Syndrome ExtractionRounds
    for round_idx in range(3):
        # Reset the round index at the beginning of each iteration
        round_idx = 0
        # Perform syndrome extraction for each round
        # Apply the necessary gates for syndrome extraction
        for i in range(12):
            circuit.cx(data_reg[i], ancilla_x[i])
            circuit.cx(data_reg[i], ancilla_z[i])
        # Measure the ancilla qubits
        for i in range(12):
            circuit.measure(ancilla_x[i], classical_x[i])
            circuit.measure(ancilla_z[i], classical_z[i])
        circuit.barrier()
        circuit.reset(ancilla_x)
        circuit.reset(ancilla_z)
        round_idx += 1
    return circuit

if __name__ == "__main__":
    circuit = create_surface_code_circuit()
    print(circuit)