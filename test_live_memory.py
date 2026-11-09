import json
import tempfile
import unittest

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from Data_Log.Pico_Frames import PicoFrameWriter, make_frame
from Simulation_Logic.memory import STEPS, SurfaceCodeMemory


def run_cycle(memory):
    return [memory.step() for _ in STEPS]


class LiveMemoryTests(unittest.TestCase):
    def test_every_single_error_is_corrected(self):
        memory = SurfaceCodeMemory(seed=3)
        for inject_before in range(len(STEPS)):  # before X checks, Z checks, decode
            for qubit in range(9):
                for pauli in "XYZ":
                    memory.reset()
                    for _ in range(inject_before):
                        memory.step()
                    memory.inject(qubit, pauli)
                    for _ in range(2):
                        run_cycle(memory)
                    label = f"{pauli} on D{qubit} before step {inject_before}"
                    self.assertFalse(memory.logical_failed, label)
                    self.assertEqual(memory.errors, {}, label)
                    self.assertEqual(memory.logical_z_expectation(), 1.0, label)

    def test_weight_two_error_causes_flagged_logical_failure(self):
        memory = SurfaceCodeMemory(seed=3)
        memory.inject(0, "X")
        memory.inject(3, "X")
        results = run_cycle(memory)
        self.assertEqual(results[2].correction, {6: "X"})
        self.assertTrue(memory.logical_failed)
        self.assertEqual(memory.logical_z_expectation(), -1.0)

    def test_frame_shows_measured_and_flagged_checks(self):
        memory = SurfaceCodeMemory(seed=3)
        memory.inject(4, "Z")
        x_step = memory.step()
        frame = make_frame(memory.errors, x_step, memory.logical_failed)
        self.assertEqual(frame["Data"][4], "z")
        self.assertEqual(frame["Sx"], ["on", "flagged", "flagged", "on"])
        self.assertEqual(frame["Sz"], ["off"] * 4)
        z_step = memory.step()
        frame = make_frame(memory.errors, z_step, memory.logical_failed)
        self.assertEqual(frame["Sz"], ["on"] * 4)
        # X flags stay lit while the Z checks run, until the decoder uses them
        self.assertEqual(frame["Sx"], ["off", "flagged", "flagged", "off"])
        decode = memory.step()
        frame = make_frame(memory.errors, decode, memory.logical_failed)
        self.assertEqual(frame["Data"], ["on"] * 9)
        self.assertEqual(frame["Sx"], ["off", "flagged", "flagged", "off"])
        self.assertEqual(
            set(frame), {"Data", "Sz", "Sx", "logical failure", "reset"}
        )
        reset = make_frame({}, None, reset=True)
        self.assertTrue(reset["reset"])

    def test_buttons_write_one_frame_per_step_and_reset(self):
        from Live_visualizer import LiveVisualizer

        def click(button):
            button._observers.process("clicked", None)

        with tempfile.TemporaryDirectory() as root:
            app = LiveVisualizer(seed=1, out_root=root)
            click(app.gate_buttons["Y"])
            click(app.qubit_buttons[2])
            for _ in range(3):
                click(app.next_button)
            click(app.reset_button)
            files = sorted(app.writer.directory.glob("frame_*.json"))
            frames = [json.loads(f.read_text()) for f in files]
            self.assertEqual(len(frames), 5)  # start + 3 steps + reset
            self.assertTrue(frames[0]["reset"] and frames[-1]["reset"])
            self.assertEqual(frames[1]["Data"][2], "y")
            self.assertIn("flagged", frames[1]["Sx"])
            self.assertEqual(frames[3]["Data"], ["on"] * 9)
            plt.close(app.fig)

    def test_every_saved_frame_is_sent_to_the_led_panel(self):
        from Data_Log.Pico_Link import PicoLink
        from Live_visualizer import LiveVisualizer

        class FakeDevice:
            port = "FAKE"

            def __init__(self):
                self.sent = []

            def send_next(self, panel, reset=False):
                panel.payload(reset=reset)  # the real firmware-contract validation
                self.sent.append((panel, reset))
                return {"type": "ack", "ok": True, "revision": len(self.sent)}

            def close(self):
                pass

        def click(button):
            button._observers.process("clicked", None)

        device = FakeDevice()
        link = PicoLink(device=device)
        with tempfile.TemporaryDirectory() as root:
            app = LiveVisualizer(seed=1, out_root=root, led=link)
            click(app.qubit_buttons[4])
            for _ in range(3):
                click(app.next_button)
            click(app.reset_button)
            link.wait()
            files = sorted(app.writer.directory.glob("frame_*.json"))
            frames = [json.loads(f.read_text()) for f in files]
            self.assertEqual(len(device.sent), len(frames))
            for (panel, reset), frame in zip(device.sent, frames):
                self.assertEqual(panel.d, frame["Data"])
                self.assertEqual(panel.z, frame["Sz"])
                self.assertEqual(panel.x, frame["Sx"])
                self.assertEqual(panel.logical_failure, frame["logical failure"])
                self.assertEqual(reset, frame["reset"])
            self.assertEqual([reset for _, reset in device.sent], [True, False, False, False, True])
            self.assertIn("revision 5", link.status)
            app.close()
            plt.close(app.fig)

    def test_replay_mode_resends_a_saved_run(self):
        from Live_visualizer import LiveVisualizer

        class FakeLink:
            connected, status = True, "fake"

            def __init__(self):
                self.frames = []

            def send(self, frame):
                self.frames.append(frame)

            def close(self):
                pass

        def click(button):
            button._observers.process("clicked", None)

        with tempfile.TemporaryDirectory() as root:
            link = FakeLink()
            app = LiveVisualizer(seed=1, out_root=root, led=link)
            click(app.qubit_buttons[6])
            for _ in range(4):
                click(app.next_button)
            run_folder = app.writer.directory
            recorded = [json.loads(f.read_text()) for f in sorted(run_folder.glob("*.json"))]
            self.assertEqual(link.frames, recorded)

            link.frames.clear()
            app.choose_folder(run_folder)  # switches to Replay, shows frame 1
            self.assertEqual(app.mode, "Replay")
            self.assertFalse(app.qubit_buttons[0].active)
            click(app.qubit_buttons[0])  # injection is off in Replay
            for _ in range(10):  # runs past the end: stops at the last frame
                click(app.next_button)
            self.assertEqual(link.frames, recorded)
            self.assertEqual(len(list(run_folder.glob("*.json"))), len(recorded))  # nothing re-saved

            click(app.reset_button)  # Restart: frame 1 again, clearing the panel
            self.assertEqual(app.replay_index, 0)
            self.assertTrue(link.frames[-1]["reset"])

            app.set_mode("Live")
            self.assertEqual(app.mode, "Live")
            self.assertTrue(app.qubit_buttons[0].active)
            self.assertTrue(link.frames[-1]["reset"])
            plt.close(app.fig)

    def test_writer_uses_one_folder_per_run(self):
        with tempfile.TemporaryDirectory() as root:
            first, second = PicoFrameWriter(root), PicoFrameWriter(root)
            self.assertNotEqual(first.directory, second.directory)
            path = first.write(make_frame({}, None, reset=True))
            self.assertEqual(path.name, "frame_0000.json")


if __name__ == "__main__":
    unittest.main()
