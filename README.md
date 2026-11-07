# The Syndrome Tesseract
A physical QEC visualization instrument built on a distance-3 rotated surface code.
NOTE: Even without the device, the target of the project is to use qiskit to exec the circuit/run error correction/identify results... same idea even w/o physical interface

```
Fellas, FYI my plan is to use this as a dumping ground for all the things, broken down by sections. 
When we get closer to submission we can think about if/how we want to break out the info.
For now, I'll use this as your one stop shop for all the things. 
Feel free to edit/comment/etc. Also everyone has owner access to the org; PRETTY PLEASE be responsible.
```

## The Physical Device (WIP, this describes ultimate target)
One acrylic plane displays 17 LEDs: 9 data qubit dots and 8 stabilizer checks (cyan = X-type, amber = Z-type). Stretch goal = 3 planes each representing a round. A rotary encoder scrubs through syndrome rounds. A visitor injects data or measurement faults via buttons, toggles between raw syndrome and detection event views, and presses decode to run PyMatching. A single verdict LED shows logical success or failure.
The core takeaway: a data error and a measurement error leave different spacetime signatures. The instrument makes that difference physically visible.

## Stack (Feel free to explore, but this looked like a decent starting point... note that I did find a lib that was deprecated last month/we can review tomorrow afo)
- Qiskit + Aer: repeated stabilizer extraction circuit, fault injection, measurement records
- PyMatching: detection event decoding
- Raspberry Pi / TBD for simulation pipeline (also have AGX Xavier and other compute available, could even be laptop/etc.)
- RP2040: button input, LED chain control
- Addressable LEDs w/hardware abstraction layer

# Refernece Materials 
- [START HERE: QFF_Hackathon_Prompts.pdf](https://github.com/CU-Boulder-Qiskit-Fall-Fest/Hackathon_Prompts/blob/main/QFF_Hackathon_Prompts.pdf) - follow the steps at the top to get qiskit installed and running
- [Paper: Fault-Tolerant Stabilizer Measurements in Surface Codes with Three-Qubit Gates
](https://arxiv.org/abs/2506.09029) - great reference material, more deep than we need, but solid visuals  
- [NVIDIA QEC reference](https://nvidia.github.io/cudaq-qec/components/qec/codes.html) - not what we will be using, but helpful for well-rounded understanding
- [BWC: Hello Quantum](https://github.com/brainwavecollective/hello-quantum) - MIGHT work (quantum libraries have atrocious dependency problems) but this was our hello world ref... my goal was as simple as possible (will revisit this weekend to confirm if I have time)
- [BWC: Quantum Paradoxes](https://github.com/brainwavecollective/quantum-paradoxes) - fork of what I found to be a very useful/interesting way of visualizing. Projects are interesting and the content is awesome. Helped me understand circuits.

# Timeline 
### Saturday
- 12-no later than 4 Daniel & co & [Bldg 61](https://boulderlibrary.org/makerspaces/bldg-61/) figuring out the physical device (we have POC already, but hopefully can come up with a cool final form) 
- 4-TBD @ main event 

### Sunday 
- all day @ main event 

### Monday 
- Finalize all the things 
- PM project status review 

### Tuesday 
- AM polish 
- Submission at noon 

# SUBMISSION INFO 
We'll need a Jupyter notebook w/5 minute video
