# Create a qec decoder playground
I was able to one-shot a playground with this prompt which helped get a sense of what the final product would look like and how it would work. Not at all something you need to run, but FYI in case you want to get a sense for how it works.
```
let's visualize surface code with an interactive qec decoder playground visualizer

We want to get a sense of what the board would look like. A distance-3 rotated surface code has 9 data qubits and 8 stabilizers (4 X-type, 4 Z-type). Print a grid with 9 data-qubit sockets and 8 stabilizer sites. Color the stabilizer plaquettes by type so the X/Z distinction is visible at a glance.

Inputs and outputs:
- Error injection: Put a tactile button under each data qubit. Each press cycles I → X → Z → Y, or you can use separate buttons for X and Z. Magnetic tokens over Hall sensors feel nicer but add fragility, so start with buttons.
- Syndrome display: An LED at each stabilizer site lights when that check is violated. Addressable WS2812B LEDs need only one data line but want a 5V-tolerant level shifter from the Pi’s 3.3V GPIO.
- Decoder output: Use a second LED color or a row of LEDs for the inferred correction, and a green/red indicator for whether the final residual error is a logical error. That verdict is the “aha” moment.
Compute. A Raspberry Pi 4 or 5 is plenty. PyMatching installs on ARM, and d=3 is tiny. For the Qiskit requirement, build the syndrome-extraction circuit with qiskit-qec, inject the Paulis the user pressed, and run it with Aer or a stabilizer simulator to read out the syndrome. The Pi then decodes and drives the LEDs. This keeps Qiskit doing the real circuit work, as the track asks. You could also skip simulation and compute syndromes by parity, but that wouldn’t satisfy the prompt.

Hardware path. You could drive everything from GPIO directly: 9 buttons, 1 LED data line, and maybe an MCP23017 I²C expander if you run short of pins. If input scanning gets messy, a Raspberry Pi Pico can handle the buttons and talk to the Pi over serial.

Printing. Use PETG or PLA for the base, with press-fit sockets for the switches. Print LED diffusers or light pipes in translucent filament so the stabilizer lights glow through the surface. Modular tiles that snap together let you scale to d=5 later without reprinting the whole board.

Stretch goal. Put LEDs along the lattice edges so PyMatching’s matched pairs light up as physical paths between defects. That’s the hardest-looking part to build but the most striking when it works.
```
