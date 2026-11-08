"""
Interactive Surface-17 quantum-memory visualizer.

Run:
    python surface17/visualizer.py            (optional: --interval 1.0 --seed 1)

Controls
    Play / Pause      auto-run the QEC cycle            (key: space)
    Next step        run exactly one step               (key: n)
    Reset            re-encode a fresh |0_L>            (key: r)
    Error type       X / Z / Y for injection            (keys: x, z, y)
    Click a data qubit to inject the selected error on it right now.

Each cycle is three separate steps:  Z checks -> X checks -> Decode + correct.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import matplotlib

for _key in ("keymap.home", "keymap.back", "keymap.forward", "keymap.pan", "keymap.zoom",
             "keymap.yscale", "keymap.xscale", "keymap.grid", "keymap.grid_minor", "keymap.save",
             "keymap.fullscreen", "keymap.quit"):
    if _key in matplotlib.rcParams:
        matplotlib.rcParams[_key] = []

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Wedge  # noqa: E402
from matplotlib.widgets import Button, RadioButtons  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import STEPS, StepResult, Surface17Memory  # noqa: E402

# ---------------------------------------------------------------- palette
Z_COLOR, Z_TINT = "#F5A300", "#FFE9B8"   # amber  = Z-type checks
X_COLOR, X_TINT = "#1E9FD8", "#CDEEFC"   # cyan   = X-type checks
DET_COLOR = "#E53935"                    # detection event / error
FIX_COLOR = "#2E9E4F"                    # decoder correction
DATA_FILL = "#FFFFFF"
INK = "#263238"
MUTED = "#90A4AE"
BG = "#F7F9FA"


class Surface17Visualizer:
    def __init__(self, interval: float = 1.2, seed: int | None = None):
        self.mem = Surface17Memory(seed=seed)
        self.interval_ms = int(interval * 1000)
        self.playing = False
        self.error_type = "X"
        self._init_ui_state()

        self.fig = plt.figure(figsize=(13.5, 8.2), facecolor=BG)
        self.fig.canvas.manager.set_window_title("Surface-17 QEC memory")
        self.ax_board = self.fig.add_axes([0.02, 0.14, 0.55, 0.74])
        self.ax_phase = self.fig.add_axes([0.04, 0.89, 0.51, 0.08])
        self.ax_status = self.fig.add_axes([0.60, 0.70, 0.38, 0.27])
        self.ax_hist = self.fig.add_axes([0.63, 0.36, 0.33, 0.30])
        self.ax_log = self.fig.add_axes([0.60, 0.02, 0.38, 0.29])

        self._build_controls()
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self.timer = self.fig.canvas.new_timer(interval=self.interval_ms)
        self.timer.add_callback(self._tick)
        self.timer.start()

        self._log(self.mem.init_message)
        self._log("Ready. Press Play, or Next step to advance one step at a time.")
        self.redraw()

    # ----------------------------------------------------------- UI state
    def _init_ui_state(self):
        self.z_out = [None] * self.mem.n_z     # last raw outcome per check
        self.x_out = [None] * self.mem.n_x
        self.z_det = [0] * self.mem.n_z        # detection events per check
        self.x_det = [0] * self.mem.n_x
        self.last: StepResult | None = None
        self.rows: list[list[float]] = []      # spacetime detection history
        self.messages: list[str] = []

    # ----------------------------------------------------------- controls
    def _build_controls(self):
        def button(rect, label, cb, color="#ECEFF1"):
            b = Button(self.fig.add_axes(rect), label, color=color, hovercolor="#CFD8DC")
            b.label.set_fontsize(11)
            b.on_clicked(cb)
            return b

        self.btn_play = button([0.04, 0.03, 0.12, 0.065], "Play", self._toggle_play, "#C8E6C9")
        self.btn_step = button([0.17, 0.03, 0.12, 0.065], "Next step", self._step_clicked)
        self.btn_reset = button([0.30, 0.03, 0.09, 0.065], "Reset", self._reset_clicked)

        ax_radio = self.fig.add_axes([0.41, 0.015, 0.15, 0.10], facecolor=BG)
        ax_radio.set_title("Error to inject (click a data qubit)", fontsize=8.5, color=INK, pad=2)
        self.radio = RadioButtons(ax_radio, ("X  (bit flip)", "Z  (phase flip)", "Y  (both)"))
        for lbl in self.radio.labels:
            lbl.set_fontsize(9.5)
        self.radio.on_clicked(lambda label: setattr(self, "error_type", label[0]))

    def _toggle_play(self, _event=None):
        self.playing = not self.playing
        self.btn_play.label.set_text("Pause" if self.playing else "Play")
        self.btn_play.color = "#FFCDD2" if self.playing else "#C8E6C9"
        self._log("Playing." if self.playing else "Paused - click data qubits to inject errors.")
        self.redraw()

    def _step_clicked(self, _event=None):
        if self.playing:
            self._toggle_play()
        self.do_step()

    def _reset_clicked(self, _event=None):
        self.mem.reset()
        self._init_ui_state()
        self._log(self.mem.init_message)
        self.redraw()

    def _tick(self):
        if self.playing:
            self.do_step()

    def _on_key(self, event):
        if event.key == " ":
            self._toggle_play()
        elif event.key in ("n", "right"):
            self._step_clicked()
        elif event.key == "r":
            self._reset_clicked()
        elif event.key in ("x", "z", "y"):
            idx = "xzy".index(event.key)
            self.radio.set_active(idx)

    def _on_click(self, event):
        if event.inaxes is not self.ax_board or event.xdata is None:
            return
        for q in range(self.mem.n_data):
            x, y = self._data_pos(q)
            if math.hypot(event.xdata - x, event.ydata - y) < 0.2:
                msg = self.mem.inject(q, self.error_type)
                self._log(msg + ("" if not self.playing else "  (cycle still running)"))
                self.redraw()
                return

    # --------------------------------------------------------- simulation
    def do_step(self):
        res = self.mem.step()
        self.last = res
        if res.step == "Z checks":
            self.z_out, self.z_det = res.z_outcomes, res.z_detections
            self.rows.append(list(map(float, res.z_detections)) + [np.nan] * self.mem.n_x)
        elif res.step == "X checks":
            self.x_out, self.x_det = res.x_outcomes, res.x_detections
            if not self.rows:
                self.rows.append([np.nan] * (self.mem.n_z + self.mem.n_x))
            self.rows[-1][self.mem.n_z:] = list(map(float, res.x_detections))
        else:
            # Correction applied: show the check values now expected.
            self.z_det = [0] * self.mem.n_z
            self.x_det = [0] * self.mem.n_x
            self.z_out = list(self.mem.ref_z)
            self.x_out = list(self.mem.ref_x)
        self._log(f"[cycle {res.cycle}] {res.message}")
        self.redraw()

    def _log(self, msg: str):
        self.messages.append(msg)
        self.messages = self.messages[-11:]

    # ----------------------------------------------------------- geometry
    def _data_pos(self, q):
        return q % self.mem.d, q // self.mem.d

    def _plaq_geometry(self, coord, plaq):
        """Return (kind, shape_args, ancilla_xy) for a plaquette."""
        x, y = coord
        qubits = [q for q in plaq if q is not None]
        if len(qubits) == 4:
            corners = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
            return "square", corners, (x + 0.5, y + 0.5)
        (x1, y1), (x2, y2) = (self._data_pos(q) for q in qubits)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        # outward normal of the boundary edge the plaquette sits on
        if y1 == y2:
            ox, oy = 0.0, (1.0 if my > 1 else -1.0)
        else:
            ox, oy = (1.0 if mx > 1 else -1.0), 0.0
        theta = math.degrees(math.atan2(oy, ox))
        return "half", ((mx, my), theta), (mx + 0.27 * ox, my + 0.27 * oy)

    def _anc_pos(self, basis, i):
        coords = self.mem.zplaq_coords if basis == "Z" else self.mem.xplaq_coords
        plaqs = self.mem.zplaqs if basis == "Z" else self.mem.xplaqs
        return self._plaq_geometry(coords[i], plaqs[i])[2]

    # ------------------------------------------------------------ drawing
    def redraw(self):
        self._draw_board()
        self._draw_phase()
        self._draw_status()
        self._draw_history()
        self._draw_log()
        self.fig.canvas.draw_idle()

    def _draw_board(self):
        ax = self.ax_board
        ax.clear()
        ax.set_facecolor(BG)
        ax.set_xlim(-0.85, 2.85)
        ax.set_ylim(2.85, -0.85)  # row 0 on top
        ax.set_aspect("equal")
        ax.axis("off")

        step = self.last.step if self.last else None
        active = {"Z checks": "Z", "X checks": "X"}.get(step)

        # plaquettes
        for basis, coords, plaqs, dets, color, tint in (
            ("Z", self.mem.zplaq_coords, self.mem.zplaqs, self.z_det, Z_COLOR, Z_TINT),
            ("X", self.mem.xplaq_coords, self.mem.xplaqs, self.x_det, X_COLOR, X_TINT),
        ):
            for i, (coord, plaq) in enumerate(zip(coords, plaqs)):
                kind, args, _ = self._plaq_geometry(coord, plaq)
                lit = active == basis
                face = color if lit else tint
                alpha = 0.55 if lit else 0.9
                edge = DET_COLOR if dets[i] else color
                lw = 3.2 if dets[i] else 1.2
                if kind == "square":
                    patch = Polygon(args, closed=True)
                else:
                    (cx, cy), theta = args
                    patch = Wedge((cx, cy), 0.5, theta - 90, theta + 90)
                patch.set(facecolor=face, alpha=alpha, edgecolor=edge, linewidth=lw, zorder=1)
                ax.add_patch(patch)

        # CX interaction lines for the checks just measured
        if active:
            plaqs = self.mem.zplaqs if active == "Z" else self.mem.xplaqs
            color = Z_COLOR if active == "Z" else X_COLOR
            for i, plaq in enumerate(plaqs):
                ax_, ay_ = self._anc_pos(active, i)
                for order, q in enumerate(plaq):
                    if q is None:
                        continue
                    dx, dy = self._data_pos(q)
                    ax.plot([ax_, dx], [ay_, dy], color=color, lw=2.2, zorder=2,
                            solid_capstyle="round")
                    ax.text(ax_ + 0.55 * (dx - ax_), ay_ + 0.55 * (dy - ay_), str(order + 1),
                            fontsize=7, color=INK, ha="center", va="center", zorder=3,
                            bbox=dict(boxstyle="circle,pad=0.12", fc="white", ec=color, lw=0.8))

        # MWPM matching lines after decoding
        if step == "Decode + correct":
            for basis, matches in (("Z", self.last.z_matches), ("X", self.last.x_matches)):
                for a, b in matches:
                    pa = self._anc_pos(basis, a)
                    if b == -1:
                        ox, oy = pa[0] - 1, pa[1] - 1
                        n = math.hypot(ox, oy) or 1
                        pb = (pa[0] + 0.55 * ox / n, pa[1] + 0.55 * oy / n)
                    else:
                        pb = self._anc_pos(basis, b)
                    ax.plot([pa[0], pb[0]], [pa[1], pb[1]], ls="--", lw=2.5, color=FIX_COLOR,
                            zorder=4)

        # ancillas
        for basis, outs, dets, color in (("Z", self.z_out, self.z_det, Z_COLOR),
                                         ("X", self.x_out, self.x_det, X_COLOR)):
            for i in range(len(outs)):
                x, y = self._anc_pos(basis, i)
                if dets[i]:
                    face, txt, tc = DET_COLOR, "-1", "white"
                elif outs[i] is None:
                    face, txt, tc = "white", "", INK
                else:
                    face, txt, tc = color, "+1" if outs[i] == 0 else "-1", "white"
                ring = INK if active == basis else color
                ax.add_patch(Circle((x, y), 0.11, facecolor=face, edgecolor=ring,
                                    lw=2.4 if active == basis else 1.4, zorder=5))
                ax.text(x, y, txt, ha="center", va="center", fontsize=7.5, color=tc,
                        fontweight="bold", zorder=6)
                ax.text(x, y + 0.17, f"{basis}{i}", ha="center", va="center", fontsize=7.5,
                        color=INK, zorder=6)

        # data qubits
        corrected = self.last.correction if step == "Decode + correct" else {}
        for q in range(self.mem.n_data):
            x, y = self._data_pos(q)
            err = self.mem.frame.get(q)
            face = DET_COLOR if err else DATA_FILL
            ax.add_patch(Circle((x, y), 0.17, facecolor=face, edgecolor=INK, lw=1.8, zorder=7))
            ax.text(x, y, err or f"D{q}", ha="center", va="center", zorder=8,
                    fontsize=12 if err else 9, fontweight="bold",
                    color="white" if err else INK)
            if q in corrected:
                ax.add_patch(Circle((x, y), 0.23, facecolor="none", edgecolor=FIX_COLOR, lw=3,
                                    zorder=7))
                ax.text(x + 0.2, y - 0.22, f"+{corrected[q]}", color=FIX_COLOR, fontsize=11,
                        fontweight="bold", zorder=8)

        ax.text(-0.8, 2.8, "amber = Z checks (catch X errors)   cyan = X checks (catch Z errors)"
                "   red = error / detection   green = MWPM correction",
                fontsize=8.5, color=INK, va="bottom")

    def _draw_phase(self):
        ax = self.ax_phase
        ax.clear()
        ax.set_xlim(0, 3)
        ax.set_ylim(0, 1)
        ax.axis("off")
        done = STEPS.index(self.last.step) if self.last else -1
        nxt = self.mem.step_index
        colors = (Z_COLOR, X_COLOR, FIX_COLOR)
        for i, name in enumerate(STEPS):
            is_done = i == done
            is_next = i == nxt
            ax.add_patch(FancyBboxPatch((i + 0.04, 0.12), 0.92, 0.76,
                                        boxstyle="round,pad=0.0,rounding_size=0.12",
                                        fc=colors[i] if is_done else "white",
                                        ec=colors[i], lw=3 if is_next else 1.5))
            label = f"{i + 1}. {name}" + ("   <- next" if is_next else "")
            ax.text(i + 0.5, 0.5, label, ha="center", va="center", fontsize=11,
                    color="white" if is_done else INK, fontweight="bold" if is_done else None)

    def _draw_status(self):
        ax = self.ax_status
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        bad = self.mem.logical_failed
        color = DET_COLOR if bad else FIX_COLOR
        ax.plot([0.12], [0.62], "o", ms=52, mfc=color, mec=INK, mew=1.5)
        ax.text(0.29, 0.70, "LOGICAL ERROR" if bad else "LOGICAL OK", fontsize=19,
                fontweight="bold", color=color, va="center")
        sub = self.mem.logical_kind if bad else r"memory holds $|\bar{0}\rangle$"
        ax.text(0.29, 0.52, sub, fontsize=10.5, color=INK, va="center")
        ez = self.mem.logical_z_expectation()
        mode = "PLAYING" if self.playing else "PAUSED"
        ax.text(0.02, 0.24,
                f"Cycle {self.mem.cycle}    next: {self.mem.next_step}    [{mode}]\n"
                rf"Simulator $\langle\bar{{Z}}\rangle$ = {ez:+.0f}    "
                f"tracked error: {self._frame_str()}",
                fontsize=10, color=INK, va="center", linespacing=1.7)

    def _frame_str(self):
        if not self.mem.frame:
            return "none"
        return " ".join(f"{p}{q}" for q, p in sorted(self.mem.frame.items()))

    def _draw_history(self):
        ax = self.ax_hist
        ax.clear()
        n = self.mem.n_z + self.mem.n_x
        rows = self.rows[-10:]
        first = len(self.rows) - len(rows) + 1
        grid = np.full((10, n), np.nan)
        if rows:
            grid[: len(rows)] = np.array(rows)
        cmap = matplotlib.colors.ListedColormap(["#FFFFFF", DET_COLOR])
        cmap.set_bad("#ECEFF1")
        ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(n))
        labels = [f"Z{i}" for i in range(self.mem.n_z)] + [f"X{i}" for i in range(self.mem.n_x)]
        ax.set_xticklabels(labels, fontsize=8)
        for t, lbl in zip(ax.get_xticklabels(), labels):
            t.set_color(Z_COLOR if lbl[0] == "Z" else X_COLOR)
            t.set_fontweight("bold")
        ax.set_yticks(range(10))
        ax.set_yticklabels([str(first + i) if i < len(rows) else "" for i in range(10)],
                           fontsize=8)
        ax.set_ylabel("cycle", fontsize=9)
        ax.set_xticks(np.arange(-0.5, n), minor=True)
        ax.set_yticks(np.arange(-0.5, 10), minor=True)
        ax.grid(which="minor", color="#B0BEC5", lw=0.6)
        ax.tick_params(which="minor", length=0)
        ax.axvline(self.mem.n_z - 0.5, color=INK, lw=1.5)
        ax.set_title("Detection events per cycle (red = check flipped)", fontsize=10, color=INK)

    def _draw_log(self):
        ax = self.ax_log
        ax.clear()
        ax.set_facecolor("white")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#CFD8DC")
        text = "\n".join(self.messages)
        ax.text(0.015, 0.97, text, va="top", ha="left", fontsize=8.2, family="monospace",
                color=INK, transform=ax.transAxes, wrap=True)


def main():
    parser = argparse.ArgumentParser(description="Surface-17 QEC memory visualizer")
    parser.add_argument("--interval", type=float, default=1.2,
                        help="seconds between steps while playing (default 1.2)")
    parser.add_argument("--seed", type=int, default=None, help="Aer simulator seed")
    args = parser.parse_args()
    viz = Surface17Visualizer(interval=args.interval, seed=args.seed)  # noqa: F841
    plt.show()


if __name__ == "__main__":
    main()
