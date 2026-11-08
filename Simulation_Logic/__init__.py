"""
Simulation logic for a simple quantum circuit using Qiskit & QEC Pipeline
"""

### Make sure these modules are properly defined and accessible

from .circuits import create_surface_code_circuit 
from .fault_injection import inject_fault
from .decoder import decoder


__version__ = "0.1.0"

"""
Example usage of the simulation logic.
"""

from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator

# Create a quantum circuit with 2 qubits and 2 classical bits
qc = QuantumCircuit(2, 2)

# Apply a Hadamard gate to qubit 0 (puts it in superposition)
qc.h(0)

# Apply a CNOT gate with control qubit 0 and target qubit 1 (entangles them)
qc.cx(0, 1)

# Measure both qubits
qc.measure([0, 1], [0, 1])

# Run the circuit on a local simulator
simulator = AerSimulator()
job = simulator.run(qc, shots=1024)
result = job.result()
counts = result.get_counts(qc)

print("Measurement outcomes:", counts)
