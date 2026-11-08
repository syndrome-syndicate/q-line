import random
from Event_Mapping import EventMap
from Experiment_Logger import ExperimentLogger
from Event_extraction import EventDetection

### Test Event Logging with EventMap, ExperimentLogger, and EventDetection

event_map = EventMap()
experiment_logger = ExperimentLogger(log_dir="logs")
event_detection = EventDetection()

### Randomly generate some events to the event_map
random.seed(42)
for i in range(3):
    event_id = f"event_{i}"
    event_type = random.choice(["Error", "Correction", "Warning"])
    event_classification = random.choice(["X", "Z", "H"])
    event_map.add_event(event_id, event_type, event_classification)

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