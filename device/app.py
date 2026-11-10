"""Live bidirectional demonstration for Pico or local emulator."""

import time

from display_device import DisplayDevice, Panel


DATA_VALUES = ("on", "x", "z", "y", "off")


def make_panel(step, d=None):
    """Generate a visible test panel, optionally using device-selected d."""
    return Panel(
        d=list(d) if d is not None else [
            DATA_VALUES[(step + i) % len(DATA_VALUES)]
            for i in range(9)
        ],
        z=[
            "flagged" if i == step % 4 else "on"
            for i in range(4)
        ],
        x=[
            "flagged" if i == (step + 1) % 4 else "on"
            for i in range(4)
        ],
        logical_failure=(step % 5 == 4),
    )


def main():
    print("Connecting to display device...")

    with DisplayDevice.connect() as device:
        print(f"Connected: {device.port}")

        step = 0
        paused = False
        mode = None
        current_d = ["off"] * 9

        # Start with one panel in position 10.
        ack = device.send_next(
            make_panel(step),
            reset=True,
        )
        print(f"INITIAL PANEL -> {ack}")

        print("\nLive demonstration running.")
        print("Try PAUSE, data buttons, mode, NEXT, or hold NEXT for RESET.")
        print("Press Ctrl+C to exit.\n")

        try:
            while True:
                event = device.read_message(timeout=0.25)

                if event is None:
                    continue

                if event.get("type") != "event":
                    continue

                event_name = event.get("event")
                current_d = event.get("d", current_d)
                paused = event.get("pause", paused)
                mode = event.get("mode", mode)

                print(
                    f"EVENT {event_name:13} "
                    f"seq={event.get('seq')} "
                    f"pause={paused} "
                    f"mode={mode}"
                )

                if event_name == "next_request":
                    step += 1

                    # The device has already captured the old
                    # panel 10 for preservation in history.
                    # We only supply the next panel.
                    panel = make_panel(step, d=current_d)

                    ack = device.send_next(panel)
                    print(f"  SENT NEXT -> {ack}")

                elif event_name == "reset":
                    step = 0

                    ack = device.send_next(
                        make_panel(step),
                        reset=True,
                    )
                    print(f"  SENT RESET -> {ack}")

                elif event_name == "update":
                    print(f"  Current displayed D: {current_d}")

                elif event_name == "pause":
                    print("  Simulation paused.")

                elif event_name == "run":
                    print("  Simulation running.")

                elif event_name == "mode":
                    print(f"  Mode changed to {mode}.")

                else:
                    print(f"  Unknown event: {event}")

        except KeyboardInterrupt:
            print("\nDisconnecting.")


if __name__ == "__main__":
    main()
