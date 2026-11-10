"""Interactive hardware test for the ten-panel Pico LED display."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from display_device import DisplayDevice, Panel


DATA_STATES = ("off", "on", "x", "z", "y")
CHECK_STATES = ("off", "on", "flagged")

OFF_D = ["off"] * 9
OFF_CHECK = ["off"] * 4


def blank_panel():
    return Panel(
        d=OFF_D.copy(),
        x=OFF_CHECK.copy(),
        z=OFF_CHECK.copy(),
        logical_failure=False,
    )


def make_panel(kind, index, state):
    d = OFF_D.copy()
    x = OFF_CHECK.copy()
    z = OFF_CHECK.copy()
    failure = False

    if kind == "D":
        d[index] = state
    elif kind == "X":
        x[index] = state
    elif kind == "Z":
        z[index] = state
    elif kind == "FAILURE":
        failure = state == "on"

    return Panel(
        d=d,
        x=x,
        z=z,
        logical_failure=failure,
    )


class LedTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Pico LED Hardware Tester")
        self.root.geometry("860x690")
        self.root.minsize(620, 540)

        self.selected = None
        self.state = "off"
        self.panel_number = tk.IntVar(value=10)

        self.commands = queue.Queue()
        self.responses = queue.Queue()
        self.buttons = {}

        self.status = tk.StringVar(value="Connecting...")
        self.selection_label = tk.StringVar(
            value="Select an indicator to begin."
        )

        self.build_ui()

        self.worker = threading.Thread(
            target=self.device_worker,
            daemon=True,
            name="led-test-device",
        )
        self.worker.start()

        self.root.after(100, self.poll_responses)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        main.columnconfigure(0, weight=1)

        title = ttk.Label(
            main,
            text="Pico LED Hardware Tester",
            font=("Segoe UI", 20, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            main,
            text=(
                "Test one logical indicator at a time. "
                "Click the same button repeatedly to cycle states."
            ),
        )
        subtitle.grid(
            row=1, column=0, sticky="w", pady=(4, 14)
        )

        settings = ttk.LabelFrame(
            main, text="Target physical panel", padding=12
        )
        settings.grid(row=2, column=0, sticky="ew")

        ttk.Label(
            settings,
            text="Panel number:",
        ).pack(side="left", padx=(0, 10))

        panel_picker = ttk.Combobox(
            settings,
            textvariable=self.panel_number,
            values=list(range(1, 11)),
            width=6,
            state="readonly",
        )
        panel_picker.pack(side="left")
        panel_picker.bind(
            "<<ComboboxSelected>>",
            self.change_panel,
        )

        ttk.Label(
            settings,
            text="Panel 10 is newest; Panel 1 is oldest.",
        ).pack(side="left", padx=16)

        self.make_group(
            main,
            row=3,
            title="X checks",
            kind="X",
            count=4,
            columns=4,
        )

        self.make_group(
            main,
            row=4,
            title="Z checks",
            kind="Z",
            count=4,
            columns=4,
        )

        self.make_group(
            main,
            row=5,
            title="Data qubits",
            kind="D",
            count=9,
            columns=9,
        )

        failure = ttk.LabelFrame(
            main,
            text="Logical failure indicators",
            padding=12,
        )
        failure.grid(
            row=6,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        button = tk.Button(
            failure,
            text="Logical Failure",
            font=("Segoe UI", 11, "bold"),
            width=20,
            height=2,
            command=lambda: self.click("FAILURE", 0),
        )
        button.pack(side="left")
        self.buttons[("FAILURE", 0)] = button

        ttk.Label(
            failure,
            text="Tests the selected panel's outer LEDs and divider LEDs.",
            wraplength=430,
        ).pack(side="left", padx=15)

        controls = ttk.Frame(main)
        controls.grid(
            row=7,
            column=0,
            sticky="ew",
            pady=(18, 6),
        )

        ttk.Button(
            controls,
            text="Clear all LEDs",
            command=self.clear,
        ).pack(side="left")

        ttk.Button(
            controls,
            text="Resend selected state",
            command=self.send_selection,
        ).pack(side="left", padx=10)

        ttk.Button(
            controls,
            text="Reconnect",
            command=lambda: self.commands.put(("reconnect",)),
        ).pack(side="left")

        selected = ttk.Label(
            main,
            textvariable=self.selection_label,
            font=("Segoe UI", 13, "bold"),
        )
        selected.grid(
            row=8, column=0, sticky="w", pady=(10, 6)
        )

        connection = ttk.Label(
            main,
            textvariable=self.status,
            wraplength=760,
        )
        connection.grid(row=9, column=0, sticky="ew")

        help_text = (
            "D states: off -> on -> x -> z -> y -> off\n"
            "X/Z states: off -> on -> flagged -> off\n"
            "Logical failure: off -> on -> off\n\n"
            "Changing indicators turns the previous one off.\n"
            "Each test reconstructs the full ten-panel history "
            "using the existing NEXT protocol."
        )

        help_label = ttk.Label(
            main,
            text=help_text,
            foreground="#666666",
            justify="left",
        )
        help_label.grid(
            row=10,
            column=0,
            sticky="w",
            pady=(14, 0),
        )

    def make_group(self, parent, row, title, kind, count, columns):
        group = ttk.LabelFrame(
            parent, text=title, padding=12
        )
        group.grid(
            row=row,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        for col in range(columns):
            group.columnconfigure(col, weight=1)

        for index in range(count):
            key = (kind, index)
            button = tk.Button(
                group,
                text=f"{kind}{index + 1}\noff",
                font=("Segoe UI", 11, "bold"),
                height=2,
                command=lambda k=kind, i=index: self.click(k, i),
            )
            button.grid(
                row=index // columns,
                column=index % columns,
                sticky="ew",
                padx=3,
                pady=3,
            )
            self.buttons[key] = button

    def click(self, kind, index):
        key = (kind, index)

        if self.selected == key:
            states = (
                DATA_STATES if kind == "D"
                else CHECK_STATES if kind in ("X", "Z")
                else ("off", "on")
            )
            position = states.index(self.state)
            self.state = states[(position + 1) % len(states)]
        else:
            self.selected = key
            self.state = "on"

        self.update_buttons()
        self.send_selection()

    def update_buttons(self):
        for key, button in self.buttons.items():
            kind, index = key
            active = key == self.selected

            state = self.state if active else "off"

            if kind == "FAILURE":
                caption = f"Logical Failure\n{state}"
            else:
                caption = f"{kind}{index + 1}\n{state}"

            if active and state != "off":
                if state == "flagged":
                    color = "#ff7777"
                elif state == "x":
                    color = "#66d7d1"
                elif state == "z":
                    color = "#ffc078"
                elif state == "y":
                    color = "#d0a4ff"
                else:
                    color = "#a9e3b1"
            else:
                color = "#eeeeee"

            button.configure(
                text=caption,
                bg=color,
                activebackground=color,
                relief="sunken" if active else "raised",
            )

        if self.selected is None:
            self.selection_label.set("All indicators off")
        else:
            kind, index = self.selected
            label = (
                "Logical Failure" if kind == "FAILURE"
                else f"{kind}{index + 1}"
            )
            self.selection_label.set(
                f"Panel {self.panel_number.get()} "
                f"| {label} = {self.state}"
            )

    def change_panel(self, _event=None):
        self.update_buttons()
        self.send_selection()

    def send_selection(self):
        if self.selected is None:
            self.commands.put(("show", self.panel_number.get(), None))
            return

        kind, index = self.selected
        self.commands.put((
            "show",
            self.panel_number.get(),
            (kind, index, self.state),
        ))

    def clear(self):
        self.selected = None
        self.state = "off"
        self.update_buttons()
        self.commands.put(("show", self.panel_number.get(), None))

    def device_worker(self):
        device = None

        def connect():
            nonlocal device

            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass

            device = None

            try:
                device = DisplayDevice.connect()
                self.responses.put((
                    "status",
                    f"Connected: {device.port}",
                ))
            except Exception as error:
                self.responses.put((
                    "status",
                    f"Connection failed: {error}",
                ))

        connect()

        while True:
            command = self.commands.get()
            action = command[0]

            if action == "quit":
                break

            if action == "reconnect":
                connect()
                continue

            if action != "show":
                continue

            # Keep the latest requested state if the user
            # clicked multiple buttons during transmission.
            while True:
                try:
                    newer = self.commands.get_nowait()
                except queue.Empty:
                    break

                if newer[0] == "show":
                    command = newer
                elif newer[0] == "quit":
                    action = "quit"
                    break
                elif newer[0] == "reconnect":
                    connect()

            if action == "quit":
                break

            if device is None:
                self.responses.put((
                    "status",
                    "Not connected. Click Reconnect.",
                ))
                continue

            _, target_panel, selection = command

            try:
                # Reconstruct panels 1 through 10.
                # The first frame resets all previous history.
                # Each subsequent NEXT shifts the frame left.
                # Thus the frame at position N ends at Panel N.
                #
                # We send a new blank panel for every other
                # position, ensuring exactly one test indicator.
                for panel_number in range(1, 11):
                    if selection is not None and panel_number == target_panel:
                        kind, index, state = selection
                        frame = make_panel(kind, index, state)
                    else:
                        frame = blank_panel()

                    ack = device.send_next(
                        frame,
                        reset=(panel_number == 1),
                    )

                    if not ack.get("ok", False):
                        raise RuntimeError(
                            f"Panel {panel_number}: {ack}"
                        )

                label = (
                    "all LEDs off"
                    if selection is None
                    else (
                        f"{selection[0]}"
                        f"{selection[1] + 1 if selection[0] != 'FAILURE' else ''}"
                        f" = {selection[2]}"
                    )
                )

                self.responses.put((
                    "status",
                    f"{device.port} | Panel {target_panel} | "
                    f"{label} | ACK revision "
                    f"{ack.get('revision', '?')}",
                ))

            except Exception as error:
                self.responses.put((
                    "status",
                    f"Device communication error: {error}",
                ))

        if device is not None:
            try:
                device.close()
            except Exception:
                pass

    def poll_responses(self):
        try:
            while True:
                kind, message = self.responses.get_nowait()
                if kind == "status":
                    self.status.set(message)
        except queue.Empty:
            pass

        self.root.after(100, self.poll_responses)

    def close(self):
        self.commands.put(("quit",))
        self.root.destroy()


def main():
    root = tk.Tk()
    LedTestApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
