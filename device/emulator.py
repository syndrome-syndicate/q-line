import json
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

HOST, PORT = "127.0.0.1", 8765
DATA = ("off", "on", "x", "z", "y")
CHECK = ("off", "on", "flagged")
COLORS = {
    "off": "#303238", "on": "#ffffff",
    "x": "#16b8a2", "z": "#ff9b35",
    "y": "#bf65ff", "flagged": "#ff4343"
}


def blank():
    return {
        "d": ["off"] * 9,
        "z": ["off"] * 4,
        "x": ["off"] * 4,
        "logical_failure": False,
    }


def clone(panel):
    return {
        "d": panel["d"][:],
        "z": panel["z"][:],
        "x": panel["x"][:],
        "logical_failure": panel["logical_failure"],
    }


def parse_next(msg):
    if not isinstance(msg, dict) or msg.get("type") != "next":
        raise ValueError("invalid_next")

    allowed = {"type", "d", "z", "x", "logical_failure", "reset"}
    if set(msg) - allowed:
        raise ValueError("invalid_next")

    for key, length, values in (
        ("d", 9, DATA),
        ("z", 4, CHECK),
        ("x", 4, CHECK),
    ):
        items = msg.get(key)
        if (
            not isinstance(items, list)
            or len(items) != length
            or any(type(v) is not str or v not in values for v in items)
        ):
            raise ValueError("invalid_next")

    if type(msg.get("reset", False)) is not bool:
        raise ValueError("invalid_next")

    if type(msg.get("logical_failure", False)) is not bool:
        raise ValueError("invalid_next")

    return {
        "d": msg["d"][:],
        "z": msg["z"][:],
        "x": msg["x"][:],
        "logical_failure": msg.get("logical_failure", False),
    }


