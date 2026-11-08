"""
Interactive 3-patch Surface-17 visualizer with a lattice-surgery CNOT.

Run:
    python surface17/lattice_surgery.py      (optional: --interval 1.0 --merge-rounds 1 --seed 1)

Three d=3 patches (C = control, A = ancilla, T = target) idle as quantum
memories, each running Z checks -> X checks -> Decode + correct. Press CNOT
and, at the next cycle boundary, the program becomes:

    Merge C+A (ZZ) -> checks/decode -> Split C|A -> Merge A+T (XX) -> checks/decode
    -> Split A|T -> Measure A + Pauli-frame fix -> Re-prepare A |+>

Controls
    Play / Pause (space), Next step (n), Reset (r), CNOT (c)
    Error type X / Z / Y (x, z, y); click any active data qubit to inject.
    Input states for C and T (changing them resets the memory).
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import matplotlib

for _key in ("keymap.home", "keymap.back", "keymap.forward", "keymap.pan", "keymap.zoom",
             "keymap.yscale", "keymap.xscale", "keymap.grid", "keymap.grid_minor", "keymap.save",
             "keymap.fullscreen", "keymap.quit", "keymap.copy"):
    if _key in matplotlib.rcParams:
        matplotlib.rcParams[_key] = []

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Wedge  # noqa: E402
from matplotlib.widgets import Button, RadioButtons  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multipatch import (CYCLE, INPUT_STATES, PATCH_ORIGIN, LatticeSurgeryMemory,  # noqa: E402
                        StepResult)

Z_COLOR, Z_TINT = "#F5A300", "#FFE9B8"
X_COLOR, X_TINT = "#1E9FD8", "#CDEEFC"
DET_COLOR = "#E53935"
FIX_COLOR = "#2E9E4F"
SURGERY = "#7E57C2"
INK = "#263238"
MUTED = "#B0BEC5"
BG = "#F7F9FA"
PATCH_NAMES = {"C": "control", "A": "ancilla", "T": "target"}


class LatticeSurgeryVisualizer:
    def __init__(self, interval=1.0, merge_rounds=1, seed=None):
        self.inputs = ["|+>", "|0>"]
        self.mem = LatticeSurgeryMemory(inputs=tuple(self.inputs), merge_rounds=merge_rounds,
                                        seed=seed)
        self.playing = False
        self.error_type = "X"
        self.last: StepResult | None = None
        self.messages: list[str] = []

        self.fig = plt.figure(figsize=(15, 9), facecolor=BG)
        self.fig.canvas.manager.set_window_title("Surface-17 lattice surgery")
        self.ax_board = self.fig.add_axes([0.01, 0.12, 0.56, 0.86])
        self.ax_queue = self.fig.add_axes([0.58, 0.58, 0.17, 0.36])
        self.ax_status = self.fig.add_axes([0.77, 0.74, 0.22, 0.24])
        self.ax_table = self.fig.add_axes([0.77, 0.45, 0.22, 0.28])
        self.ax_log = self.fig.add_axes([0.58, 0.02, 0.41, 0.40])
        self._build_controls()
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.timer = self.fig.canvas.new_timer(interval=int(interval * 1000))
        self.timer.add_callback(self._tick)
        self.timer.start()

        self._log(self.mem.init_message)
        self._log("Press Play or Next step. Press CNOT to run lattice surgery.")
        self.redraw()

    # ------------------------------------------------------------ controls
    def _build_controls(self):
        def button(rect, label, cb, color="#ECEFF1"):
            b = Button(self.fig.add_axes(rect), label, color=color, hovercolor="#CFD8DC")
            b.label.set_fontsize(11)
            b.on_clicked(cb)
            return b

        self.btn_play = button([0.02, 0.03, 0.08, 0.06], "Play", self._toggle_play, "#C8E6C9")
        self.btn_step = button([0.11, 0.03, 0.08, 0.06], "Next step", self._step_clicked)
        self.btn_cnot = button([0.20, 0.03, 0.08, 0.06], "CNOT", self._cnot_clicked, "#D1C4E9")
        self.btn_reset = button([0.29, 0.03, 0.06, 0.06], "Reset", self._reset_clicked)

        def radio(rect, title, labels, active, cb):
            ax = self.fig.add_axes(rect, facecolor=BG)
            ax.set_title(title, fontsize=8.5, color=INK, pad=2)
            r = RadioButtons(ax, labels, active=active)
            for lbl in r.labels:
                lbl.set_fontsize(9)
            r.on_clicked(cb)
            return r

        self.radio_err = radio([0.36, 0.005, 0.07, 0.095], "Error (click qubit)",
                               ("X", "Z", "Y"), 0,
                               lambda lab: setattr(self, "error_type", lab))
        self.radio_c = radio([0.44, 0.005, 0.06, 0.095], "Input C", INPUT_STATES,
                             INPUT_STATES.index(self.inputs[0]), lambda lab: self._set_input(0, lab))
        self.radio_t = radio([0.51, 0.005, 0.06, 0.095], "Input T", INPUT_STATES,
                             INPUT_STATES.index(self.inputs[1]), lambda lab: self._set_input(1, lab))

    def _set_input(self, i, label):
        self.inputs[i] = label
        self._reset_clicked()

    def _toggle_play(self, _event=None):
        self.playing = not self.playing
        self.btn_play.label.set_text("Pause" if self.playing else "Play")
        self.btn_play.color = "#FFCDD2" if self.playing else "#C8E6C9"
        self._log("Playing." if self.playing else "Paused: click data qubits to inject errors.")
        self.redraw()

    def _step_clicked(self, _event=None):
        if self.playing:
            self._toggle_play()
        self.do_step()

    def _cnot_clicked(self, _event=None):
        if self.mem.in_surgery or self.mem.cnot_pending or any(
                s.startswith("Merge") for s in self.mem.queue):
            self._log("A CNOT is already scheduled or running.")
        else:
            self.mem.request_cnot()
            self._log("CNOT requested: lattice surgery starts after the current cycle.")
        self.redraw()

    def _reset_clicked(self, _event=None):
        self.mem.reset(tuple(self.inputs))
        self.last = None
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
        elif event.key == "c":
            self._cnot_clicked()
        elif event.key in ("x", "z", "y"):
            self.radio_err.set_active("xzy".index(event.key))

    def _on_click(self, event):
        if event.inaxes is not self.ax_board or event.xdata is None:
            return
        for q, (x, y) in enumerate(self.mem.coords):
            if math.hypot(event.xdata - x, event.ydata - y) < 0.2:
                self._log(self.mem.inject(q, self.error_type))
                self.redraw()
                return

    def do_step(self):
        self.last = self.mem.step()
        tag = "[CNOT]" if self.mem.in_surgery or self.last.step in (
            "Measure A + frame fix", "Re-prepare A |+>") else f"[cycle {self.mem.cycle}]"
        self._log(f"{tag} {self.last.message}")
        self.redraw()

    def _log(self, msg):
        self.messages.append(msg)
        self.messages = self.messages[-14:]

    # -------------------------------------------------------------- drawing
    def redraw(self):
        self._draw_board()
        self._draw_queue()
        self._draw_status()
        self._draw_table()
        self._draw_log()
        self.fig.canvas.draw_idle()

    def _plaq_shape(self, c):
        pts = [self.mem.coords[q] for q in c.qubits]
        cx, cy = c.coord[0] + 0.5, c.coord[1] + 0.5
        if len(pts) == 4:
            (x, y) = c.coord
            return Polygon([(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)], closed=True)
        mx, my = (pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2
        theta = math.degrees(math.atan2(cy - my, cx - mx))
        return Wedge((mx, my), 0.5, theta - 90, theta + 90)

    def _draw_board(self):
        ax = self.ax_board
        ax.clear()
        ax.set_facecolor(BG)
        ax.set_xlim(-0.9, 6.9)
        ax.set_ylim(6.95, -0.95)
        ax.set_aspect("equal")
        ax.axis("off")
        mem = self.mem
        step = self.last.step if self.last else None
        active_kind = self.last.kind if self.last else None

        # patch labels
        for p, (ox, oy) in PATCH_ORIGIN.items():
            ax.text(ox - 0.85, oy - 0.55, f"{p}: {PATCH_NAMES[p]}", fontsize=10.5, color=INK,
                    fontweight="bold", va="center")
        ax.text(4.0, 0.2, "C = control      A = ancilla (|+>)      T = target\n\n"
                f"inputs:  C = {self.inputs[0]}    T = {self.inputs[1]}\n\n"
                "amber: Z checks (catch X errors)\ncyan:  X checks (catch Z errors)\n"
                "red: error / flipped check\ngreen: MWPM correction",
                fontsize=9.5, color=INK, va="top", linespacing=1.3)

        # merged region highlight
        if mem.config in ("ZZ", "XX"):
            (x0, y0, w, h, lbl) = ((-0.45, -0.45, 2.9, 6.9, "ZZ merge: C+A") if mem.config == "ZZ"
                                   else (-0.45, 3.55, 6.9, 2.9, "XX merge: A+T"))
            ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0.05,rounding_size=0.3",
                                        fc="none", ec=SURGERY, lw=3, ls="--", zorder=0.5))
            what = ("new seam Z checks multiply to Z_C Z_A" if mem.config == "ZZ"
                    else "new seam X checks multiply to X_A X_T")
            ax.text(4.0, 2.75, f"{lbl}\n{what}", color=SURGERY, fontsize=11, fontweight="bold",
                    va="center", linespacing=1.5)

        # plaquettes
        for c in mem.checks:
            color, tint = (Z_COLOR, Z_TINT) if c.kind == "Z" else (X_COLOR, X_TINT)
            det = mem.last_det.get(c.key, 0)
            lit = active_kind == c.kind
            patch = self._plaq_shape(c)
            patch.set(facecolor=color if lit else tint, alpha=0.5 if lit else 0.85,
                      edgecolor=DET_COLOR if det else color, linewidth=3 if det else 1.0, zorder=1)
            ax.add_patch(patch)
            if lit:
                ax_, ay_ = c.coord[0] + 0.5, c.coord[1] + 0.5
                for q in c.qubits:
                    dx, dy = mem.coords[q]
                    ax.plot([ax_, dx], [ay_, dy], color=color, lw=1.6, zorder=2)

        # matching lines
        if step == "Decode + correct":
            for kind, a, b in self.last.matches:
                pa = (a.coord[0] + 0.5, a.coord[1] + 0.5)
                if b is None:
                    pb = self._boundary_point(a)
                else:
                    pb = (b.coord[0] + 0.5, b.coord[1] + 0.5)
                ax.plot([pa[0], pb[0]], [pa[1], pb[1]], ls="--", lw=2.5, color=FIX_COLOR, zorder=4)

        # ancillas
        for c in mem.checks:
            x, y = c.coord[0] + 0.5, c.coord[1] + 0.5
            color = Z_COLOR if c.kind == "Z" else X_COLOR
            out = mem.last_out.get(c.key)
            det = mem.last_det.get(c.key, 0)
            face = DET_COLOR if det else ("white" if out is None else color)
            txt = "" if out is None else ("+1" if out == 0 else "-1")
            ring = INK if active_kind == c.kind else color
            ax.add_patch(Circle((x, y), 0.13, fc=face, ec=ring,
                                lw=2.0 if active_kind == c.kind else 1.0, zorder=5))
            ax.text(x, y, txt, ha="center", va="center", fontsize=6.5, zorder=6, fontweight="bold",
                    color="white" if out is not None or det else INK)

        # data qubits
        active = set(mem.active_data)
        corrected = self.last.correction if step == "Decode + correct" else {}
        for q, (x, y) in enumerate(mem.coords):
            err = mem.frame.get(q)
            if q not in active:
                ax.add_patch(Circle((x, y), 0.1, fc=BG, ec=MUTED, lw=1, ls="--", zorder=7))
                continue
            ax.add_patch(Circle((x, y), 0.17, fc=DET_COLOR if err else "white", ec=INK, lw=1.6,
                                zorder=7))
            label = err or mem.label(q).replace("seam", "s")
            ax.text(x, y, label, ha="center", va="center", zorder=8,
                    fontsize=11 if err else 6.5, fontweight="bold",
                    color="white" if err else INK)
            if q in corrected:
                ax.add_patch(Circle((x, y), 0.23, fc="none", ec=FIX_COLOR, lw=3, zorder=7))
                ax.text(x + 0.2, y - 0.22, f"+{corrected[q]}", color=FIX_COLOR, fontsize=10,
                        fontweight="bold", zorder=8)

    def _boundary_point(self, c):
        pts = [self.mem.coords[q] for q in c.qubits]
        cx, cy = c.coord[0] + 0.5, c.coord[1] + 0.5
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        if len(pts) == 2:
            return (cx + (cx - mx), cy + (cy - my))
        # bulk check matched to the boundary: point toward the nearest data qubit pair edge
        return (cx, cy)

    def _draw_queue(self):
        ax = self.ax_queue
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("Program", fontsize=11, color=INK, loc="left")
        items = []
        if self.last:
            items.append(("done", self.last.step))
        items += [("next" if i == 0 else "todo", s) for i, s in enumerate(self.mem.upcoming(8))]
        n = len(items)
        h = 1 / max(n, 9)
        for i, (state, name) in enumerate(items):
            y = 1 - (i + 1) * h
            surgery = name not in CYCLE
            color = SURGERY if surgery else {"Z checks": Z_COLOR, "X checks": X_COLOR}.get(name, FIX_COLOR)
            fc = color if state == "done" else "white"
            ax.add_patch(FancyBboxPatch((0.02, y + 0.1 * h), 0.96, 0.8 * h,
                                        boxstyle="round,pad=0,rounding_size=0.02", fc=fc, ec=color,
                                        lw=2.5 if state == "next" else 1, alpha=0.9))
            prefix = {"done": "done  ", "next": "next >", "todo": "      "}[state]
            ax.text(0.05, y + 0.5 * h, f"{prefix} {name}", va="center", fontsize=9,
                    family="monospace", color="white" if state == "done" else INK,
                    fontweight="bold" if state != "todo" else None)

    def _draw_status(self):
        ax = self.ax_status
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        bad = self.mem.logical_failed
        color = DET_COLOR if bad else FIX_COLOR
        ax.plot([0.11], [0.75], "o", ms=40, mfc=color, mec=INK, mew=1.5)
        ax.text(0.25, 0.80, "LOGICAL ERROR" if bad else "LOGICAL OK", fontsize=16,
                fontweight="bold", color=color, va="center")
        ax.text(0.25, 0.64, self.mem.failure_note if bad else "matches ideal logical state",
                fontsize=8.5, color=INK, va="center", wrap=True)
        par = self.mem.parities
        mode = "PLAYING" if self.playing else "PAUSED"
        lines = [f"cycle {self.mem.cycle}   CNOTs done: {self.mem.cnots_done}   [{mode}]",
                 f"config: {self.mem.config}"
                 + ("   (CNOT queued)" if self.mem.cnot_pending else "")]
        if par:
            lines.append("  ".join(f"{k}={v}" for k, v in
                                   (("Z_C Z_A", par.get("ZZ")), ("X_A X_T", par.get("XX"))) if v))
        ax.text(0.02, 0.32, "\n".join(lines), fontsize=9, color=INK, va="center", linespacing=1.6)

    def _draw_table(self):
        ax = self.ax_table
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("Logical observables of C, T", fontsize=10.5, color=INK, loc="left")
        rows = self.mem.observables()
        ax.text(0.02, 0.93, "operator", fontsize=9, fontweight="bold", color=INK)
        ax.text(0.50, 0.93, "ideal", fontsize=9, fontweight="bold", color=INK)
        ax.text(0.75, 0.93, "simulated", fontsize=9, fontweight="bold", color=INK)
        fmt = {1: "+1", -1: "-1", 0: " 0", None: " ..."}
        for i, (name, ideal, sim) in enumerate(rows):
            y = 0.80 - i * 0.13
            mismatch = sim is not None and sim != ideal
            ax.text(0.02, y, name, fontsize=10, family="monospace", color=INK)
            ax.text(0.52, y, fmt[ideal], fontsize=10, family="monospace", color=INK)
            ax.text(0.78, y, fmt[sim], fontsize=10, family="monospace",
                    color=DET_COLOR if mismatch else INK, fontweight="bold" if mismatch else None)
        ax.text(0.02, -0.04, "simulated = <op> on the Aer state (pending errors show here first)",
                fontsize=7.5, color="#607D8B")

    def _draw_log(self):
        ax = self.ax_log
        ax.clear()
        ax.set_facecolor("white")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#CFD8DC")
        import textwrap
        lines = []
        for m in self.messages:
            lines += textwrap.wrap(m, 92, subsequent_indent="    ")
        ax.text(0.01, 0.98, "\n".join(lines[-20:]), va="top", ha="left", fontsize=8,
                family="monospace", color=INK, transform=ax.transAxes)


def main():
    parser = argparse.ArgumentParser(description="Surface-17 lattice-surgery visualizer")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds per step when playing")
    parser.add_argument("--merge-rounds", type=int, default=1,
                        help="syndrome rounds while patches are merged (default 1)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    viz = LatticeSurgeryVisualizer(args.interval, args.merge_rounds, args.seed)  # noqa: F841
    plt.show()


if __name__ == "__main__":
    main()
