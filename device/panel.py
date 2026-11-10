"""Shared panel data contract for the real Pico and emulator."""

from dataclasses import dataclass, field


DATA_VALUES = frozenset(("on", "x", "z", "y", "off"))
CHECK_VALUES = frozenset(("on", "flagged", "off"))


@dataclass
class Panel:
    d: list[str] = field(default_factory=lambda: ["off"] * 9)
    z: list[str] = field(default_factory=lambda: ["off"] * 4)
    x: list[str] = field(default_factory=lambda: ["off"] * 4)
    logical_failure: bool = False

    def payload(self, reset: bool = False) -> dict:
        for name, values, count, allowed in (
            ("d", self.d, 9, DATA_VALUES),
            ("z", self.z, 4, CHECK_VALUES),
            ("x", self.x, 4, CHECK_VALUES),
        ):
            if not isinstance(values, (list, tuple)):
                raise ValueError(f"{name} must be an array")

            if len(values) != count:
                raise ValueError(
                    f"{name} must contain exactly {count} values"
                )

            if any(
                type(value) is not str or value not in allowed
                for value in values
            ):
                raise ValueError(
                    f"{name} contains an invalid value"
                )

        if type(self.logical_failure) is not bool:
            raise ValueError(
                "logical_failure must be a boolean"
            )

        if type(reset) is not bool:
            raise ValueError("reset must be a boolean")

        return {
            "type": "next",
            "d": list(self.d),
            "z": list(self.z),
            "x": list(self.x),
            "logical_failure": self.logical_failure,
            "reset": reset,
        }
