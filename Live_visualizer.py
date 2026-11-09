"""
Live surface-code memory with LED-panel frames.

    python Live_visualizer.py            # optional: --interval 500 --seed 1 --fault 5:X
    python Live_visualizer.py --replay data_to_pico/2026-11-08_23-25-44

Mode (top right):
    Live          the simulation below; every step is saved and sent to the LEDs
    Replay        play back a saved run (Choose folder...) on the screen and the
                  LEDs at the same time. Play/Pause, Next and Step (ms) work as
                  in Live; Restart starts the replay over; error buttons are off.
                  Replays are not saved again.

Buttons (Live):
    D1 .. D9      inject the selected error on that data qubit
    X / Y / Z     select the error type
    Play / Pause  auto-run one step every Step (ms) (default 500, or --interval)
    Step (ms)     type a new step time and press Enter
    Next step     run one step: X checks -> Z checks -> Decode + correct
    Reset         fresh qubits, re-encoded into |0_L>

Every Next step, every auto-run step and every Reset writes the array shown on
screen to data_to_pico/<date_time>/frame_NNNN.json (format: Data_Log/Pico_Frames.py)
and, if the Pico is plugged in, sends it to the LED panel right away
(Data_Log/Pico_Link.py). Reset frames clear the panel history. --no-led skips the USB.
Keys: space play/pause, n next, r reset, x/y/z error type, 1-9 inject.
Board layout and D1..D9 numbering: Simulation_Logic/circuits.py.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Button, RadioButtons, TextBox

from Data_Log.Pico_Frames import PicoFrameWriter, load_frames, make_frame
from Data_Log.Pico_Link import PicoLink
from Round_visualizer import DATA_POSITIONS, X_POSITIONS, Z_POSITIONS
from Simulation_Logic.circuits import X_CHECK_SUPPORTS, Z_CHECK_SUPPORTS, data_label
from Simulation_Logic.memory import PAULIS, STEPS, SurfaceCodeMemory

CHECK_COLORS = {"X": "#FB8C00", "Z": "#1E88E5"}
DATA_COLORS = {"on": "#4FC3F7", "x": "#E53935", "y": "#8E24AA", "z": "#F9A825"}
FLAGGED = "#D50000"
OFF = "#E6E6E6"
SELECTED = "#FFCC80"
IDLE_BUTTON = "0.95"
MIN_INTERVAL_MS = 50
MODES = ("Live", "Replay")


class LiveVisualizer:
    def __init__(self, interval_ms=500, seed=None, out_root="data_to_pico", faults=(), led=None,
                 replay=None):
        self.memory = SurfaceCodeMemory(seed=seed)
        self.out_root = Path(out_root)
        self.writer = PicoFrameWriter(out_root)
        self.mode = "Live"
        self.replay_folder: Path | None = None
        self.replay_frames: list = []  # [(path, frame), ...]
        self.replay_index = 0
        self.led = led  # PicoLink: every saved frame is also sent to the LED panel
        self.gate = "X"
        self.playing = False
        self.log = deque(maxlen=9)
        self.last_saved = None

        self.fig = plt.figure(figsize=(12, 8))
        self.fig.canvas.manager.set_window_title("Surface code memory -> LED panel")
        self.ax = self.fig.add_axes([0.03, 0.27, 0.52, 0.66])
        self.info = self.fig.add_axes([0.58, 0.27, 0.40, 0.57])

        self.mode_radio = RadioButtons(self.fig.add_axes([0.58, 0.86, 0.11, 0.11]), MODES)
        self.mode_radio.ax.set_title("Mode", fontsize=9, loc="left")
        self.mode_radio.on_clicked(self.set_mode)
        self.folder_button = Button(self.fig.add_axes([0.71, 0.89, 0.20, 0.06]), "Choose folder...")
        self.folder_button.on_clicked(lambda _e: self.choose_folder())

        self.qubit_buttons = []
        for qubit in range(9):
            button = Button(self.fig.add_axes([0.03 + qubit * 0.106, 0.15, 0.09, 0.065]), data_label(qubit))
            button.on_clicked(lambda _e, q=qubit: self.inject(q))
            self.qubit_buttons.append(button)
        self.gate_buttons = {}
        for index, gate in enumerate(PAULIS):
            button = Button(self.fig.add_axes([0.03 + index * 0.08, 0.04, 0.07, 0.07]), gate)
            button.on_clicked(lambda _e, g=gate: self.select_gate(g))
            self.gate_buttons[gate] = button
        self.play_button = Button(self.fig.add_axes([0.50, 0.04, 0.14, 0.07]), "Play")
        self.next_button = Button(self.fig.add_axes([0.66, 0.04, 0.14, 0.07]), "Next step")
        self.reset_button = Button(self.fig.add_axes([0.82, 0.04, 0.14, 0.07]), "Reset")
        self.play_button.on_clicked(self.toggle_play)
        self.next_button.on_clicked(self.next_step)
        self.reset_button.on_clicked(self.reset)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("close_event", lambda _event: self.close())

        self.timer = self.fig.canvas.new_timer(interval=interval_ms)
        self.timer.add_callback(self._tick)
        self.interval_box = TextBox(
            self.fig.add_axes([0.35, 0.04, 0.09, 0.07]), "Step (ms) ", initial=str(interval_ms)
        )
        self.interval_box.on_submit(self.set_interval)

        self._log("Encoded |0_L>.")
        for qubit, gate in faults:
            self._log(self.memory.inject(qubit, gate))
        self.select_gate("X")
        if replay is not None:
            self.choose_folder(replay)
        else:
            self._save(reset=True)  # LED panel starts from pristine qubits
            self.render()

    # ---------------------------------------------------------------- frames
    def current_frame(self, reset=False):
        return make_frame(
            self.memory.errors,
            self.memory.last_result,
            logical_failure=self.memory.logical_failed,
            reset=reset,
        )

    def _save(self, reset=False):
        if self.mode != "Live":
            return
        frame = self.current_frame(reset=reset)
        self.last_saved = self.writer.write(frame)
        if self.led is not None:
            self.led.send(frame)

    def close(self):
        self.writer.remove_if_empty()
        if self.led is not None:
            self.led.close()

    def _send(self, frame):
        if self.led is not None:
            self.led.send(frame)

    # ------------------------------------------------------------------ modes
    def set_mode(self, mode):
        if mode == self.mode:
            return
        if self.playing:
            self.toggle_play()
        self.mode = mode
        if self.mode_radio.value_selected != mode:
            self.mode_radio.set_active(MODES.index(mode))
        live = mode == "Live"
        for button in [*self.qubit_buttons, *self.gate_buttons.values()]:
            button.set_active(live)
            button.label.set_color("black" if live else "0.65")
        self.next_button.label.set_text("Next step" if live else "Next frame")
        self.reset_button.label.set_text("Reset" if live else "Restart")
        if live:
            self.reset()  # fresh qubits; also clears the LED panel
        elif self.replay_frames:
            self._restart_replay()
        else:
            self._log("Replay: choose a folder with frame_*.json files.")
            self.render()
            self.choose_folder()

    def choose_folder(self, folder=None):
        """Load a saved run (folder of frame_*.json) and switch to Replay."""
        if folder is None:
            folder = self._ask_folder()
            if not folder:
                self.render()
                return
        try:
            frames = load_frames(folder)
        except (OSError, ValueError) as error:
            self._log(f"Can't replay that folder: {error}")
            self.render()
            return
        self.replay_folder = Path(folder)
        self.replay_frames = frames
        self._log(f"Loaded {len(frames)} frames from {self.replay_folder.name}.")
        if self.mode != "Replay":
            self.set_mode("Replay")  # restarts the replay
        else:
            if self.playing:
                self.toggle_play()
            self._restart_replay()

    def _ask_folder(self):
        from tkinter import filedialog

        root = None
        try:
            parent = self.fig.canvas.get_tk_widget().winfo_toplevel()
        except AttributeError:  # not the Tk backend: use a hidden Tk window
            import tkinter

            root = parent = tkinter.Tk()
            root.withdraw()
        start = self.replay_folder.parent if self.replay_folder else self.out_root
        try:
            return filedialog.askdirectory(
                parent=parent,
                initialdir=str(start.resolve()) if start.exists() else None,
                title="Choose a run folder with frame_*.json files",
            )
        finally:
            if root is not None:
                root.destroy()

    def _restart_replay(self):
        """Show the first frame; it is sent with reset so the LED panel clears first."""
        self.replay_index = 0
        self._send(dict(self.replay_frames[0][1], reset=True))
        self._log(f"Replay started: frame 1 of {len(self.replay_frames)}.")
        self.render()

    def _replay_next(self):
        if not self.replay_frames:
            self._log("Replay: choose a folder first.")
            self.render()
            return
        if self.replay_index >= len(self.replay_frames) - 1:
            if self.playing:
                self.toggle_play()
            self._log("End of replay. Restart to play it again.")
            self.render()
            return
        self.replay_index += 1
        self._send(self.replay_frames[self.replay_index][1])
        self.render()

    # --------------------------------------------------------------- actions
    def select_gate(self, gate):
        self.gate = gate
        for name, button in self.gate_buttons.items():
            button.ax.set_facecolor(SELECTED if name == gate else IDLE_BUTTON)
        self.render()

    def inject(self, qubit):
        if self.mode != "Live":
            return
        self._log(self.memory.inject(qubit, self.gate))
        self.render()

    def next_step(self, _event=None):
        if self.playing:
            self.toggle_play()
        self._step()

    def _step(self):
        if self.mode == "Replay":
            self._replay_next()
            return
        result = self.memory.step()
        self._log(f"[cycle {result.cycle}] {result.message}")
        self._save()
        self.render()

    def _tick(self):
        if self.playing:
            self._step()

    def set_interval(self, text):
        """Change the time between auto-run steps (from the Step (ms) box)."""
        try:
            interval = int(float(text))
        except ValueError:
            interval = 0
        if interval < MIN_INTERVAL_MS:
            self._log(f"Step time must be a number >= {MIN_INTERVAL_MS} ms.")
            self.interval_box.set_val(str(self.timer.interval))
            self.render()
            return
        if interval == self.timer.interval:
            return
        self.timer.interval = interval
        if self.playing:  # restart so the new interval applies right away
            self.timer.stop()
            self.timer.start()
        self._log(f"Step time set to {interval} ms.")
        self.render()

    def toggle_play(self, _event=None):
        at_end = self.replay_frames and self.replay_index >= len(self.replay_frames) - 1
        if not self.playing and self.mode == "Replay" and at_end:
            self._restart_replay()  # Play at the end starts the replay over
        self.playing = not self.playing
        self.play_button.label.set_text("Pause" if self.playing else "Play")
        if self.playing:
            self.timer.start()
        else:
            self.timer.stop()
        self.render()

    def reset(self, _event=None):
        if self.mode == "Replay":
            if self.playing:
                self.toggle_play()
            if self.replay_frames:
                self._restart_replay()
            return
        self.memory.reset()
        self.log.clear()
        self._log("Reset: fresh qubits, encoded |0_L>.")
        self._save(reset=True)
        self.render()

    def _on_key(self, event):
        if self.interval_box.capturekeystrokes:  # typing in the Step (ms) box
            return
        key = (event.key or "").lower()
        if key == " ":
            self.toggle_play()
        elif key == "n":
            self.next_step()
        elif key == "r":
            self.reset()
        elif self.mode != "Live":
            return
        elif key.upper() in PAULIS:
            self.select_gate(key.upper())
        elif key.isdigit() and 1 <= int(key) <= 9:
            self.inject(int(key) - 1)

    def _log(self, message):
        self.log.append(message)

    # ---------------------------------------------------------------- render
    def render(self):
        if self.mode == "Replay":
            if self.replay_frames:
                path, frame = self.replay_frames[self.replay_index]
                title = f"Replay  |  {path.name}  ({self.replay_index + 1}/{len(self.replay_frames)})"
            else:
                frame, title = make_frame({}, None), "Replay  |  choose a folder"
            self._draw_board(frame, None, title)
            self._draw_replay_info(frame)
        else:
            frame = self.current_frame()
            result = self.memory.last_result
            self._draw_board(frame, result)
            self._draw_info(frame, result)
        self.fig.canvas.draw_idle()

    def _draw_board(self, frame, result, title=None):
        ax = self.ax
        ax.clear()
        for coordinate in (1, 2):
            ax.axhline(coordinate, color="black", linewidth=0.5)
            ax.axvline(coordinate, color="black", linewidth=0.5)
        ax.set_xlim(-0.35, 3.35)
        ax.set_ylim(3.35, -0.35)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_aspect("equal")
        if title is None and result:
            title = f"Cycle {result.cycle}  |  showing: {result.step}"
        elif title is None:
            title = "Fresh qubits, encoded |0_L>"
        ax.set_title(title, fontsize=13, fontweight="bold")

        outcomes = result.outcomes if result else {}
        for basis, positions, supports in (
            ("Z", Z_POSITIONS, Z_CHECK_SUPPORTS),
            ("X", X_POSITIONS, X_CHECK_SUPPORTS),
        ):
            states = frame[f"S{basis.lower()}"]
            color = CHECK_COLORS[basis]
            for index, (position, state) in enumerate(zip(positions, states)):
                for data_index in supports[index]:
                    data_position = DATA_POSITIONS[data_index]
                    ax.plot(
                        [position[0], data_position[0]],
                        [position[1], data_position[1]],
                        color=color,
                        linewidth=2.2 if state != "off" else 0.8,
                        alpha=0.8 if state != "off" else 0.35,
                        zorder=1,
                    )
                fill = {"off": OFF, "on": color, "flagged": FLAGGED}[state]
                ax.add_patch(Circle(position, 0.17, facecolor=fill, edgecolor=color, linewidth=2, zorder=2))
                label = f"{basis}{index}"
                if basis in outcomes:
                    label += "\n" + ("+1" if outcomes[basis][index] == 0 else "-1")
                ax.text(*position, label, ha="center", va="center", fontsize=7, fontweight="bold",
                        color="black" if state == "off" else "white", zorder=3)

        corrected = result.correction if result else {}
        for qubit, (center, state) in enumerate(zip(DATA_POSITIONS, frame["Data"])):
            ax.add_patch(Circle(center, 0.22, color=DATA_COLORS[state], zorder=2))
            if qubit in corrected:
                ax.add_patch(Circle(center, 0.28, facecolor="none", edgecolor="#2E9E4F",
                                    linewidth=3, zorder=2))
            label = data_label(qubit) + ("" if state == "on" else f"\n{state.upper()}")
            ax.text(*center, label, ha="center", va="center", color="white",
                    fontsize=9, fontweight="bold", zorder=3)

    def _info_axes(self):
        ax = self.info
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        return ax

    def _draw_light(self, ax, failed, detail):
        ax.plot([0.06], [0.93], "o", markersize=26, color="#D32F2F" if failed else "#2E7D32")
        ax.text(0.14, 0.93, "LOGICAL ERROR" if failed else "Logical qubit OK",
                va="center", fontsize=14, fontweight="bold")
        ax.text(0.14, 0.865, detail, va="center", fontsize=9, color="0.3")

    def _draw_footer(self, ax, top):
        led = self.led.status if self.led is not None else "off (--no-led)"
        ax.text(0.0, top, f"LED panel: {led}", fontsize=8, va="center",
                color="#2E7D32" if self.led is not None and self.led.connected else "0.3")
        legend = "Data: on / x / y / z      Checks: off / on (measuring) / flagged"
        ax.text(0.0, top - 0.05, legend, fontsize=8, va="center", color="0.3")
        ax.text(0.0, top - 0.1, "\n".join(self.log), fontsize=8.5, va="top", family="monospace")

    def _draw_replay_info(self, frame):
        ax = self._info_axes()
        self._draw_light(ax, frame["logical failure"], "as saved in the replayed frame")
        if self.replay_frames:
            where = f"{self.replay_folder.parent.name}/{self.replay_folder.name}/"
            position = f"frame {self.replay_index + 1} of {len(self.replay_frames)}"
        else:
            where, position = "no folder chosen", "-"
        ax.text(0.0, 0.77, "Replaying:", fontsize=10, fontweight="bold", va="center")
        ax.text(0.2, 0.77, where, fontsize=9, va="center")
        mode = "running" if self.playing else "paused"
        ax.text(0.0, 0.69, f"{position}   |   step {self.timer.interval} ms   |   {mode}",
                fontsize=10, va="center")
        ax.text(0.0, 0.62, "Shown here and sent to the LED panel; not saved again.",
                fontsize=8, va="center", color="0.3")
        self._draw_footer(ax, 0.54)

    def _draw_info(self, frame, result):
        ax = self._info_axes()
        failed = frame["logical failure"]
        detail = self.memory.logical_kind if failed else "residual error is correctable"
        self._draw_light(ax, failed, f"{detail}   <Z_L> = {self.memory.logical_z_expectation():+.0f}")

        ax.text(0.0, 0.79, "Next:", fontsize=10, fontweight="bold", va="center")
        for index, name in enumerate(STEPS):
            active = index == self.memory.step_index
            ax.text(0.14 + index * 0.29, 0.79, name, fontsize=9, va="center",
                    fontweight="bold" if active else "normal",
                    bbox=dict(boxstyle="round", facecolor=SELECTED if active else "white",
                              edgecolor="0.6"))

        mode = "running" if self.playing else "paused"
        ax.text(0.0, 0.71, f"Error type: {self.gate}   |   step {self.timer.interval} ms   |   {mode}",
                fontsize=10, va="center")

        saved = self.last_saved.name if self.last_saved else "-"
        folder = f"{self.writer.directory.parent.name}/{self.writer.directory.name}"
        ax.text(0.0, 0.645, f"LED frames: {folder}/", fontsize=8, va="center", color="0.3")
        ax.text(0.0, 0.605, f"last saved: {saved}  ({self.writer.count} total)", fontsize=8,
                va="center", color="0.3")

        self._draw_footer(ax, 0.54)


def _parse_fault(value):
    try:
        qubit, gate = value.split(":")
        qubit, gate = int(qubit), gate.upper()
    except ValueError as error:
        raise argparse.ArgumentTypeError("use QUBIT:GATE, e.g. 5:X for D5") from error
    if not 1 <= qubit <= 9 or gate not in PAULIS:
        raise argparse.ArgumentTypeError("qubit 1-9 (D1..D9), gate X, Y or Z")
    return qubit - 1, gate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Live surface-code memory with LED frames.")
    parser.add_argument("--interval", type=int, default=500, help="ms per step while playing")
    parser.add_argument("--seed", type=int, default=None, help="Aer seed")
    parser.add_argument("--out", default="data_to_pico", help="folder for the LED frames")
    parser.add_argument("--no-led", action="store_true", help="don't connect to the LED panel")
    parser.add_argument("--replay", metavar="FOLDER", help="start in Replay mode with this run folder")
    parser.add_argument("--fault", type=_parse_fault, action="append", default=[],
                        metavar="QUBIT:GATE", help="error to inject at start (repeatable)")
    args = parser.parse_args(argv)
    led = None if args.no_led else PicoLink()
    app = LiveVisualizer(args.interval, args.seed, args.out, args.fault, led=led, replay=args.replay)
    plt.show()
    return app


if __name__ == "__main__":
    main()
