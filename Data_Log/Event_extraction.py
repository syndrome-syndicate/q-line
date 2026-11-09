class EventDetection:
    def __init__(self):
        self.events = []

    def detect_event(self, event_data: dict):
        self.events.append(event_data)
        return event_data

    def get_qubit_location(self, event_data: dict):
        return event_data.get("qubit_location", None)

    def get_all_events(self):
        return self.events

    def clear_events(self):
        self.events.clear()
        return True

    def event_classification(self, event_data: dict):
        # Implement your event classification logic here
        event_classes = ['X', 'Z', 'H']
        event_type = event_data.get("type", "")
        if event_type in event_classes:
            classification = event_type
        else:
            classification = ValueError("Unknown event type")  # Replace with actual classification logic
            raise classification
        event_data["classification"] = classification
        return event_data

    def noise_depolarization(self, event_data: dict):
        # Implement your noise depolarization logic here
        event_type = event_data.get("type", "")
        if event_type == "depolarizing":
            classification = "noise_depolarization"
        else:
            classification = "unknown"  # Replace with actual classification logic
        event_data["classification"] = classification
        return event_data

    def decoding_event(self, event_data: dict):
        # run decoder file here
        import subprocess
        # Replace the following line with the actual command to run your decoder script
        subprocess.run(["python", "decoder.py", "--event_data", str(event_data)])
        return event_data

