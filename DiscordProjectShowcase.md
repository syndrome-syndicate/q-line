**Q-Line: Hackathon Submission (Syndrome Syndicate)**

**Team:** Daniel Ritchie (brainwavecoder9), Mullai Vaneshwar Sampangi Raman (kuramaku88), Timothy Williams (Manta4000), Sean Flannery (sflans99)

**Overview:** Q-Line is an interactive quantum error correction (QEC) app and physical visualizer for the [[9,1,3]] surface code. Users inject X, Y, and Z errors, run syndrome measurements, and watch decoding and correction unfold. A ten-step visual history shows how errors propagate and corrections evolve, and users can pause at any time to review it. The goal is to make QEC easier to understand, teach, and investigate.

**How it works:** The code is simulated in Qiskit and decoded with a Minimum-Weight Perfect Matching (MWPM) decoder via PyMatching, based on research by Craig Gidney. The physical visualizer sends code snapshots to the Qiskit backend, which measures syndromes, decodes them, and returns the next state for display.

**Results:** The same experience runs in both the app and the device. Users can replay past runs, including runs from real quantum hardware, to spot possible hardware-specific error patterns. Building it also deepened our own understanding, since presenting the concepts chronologically made them clearer.

**Links:**
GitHub: https://github.com/syndrome-syndicate/q-line
Notebook: https://github.com/syndrome-syndicate/q-line/blob/main/Submission_Doc.ipynb
Demo: https://github.com/syndrome-syndicate/q-line/blob/main/Demonstration_video/video_submission.mp4
App/Display Integration: https://github.com/syndrome-syndicate/q-line/blob/main/q-line.mp4 (earlier demo; the color mapping bug it shows has since been fixed)
