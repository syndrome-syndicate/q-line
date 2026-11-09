"""
Live surface-code memory with LED-panel frames.

    python Live_visualizer.py            # optional: --interval 500 --seed 1 --fault 5:X

Buttons:
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

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Button, TextBox

from Data_Log.Pico_Frames import PicoFrameWriter, make_frame
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


class LiveVisualizer:
    def __init__(self, interval_ms=500, seed=None, out_root="data_to_pico", faults=(), led=None):
        self.memory = SurfaceCodeMemory(seed=seed)
        self.writer = PicoFrameWriter(out_root)
        self.led = led  # PicoLink: every saved frame is also sent to the LED panel
        self.gate = "X"
        self.playing = False
        self.log = deque(maxlen=9)
        self.last_saved = None

        self.fig = plt.figure(figsize=(12, 8))
        self.fig.canvas.manager.set_window_title("Surface code memory -> LED panel")
        self.ax = self.fig.add_axes([0.03, 0.27, 0.52, 0.66])
        self.info = self.fig.add_axes([0.58, 0.27, 0.40, 0.66])

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
        self._save(reset=True)  # LED panel starts from pristine qubits
        self.select_gate("X")

    # ---------------------------------------------------------------- frames
    def current_frame(self, reset=False):
        return make_frame(
            self.memory.errors,
            self.memory.last_result,
            logical_failure=self.memory.logical_failed,
            reset=reset,
        )

    def _save(self, reset=False):
        frame = self.current_frame(reset=reset)
        self.last_saved = self.writer.write(frame)
        if self.led is not None:
            self.led.send(frame)

    def close(self):
        if self.led is not None:
            self.led.close()

    # --------------------------------------------------------------- actions
    def select_gate(self, gate):
        self.gate = gate
        for name, button in self.gate_buttons.items():
            button.ax.set_facecolor(SELECTED if name == gate else IDLE_BUTTON)
        self.render()

    def inject(self, qubit):
        self._log(self.memory.inject(qubit, self.gate))
        self.render()

    def next_step(self, _event=None):
        if self.playing:
            self.toggle_play()
        self._step()

    def _step(self):
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
        self.playing = not self.playing
        self.play_button.label.set_text("Pause" if self.playing else "Play")
        if self.playing:
            self.timer.start()
        else:
            self.timer.stop()
        self.render()

    def reset(self, _event=None):
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
        elif key.upper() in PAULIS:
            self.select_gate(key.upper())
        elif key.isdigit() and 1 <= int(key) <= 9:
            self.inject(int(key) - 1)

    def _log(self, message):
        self.log.append(message)

    # ---------------------------------------------------------------- render
    def render(self):
        frame = self.current_frame()
        result = self.memory.last_result
        self._draw_board(frame, result)
        self._draw_info(frame, result)
        self.fig.canvas.draw_idle()

    def _draw_board(self, frame, result):
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
        if result:
            title = f"Cycle {result.cycle}  |  showing: {result.step}"
        else:
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

    def _draw_info(self, frame, result):
        ax = self.info
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        failed = frame["logical failure"]
        ax.plot([0.06], [0.93], "o", markersize=26, color="#D32F2F" if failed else "#2E7D32")
        ax.text(0.14, 0.93, "LOGICAL ERROR" if failed else "Logical qubit OK",
                va="center", fontsize=14, fontweight="bold")
        detail = self.memory.logical_kind if failed else "residual error is correctable"
        ax.text(0.14, 0.875, f"{detail}   <Z_L> = {self.memory.logical_z_expectation():+.0f}",
                va="center", fontsize=9, color="0.3")

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

        led = self.led.status if self.led is not None else "off (--no-led)"
        ax.text(0.0, 0.555, f"LED panel: {led}", fontsize=8, va="center",
                color="#2E7D32" if self.led is not None and self.led.connected else "0.3")
        legend = "Data: on / x / y / z      Checks: off / on (measuring) / flagged"
        ax.text(0.0, 0.515, legend, fontsize=8, va="center", color="0.3")
        ax.text(0.0, 0.475, "\n".join(self.log), fontsize=8.5, va="top", family="monospace", wrap=True)


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
    parser.add_argument("--fault", type=_parse_fault, action="append", default=[],
                        metavar="QUBIT:GATE", help="error to inject at start (repeatable)")
    args = parser.parse_args(argv)
    led = None if args.no_led else PicoLink()
    app = LiveVisualizer(args.interval, args.seed, args.out, args.fault, led=led)
    plt.show()
    return app


if __name__ == "__main__":
    main()
