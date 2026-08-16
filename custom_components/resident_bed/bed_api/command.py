"""Command definitions for OKIN-based Resident adjustable bed bases.

Pure protocol -- this module must not import Home Assistant.

Payloads are fixed-length hex bit-masks written to the control characteristic.
Note the frame length is not uniform: most commands are 14 bytes, but the
combined head+feet commands are 10.
"""

from enum import Enum

# Advertised service, used for Bluetooth discovery in manifest.json.
SERVICE_UUID = "62741523-52f9-8864-b1ab-3b3a8d65950b"

# Control characteristic. Supports both write and notify.
CONTROL_UUID = "62741525-52f9-8864-b1ab-3b3a8d65950b"


class BedCommand(Enum):
    """A bed command and its wire payload.

    Do NOT define a member or method called `name` here: `name` is the Enum
    member-name attribute, and shadowing it silently turns `command.name` into
    a bound method. Use `display_name` for human-facing text.
    """

    LED = "0c02000200000000000000000000"

    Flat = "0c02080000000000000000000000"

    ZeroGravity = "0c02000010000000000000000000"
    Reading = "0c02000020000000000000000000"
    TV = "0c02000040000000000000000000"
    Sleeping = "0c02000080000000000000000000"

    HeadFeetUp = "08020000000500000000"
    HeadFeetDown = "08020000000a00000000"
    HeadUp = "0c02000000010000000000000000"
    HeadDown = "0c02000000020000000000000000"
    FeetUp = "0c02000000040000000000000000"
    FeetDown = "0c02000000080000000000000000"

    M1 = "0c02000100000000000000000000"
    M2 = "0c02000400000000000000000000"

    @property
    def display_name(self) -> str:
        """Human-readable label, used as the entity name fallback."""
        return _DISPLAY_NAMES[self]

    @property
    def payload(self) -> bytes:
        """The raw bytes to write to the control characteristic."""
        return bytes.fromhex(self.value)


_DISPLAY_NAMES = {
    BedCommand.LED: "LED",
    BedCommand.Flat: "Flat",
    BedCommand.ZeroGravity: "Zero Gravity",
    BedCommand.Reading: "Reading",
    BedCommand.TV: "TV",
    BedCommand.Sleeping: "Sleeping",
    BedCommand.HeadFeetUp: "Head & Feet Up",
    BedCommand.HeadFeetDown: "Head & Feet Down",
    BedCommand.HeadUp: "Head Up",
    BedCommand.HeadDown: "Head Down",
    BedCommand.FeetUp: "Feet Up",
    BedCommand.FeetDown: "Feet Down",
    BedCommand.M1: "M1",
    BedCommand.M2: "M2",
}

# Every member must have a label; catch omissions at import time rather than
# rendering a broken entity name.
assert set(_DISPLAY_NAMES) == set(BedCommand), "BedCommand/_DISPLAY_NAMES out of sync"


# Undocumented payloads kept for protocol exploration via tools/ble_probe.py.
# Not exposed as entities.
EXPERIMENTAL = {
    "TEST": "0c02000002000000000000000000",
    "RAMP_UP": "0c02000000000010000000000000",
    "RAMP_DOWN": "0c02000000000020000000000000",
    "STOP_MASSAGE": "0c02020000000000000000000000",
}
