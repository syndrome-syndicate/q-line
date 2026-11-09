"""
Stepwise simulation module for the surface code simulation.
Step 1) Build the initial circuit state as an independent data structure.
Step 2) Run 3-4 rounds based on checks (X, Z stabilizers, and then decoding round)
Step 3) Event listener for detecting fault injection events
Step 4) Check for errors and update the circuit state accordingly.
"""
class CircuitDiagram:
    def __init__(self, circuit):
        self.circuit = circuit

    def count(self, event_type=None):
        event_count = []
        for event in self.circuit:
            if event_type is None or event == event_type:
                event_count.append(event)
        return len(event_count)

    def draw(self):
        # 3x3 data qubit layout for surface code w/ 4 Z stabilizers and 4 X stabilizers
        layout = [
            [None, None, None, None, None,'Z', None],
            [None, 'D', None, 'D', None, 'D', None],
            ['X', None, 'Z', None, 'X', None, None],
            [None, 'D', None, 'D', None, 'D', None],
            [None, None, 'X', None, 'Z', None, 'X'],
            [None, 'D', None, 'D', None, 'D', None],
            [None, None, 'Z', None, None, None, None]
        ]
        for row in layout:
            print(' '.join(row))
        print()

        print("Circuit Diagram:")
        for row in self.circuit:
            print(' '.join(row))
        print()

class StepwiseSimulation:
    def __init__(self):
        self.circuit = None
        self.circuit_state = None
        self.events = []

    def build_initial_circuit_state(self, circuit):
        self.circuit = circuit
        self.circuit_state = circuit.copy()

    def run_rounds(self, num_rounds=4):    
        for _ in range(num_rounds):
            self.circuit_diagram = CircuitDiagram(self.circuit)
            self.circuit_diagram.draw()
            self.check_errors_and_update_state()
            for _ in range(num_rounds):
                if self.events == ['Z']:
                    print(self.circuit_diagram.count())
                elif self.events == ['X']:
                    self.circuit_diagram.count('X')
                    print(self.circuit_diagram.count())
                else:
                    # Handle other events
                    pass
            self.events.clear()
            self.circuit_diagram = None

    def detect_event(self, event_data):
        self.events.append(event_data)

    def check_errors_and_update_state(self):
        if detected_errors := self.detect_errors():
            self.update_circuit_state(detected_errors)
            self.circuit_diagram = CircuitDiagram(self.circuit)
            self.circuit_diagram.draw()

    def detect_errors(self):
        if 'Z' in self.circuit_state:
            return ['Z']
        if 'X' in self.circuit_state:
            return ['X']
        if 'Z' in self.circuit_state and 'X' in self.circuit_state:
            return ['Z', 'X']
        if 'X' in self.circuit_state and 'Z' in self.circuit_state:
            return ['X', 'Z']
        return []

    def update_circuit_state(self, detected_errors):
        # Implement the logic for updating the circuit state based on detected errors
        for error in detected_errors:
            if error == 'Z':
                self.circuit_state.append('Z')
            if error == 'X':
                self.circuit_state.append('X')