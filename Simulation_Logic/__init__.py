"""
Simulation logic for a simple quantum circuit using Qiskit & QEC Pipeline
"""

### Make sure these modules are properly defined and accessible

from .circuits import create_surface_code_circuit
from .fault_injection import inject_fault
from .decoder import decoder
from .Stepwise_simulation import StepwiseSimulation
from .memory import SurfaceCodeMemory
from .live import build_round_steps, fault_location, simulate_history


__version__ = "0.1.0"
__all__ = [
    "StepwiseSimulation",
    "SurfaceCodeMemory",
    "build_round_steps",
    "fault_location",
    "simulate_history",
    "create_surface_code_circuit",
    "decoder",
    "inject_fault",
]