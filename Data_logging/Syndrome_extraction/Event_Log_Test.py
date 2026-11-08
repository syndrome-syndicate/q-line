import random
import sys
from pathlib import Path
from Event_Mapping import EventMap
from Experiment_Logger import ExperimentLogger
from Event_extraction import EventDetection

### Test Event Logging with EventMap, ExperimentLogger, and EventDetection

event_map = EventMap()
experiment_logger = ExperimentLogger(log_dir="logs")
event_detection = EventDetection()

### Randomly generate some events to the event_map
### Add a circuit simulation component to the event map based on .circuits


repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import Simulation_Logic.circuits
circuit = Simulation_Logic.circuits.create_surface_code_circuit()
event_map.add_event("circuit_simulation", "Simulation", "Circuit")

random.seed(42)
for i in range(3):
    event_id = f"event_{i}"
    event_type = random.choice(["Error", "Correction", "Warning"])
    event_classification = random.choice(["X", "Z", "H"])
    step_count = random.randint(0, 10)
    qubits = random.sample(range(25), 1)  # Assuming 25 qubits in the circuit
    gates = random.sample(["X", "Z", "H"], 1)  # Assuming 3 types of gates in the circuit
    measurement = random.choice(["X", "Z", "H"])  # Assuming 3 types of measurements in the circuit
    errors = random.sample(["X", "Z", "H"], 1)  # Assuming 3 types of errors in the circuit
    shots = random.randint(100, 20000)  # Assuming 100 to 1000 shots in the circuit
    metadata = {"step_count": step_count, "qubits": qubits, "gates": gates, "measurement": measurement, "errors": errors, "shots": shots}
    event_map.add_event(event_id, event_type, event_classification, step_count=step_count, qubits=qubits, gates=gates, measurement=measurement, errors=errors, shots=shots, metadata=metadata)

### Log the events using the experiment_logger
experiment_logger.log_experiment(event_map.get_all_events("logs"))

### Detect events using the event_detection
detected_events = event_detection.detect_event(event_map.get_all_events("logs"))
print("Detected events:", detected_events)

### Print the event map for verification
print("Event map:", event_map.get_all_events("logs"))
print("Event sequence:", event_map.get_event_sequence())
print("Event types:", event_map.get_event_types())
print("Event classifications:", event_map.get_event_classifications())
print("First event ID:", event_map.get_first_event_id())
print("Last event ID:", event_map.get_last_event_id())
print("Event count:", event_map.get_event_count())
print("Event index:", event_map.get_event_index())