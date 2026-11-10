from device_connection import DisplayDevice, Panel


def main():
    with DisplayDevice.connect() as device:
        print(f"Connected to display-device at {device.port}")

        # Clear the ten-panel history and insert a blank panel 10.
        reply = device.send_next(Panel(), reset=False)
        print("Reset:", reply)

        # Insert one example populated panel 10.
        reply = device.send_next(
            Panel(
                d=["on", "x", "z", "y", "off", "on", "off", "x", "z"],
                z=["on", "flagged", "off", "on"],
                x=["off", "on", "flagged", "on"],
                logical_failure=False,
            )
        )
        print("Next:", reply)


if __name__ == "__main__":
    main()
