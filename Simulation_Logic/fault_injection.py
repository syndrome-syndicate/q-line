"""
Fault injection module for the surface code simulation.
"""

def inject_fault(circuit, qubit, gate):
    if gate == 'X':
        circuit.x(qubit)
    elif gate == 'Z':
        circuit.z(qubit)
    elif gate == 'H':
        circuit.h(qubit)
    else:
        raise ValueError(f"Unsupported gate type: {gate}")

if __name__ == "__main__":
    from qiskit import QuantumCircuit
    circuit = QuantumCircuit(3)
    inject_fault(circuit, 0, 'X')
    inject_fault(circuit, 1, 'Z')
    inject_fault(circuit, 2, 'H')
    print(circuit)