class Emulator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Display Device Emulator")
        self.root.geometry("1350x680")
        self.root.minsize(1050, 560)

        self.panels = [blank() for _ in range(10)]
        self.original = blank()
        self.requested = None

        self.pause = False
        self.mode = 1
        self.selector = "x"
        self.selected_data = 0

        self.sequence = 0
        self.revision = 0
        self.hold_start = None
        self.long_sent = False

        self.incoming = queue.Queue()
        self.client = None
        self.client_lock = threading.Lock()

        self.build_ui()
        self.redraw()

        threading.Thread(
            target=self.server, daemon=True
        ).start()

        self.root.after(30, self.process_incoming)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self):
        root = ttk.Frame(self.root, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root, text="DISPLAY DEVICE EMULATOR",
            font=("Segoe UI", 15, "bold")
        ).pack(anchor="w")

        ttk.Label(
            root,
            text="10-panel history | localhost:8765 | no Pico required"
        ).pack(anchor="w", pady=(2, 12))

        board = ttk.Frame(root)
        board.pack(fill="x")

        self.views = []

        for p in range(10):
            frame = ttk.LabelFrame(
                board, text=f"Panel {p + 1}", padding=4
            )
            frame.grid(row=0, column=p, padx=2, sticky="nsew")
            board.columnconfigure(p, weight=1)

            cells = []
            for i in range(9):
                cell = tk.Label(
                    frame, width=3, height=1,
                    relief="groove", bd=1,
                    font=("Consolas", 8, "bold")
                )
                cell.grid(
                    row=i // 3, column=i % 3,
                    padx=1, pady=1, sticky="ew"
                )
                cells.append(cell)

            z = ttk.Label(frame, font=("Consolas", 8))
            z.grid(row=3, column=0, columnspan=3, pady=(6, 0))

            x = ttk.Label(frame, font=("Consolas", 8))
            x.grid(row=4, column=0, columnspan=3)

            failure = ttk.Label(
                frame, font=("Consolas", 8, "bold")
            )
            failure.grid(row=5, column=0, columnspan=3)

            self.views.append((cells, z, x, failure))

        lower = ttk.Frame(root)
        lower.pack(fill="both", expand=True, pady=(18, 0))

        buttons = ttk.LabelFrame(
            lower, text="DATA BUTTONS", padding=10
        )
        buttons.pack(side="left", anchor="n", padx=(0, 14))

        self.data_buttons = []

        for i in range(9):
            b = ttk.Button(
                buttons, text=f"D{i+1}", width=7,
                command=lambda index=i: self.data_press(index)
            )
            b.grid(
                row=i // 3, column=i % 3,
                padx=5, pady=5
            )
            self.data_buttons.append(b)

        controls = ttk.LabelFrame(
            lower, text="CONTROLS", padding=10
        )
        controls.pack(side="left", anchor="n", padx=(0, 14))

        ttk.Label(
            controls, text="X/Z selector"
        ).pack(anchor="w")

        self.selector_var = tk.StringVar(value="x")
        selector_row = ttk.Frame(controls)
        selector_row.pack(anchor="w")

        for value in ("x", "z"):
            ttk.Radiobutton(
                selector_row,
                text=value.upper(),
                variable=self.selector_var,
                value=value,
                command=self.selector_change,
            ).pack(side="left")

        self.pause_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            controls,
            text="PAUSE (latching)",
            variable=self.pause_var,
            command=self.toggle_pause,
        ).pack(anchor="w", pady=(12, 7))

        ttk.Button(
            controls,
            text="X/Z momentary",
            command=self.xz_momentary,
        ).pack(fill="x")

        ttk.Label(
            controls, text="Mode selector (1-8)"
        ).pack(anchor="w", pady=(12, 0))

        mode_row = ttk.Frame(controls)
        mode_row.pack(fill="x")

        ttk.Button(
            mode_row, text="<", width=3,
            command=lambda: self.change_mode(-1)
        ).pack(side="left")

        self.mode_label = ttk.Label(
            mode_row, text="1", width=5,
            anchor="center",
            font=("Segoe UI", 12, "bold")
        )
        self.mode_label.pack(side="left")

        ttk.Button(
            mode_row, text=">", width=3,
            command=lambda: self.change_mode(1)
        ).pack(side="left")

        next_frame = ttk.LabelFrame(
            lower, text="NEXT / RESET", padding=10
        )
        next_frame.pack(side="left", anchor="n", padx=(0, 14))

        next_button = tk.Button(
            next_frame,
            text="NEXT\nHold 2 seconds for RESET",
            width=22, height=5,
            bg="#e2f2e9"
        )
        next_button.pack()
        next_button.bind("<ButtonPress-1>", self.next_down)
        next_button.bind("<ButtonRelease-1>", self.next_up)

        status_frame = ttk.LabelFrame(
            lower, text="STATUS / EVENTS", padding=10
        )
        status_frame.pack(side="left", fill="both", expand=True)

        self.status = ttk.Label(status_frame, justify="left")
        self.status.pack(anchor="w")

        self.log_box = tk.Text(
            status_frame, height=10, width=48,
            state="disabled", font=("Consolas", 9)
        )
        self.log_box.pack(fill="both", expand=True, pady=(10, 0))

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def redraw(self):
        for i, panel in enumerate(self.panels):
            cells, z_label, x_label, failure = self.views[i]

            for j, value in enumerate(panel["d"]):
                cells[j].configure(
                    text=value.upper() if value != "off" else ".",
                    bg=COLORS[value],
                    fg="#171717" if value == "on" else "#ffffff"
                )

            def symbol(v):
                return {
                    "off": ".", "on": "+", "flagged": "!"
                }[v]

            z_label.configure(
                text="Z " + " ".join(map(symbol, panel["z"]))
            )
            x_label.configure(
                text="X " + " ".join(map(symbol, panel["x"]))
            )
            failure.configure(
                text="FAILURE" if panel["logical_failure"] else ""
            )

        self.mode_label.configure(text=str(self.mode))

        self.status.configure(
            text=(
                f"Paused: {self.pause}\n"
                f"Mode: {self.mode}\n"
                f"Selector: {self.selector.upper()}\n"
                f"Next request pending: {self.requested is not None}\n"
                f"Revision: {self.revision}\n"
                f"Event sequence: {self.sequence}"
            )
        )

        for button in self.data_buttons:
            button.configure(
                state="normal" if self.pause else "disabled"
            )

    def server(self):
        try:
            with socket.socket() as listener:
                listener.setsockopt(
                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
                )
                listener.bind((HOST, PORT))
                listener.listen(1)

                while True:
                    sock, _ = listener.accept()

                    with self.client_lock:
                        if self.client is not None:
                            sock.close()
                            continue
                        self.client = sock

                    self.incoming.put(("log", "App connected"))

                    try:
                        with sock, sock.makefile("rb") as stream:
                            for line in stream:
                                try:
                                    message = (
                                        json.loads(line)
                                        if len(line) <= 4096
                                        else None
                                    )
                                except (ValueError, UnicodeError):
                                    message = None

                                self.incoming.put(("next", message))
                    finally:
                        with self.client_lock:
                            if self.client is sock:
                                self.client = None
                        self.incoming.put(("log", "App disconnected"))

        except OSError as exc:
            self.incoming.put(("log", f"Server error: {exc}"))

    def send(self, message):
        data = (
            json.dumps(message, separators=(",", ":")) + "\n"
        ).encode("utf-8")

        with self.client_lock:
            if self.client is not None:
                try:
                    self.client.sendall(data)
                except OSError:
                    pass

    def process_incoming(self):
        try:
            while True:
                kind, value = self.incoming.get_nowait()

                if kind == "log":
                    self.log(value)
                elif kind == "next":
                    self.receive_next(value)

        except queue.Empty:
            pass

        self.root.after(30, self.process_incoming)

    def receive_next(self, message):
        try:
            incoming = parse_next(message)
        except ValueError:
            self.send({
                "type": "ack",
                "ok": False,
                "error": "invalid_next",
            })
            self.log("Rejected invalid NEXT")
            return

        if message.get("reset", False):
            self.panels = [blank() for _ in range(10)]
        else:
            preserved = (
                self.requested
                if self.requested is not None
                else self.original
            )

            # Old panels 2-9 become panels 1-8.
            # Preserved panel 10 becomes panel 9.
            self.panels = (
                self.panels[1:9]
                + [clone(preserved), blank()]
            )

        self.panels[9] = incoming
        self.original = clone(incoming)
        self.requested = None
        self.revision += 1

        self.send({
            "type": "ack",
            "ok": True,
            "revision": self.revision,
        })

        self.log(
            f"NEXT received: reset={message.get('reset', False)}"
        )
        self.redraw()

    def emit(self, event):
        self.sequence += 1

        message = {
            "type": "event",
            "event": event,
            "seq": self.sequence,
            "d": self.panels[9]["d"][:],
            "mode": self.mode,
            "pause": self.pause,
        }

        self.send(message)
        self.log(f"EVENT {event} #{self.sequence}")
        self.redraw()

    def data_press(self, index):
        if not self.pause:
            return

        self.selected_data = index
        old = self.panels[9]["d"][index]

        # Temporary cycling rule for testing.
        next_value = DATA[(DATA.index(old) + 1) % len(DATA)]

        self.panels[9]["d"][index] = next_value
        self.revision += 1

        self.emit("update")

    def selector_change(self):
        self.selector = self.selector_var.get()
        self.redraw()

    def xz_momentary(self):
        # Temporary behavior: cycle the last selected data item.
        if self.pause:
            self.data_press(self.selected_data)

    def toggle_pause(self):
        self.pause = self.pause_var.get()
        self.emit("pause" if self.pause else "run")

    def change_mode(self, delta):
        self.mode = (self.mode - 1 + delta) % 8 + 1
        self.emit("mode")

    def next_down(self, event):
        self.hold_start = time.monotonic()
        self.long_sent = False
        self.root.after(50, self.check_hold)

    def check_hold(self):
        if self.hold_start is None or self.long_sent:
            return

        if time.monotonic() - self.hold_start >= 2.0:
            self.long_sent = True
            self.emit("reset")
        else:
            self.root.after(50, self.check_hold)

    def next_up(self, event):
        if self.hold_start is None:
            return

        if not self.long_sent:
            elapsed = time.monotonic() - self.hold_start

            if elapsed >= 2.0:
                self.emit("reset")
            else:
                self.requested = clone(self.panels[9])
                self.emit("next_request")

        self.hold_start = None

    def close(self):
        with self.client_lock:
            if self.client is not None:
                try:
                    self.client.shutdown(socket.SHUT_RDWR)
                    self.client.close()
                except OSError:
                    pass
                self.client = None

        self.root.destroy()


if __name__ == "__main__":
    Emulator().root.mainloop()
