# The Q-Line
The Q-Line is a *QEC Syndrome Visualizer Timeline* for visualizing distance-3 rotated surface code using an interactive decoder and physical timeline display.  

<img src="display_integration.png" width="60%" alt="Q Line">

## The Physical Device 
One acrylic plane displays 17 LEDs: 9 data qubit dots and 8 stabilizer checks (cyan = X-type, amber = Z-type) and these panes are repeated for 10 sequential points in time. New events are added from right to left, allowing for a chronological left to right viewing of the last 10 events of the timeline history.

<img src="q-line.jpg" width="50%" alt="Q Line">

The sequential timeline input can be fully automatic from the computer or interrupted for manual intervention. A visitor injects data or modifies X/Y/Z faults via buttons and requests the next frame when ready. A rotary encoder sets modes which the app can define. 

The core takeaway: a data error and a measurement error leave different spacetime signatures. The instrument makes that difference physically visible.

You can also [watch a short video of the q-line running in realtime](q-line.mp4)

## Display Device Interface
See the [Display Device README](device/README.md) for setup, the Python API, JSON protocol, and emulator documentation.

You can run this locally with `uv run Run_Circuit.py`. If no physical device is detected, a local emulator launches automatically.

> [!WARNING]
>
> **Emulator is for interface development and testing only.**
>
> The emulator does **not** currently replicate the real device's firmware or behavior accurately. Use it only for testing the interface. Do not rely on it to validate hardware functionality or device-specific behavior.

# Reference Materials 
- [START HERE: QFF_Hackathon_Prompts.pdf](https://github.com/CU-Boulder-Qiskit-Fall-Fest/Hackathon_Prompts/blob/main/QFF_Hackathon_Prompts.pdf) - follow the steps at the top to get qiskit installed and running. ALSO there are solid links and ref materials in the doc itself (not all relevant). 
- [Paper/Code: Fault-Tolerant Stabilizer Measurements in Surface Codes with Three-Qubit Gates
]([https://arxiv.org/abs/2506.09029](https://github.com/oldjosias/three-qubit-ft-sc)) - the code and paper contain great reference material, more deep than we need, but solid visuals. code will be helpful for building circuit and timeline.
- [NVIDIA QEC reference](https://nvidia.github.io/cudaq-qec/components/qec/codes.html) - not what we will be using, but helpful for well-rounded understanding
- [BWC: Hello Quantum](https://github.com/brainwavecollective/hello-quantum) - MIGHT work (quantum libraries have atrocious dependency problems) but this was our hello world ref... my goal was as simple as possible (will revisit this weekend to confirm if I have time)
- [BWC: Quantum Paradoxes](https://github.com/brainwavecollective/quantum-paradoxes) - fork of what I found to be a very useful/interesting way of visualizing. Projects are interesting and the content is awesome. Helped me understand circuits.

