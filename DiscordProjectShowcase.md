# 🚨 Hackathon Submission for the Syndrome Syndicate 

### **👥 Team Members and File Submission** 
Daniel Ritchie [brainwavecoder9](https://github.com/brainwavecoder9), Mullai Vaneshwar Sampangi Raman [kuramaku88](https://github.com/kuramaku88), Timothy Williams [Manta4000](https://github.com/Manta4000), Sean Flannery [sflans99](https://github.com/sflans99)

### **💡 Project Overview**
**Q-Line** is an **Interactive Quantum Error Correction (QEC) application and physical timeline visualizer** for one of the most widely executed surface codes ([[9,1,3]]).

Our project makes quantum error correction approachable by connecting a live quantum circuit simulator to a purpose-built physical display that we call the Q-Line. Users can inject X, Y, and Z errors into data qubits, execute syndrome measurements, control the flow of information, and observe the decoding and correction process while exploring how logical failures emerge.

Rather than displaying only the current state, our hardware preserves a **ten-step visual history**, allowing users to follow how errors propagate, how stabilizer measurements respond, and how corrections evolve over time. Physical controls and a bidirectional app interface enable users to interact with the simulation directly, while logging and replay features support deeper analysis. The user can pause the process at any time and see recent history.

**The problem we're exploring is how to make quantum error correction easier to understand, teach, and investigate.** We use physical intuition to transform abstract quantum operations into an interactive spatial and temporal experience, bridging the gap between theory and simulation.


### **⚛️ Quantum Computing & Qiskit**
The surface code is simulated using Qiskit, and we use a Minimum-Weight Perfect Matching (MWPM) decoder with PyMatching, drawing on quantum error correction research by Craig Gidney. The physical visualizer we built sends snapshots of the current code to the Qiskit backend, where syndrome measurements and decoding take place. The backend then returns the next state of the array, which is displayed on the physical visualizer.

Our unique approach includes a ten-step physical timeline, allowing users to interact with the circuitry in realtime and see the history of syndrome measurements, errors, and corrections rather than just the current state.

QEC is important, but can be hard to understand. We wanted to build something that other people could use to understand QEC better. 

### **🛠️ Implementation & results** 
We give the user an interactive experience where one can introduce errors at any time and see how they propagate, are corrected, or cause logical failures.

We built an interactive experience where users can introduce errors at any time and see how they propagate, are corrected, or cause logical failures. This experience is available both on an app, or through a physical device.

Users can also replay past runs, including runs from quantum hardware, to compare results and highlight potentially hardware-specific error patterns.

### **Project Links**
[GitHub: Q-Line project](https://github.com/syndrome-syndicate/q-line)  
[Notebook](https://github.com/syndrome-syndicate/q-line/blob/main/Submission_Doc.ipynb)  
[Video: Submission Demo](https://github.com/syndrome-syndicate/q-line/blob/main/Demonstration_video/video_submission.mp4)  
[Video: App/Display Integration](https://github.com/syndrome-syndicate/q-line/blob/main/q-line.mp4)  






