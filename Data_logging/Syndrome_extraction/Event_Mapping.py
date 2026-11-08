class EventMap:
    def __init__(self):
        self.event_map = {}
        self.event_count = 0
        self.last_event_id = None
        self.first_event_id = None
        self.event_sequence = []
        self.event_index = 0
        self.event_types = []
        self.event_classifications = []

    def add_event(self, event_id, event_type, event_classification, steps=None, qubits=None, gates=None, measurement=None, errors=None, shots=None, metadata=None):
        self.event_map[event_id] = {
            "type": event_type,
            "classification": event_classification,
            "qubit_location": f"qubit_{event_id}",
            "steps": steps,
            "qubits": qubits,
            "gates": gates,
            "measurement": measurement,
            "errors": errors,
            "shots": shots,
            "metadata": metadata
        }
        self.event_count += 1
        self.last_event_id = event_id
        if self.first_event_id is None:
            self.first_event_id = event_id
        self.event_sequence.append(event_id)
        self.event_types.append(event_type)
        self.event_classifications.append(event_classification)
        self.event_index += 1
        return event_id

    def get_qubit_location(self, event_id):
        event = self.event_map.get(event_id, None)
        if event:
            return event.get("qubit_location", None)
        return None

    def get_event(self, event_id):
        return self.event_map.get(event_id, None)

    def get_all_events(self, log_dir):
        # Log the events to the specified log directory
        with open(f"{log_dir}/events.log", "w") as f:
            for event_id, event_data in self.event_map.items():
                f.write(f"{event_id}: {event_data}\n")
        return self.event_map

    def get_event_sequence(self):
        return self.event_sequence

    def get_event_types(self):
        return self.event_types

    def get_event_classifications(self):
        return self.event_classifications

    def get_first_event_id(self):
        return self.first_event_id

    def get_last_event_id(self):
        return self.last_event_id

    def get_event_count(self):
        return self.event_count

    def get_event_index(self):
        return self.event_index