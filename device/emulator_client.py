"""Local emulator transport compatible with display_device.py."""

import json
import queue
import socket
import threading

from display_device import Panel


class DisplayDevice:
    def __init__(self, sock, on_message=None):
        self._socket = sock
        self.port = "emulator://127.0.0.1:8765"
        self._callback = on_message

        self._acks = queue.Queue()
        self._events = queue.Queue()
        self._lock = threading.Lock()
        self._error = None
        self._closed = False

        self._thread = threading.Thread(
            target=self._reader,
            daemon=True,
        )
        self._thread.start()

    @classmethod
    def connect(cls, vid=None, pid=None, on_message=None):
        # VID/PID are accepted for API compatibility.
        try:
            sock = socket.create_connection(
                ("127.0.0.1", 8765),
                timeout=3,
            )
        except OSError as exc:
            raise ConnectionError(
                "Start emulator.py before connecting"
            ) from exc

        sock.settimeout(None)
        return cls(sock, on_message=on_message)

    def _reader(self):
        try:
            with self._socket.makefile("rb") as stream:
                for raw in stream:
                    message = json.loads(raw)

                    if message.get("type") == "ack":
                        self._acks.put(message)
                    else:
                        self._events.put(message)

                        if self._callback is not None:
                            try:
                                self._callback(message)
                            except Exception:
                                pass

        except (OSError, ValueError) as exc:
            self._error = exc
        finally:
            self._acks.put(None)

    def send_next(self, panel, reset=False, timeout=3.0):
        if not isinstance(panel, Panel):
            raise TypeError("panel must be a Panel")

        payload = panel.payload(reset=reset)

        with self._lock:
            if self._closed or self._error:
                raise ConnectionError(
                    f"Emulator disconnected: {self._error}"
                )

            data = (
                json.dumps(payload, separators=(",", ":")) + "\n"
            ).encode("utf-8")

            self._socket.sendall(data)

            try:
                ack = self._acks.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError(
                    "Emulator acknowledgment timed out"
                ) from exc

            if ack is None:
                raise ConnectionError("Emulator disconnected")

            if not ack.get("ok"):
                raise ValueError(f"Panel rejected: {ack}")

            return ack

    def next(self, panel, reset=False, timeout=3.0):
        return self.send_next(
            panel, reset=reset, timeout=timeout
        )

    def read_message(self, timeout=0.0):
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        if not self._closed:
            self._closed = True

            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            self._socket.close()
            self._thread.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
