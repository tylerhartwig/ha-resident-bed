import binascii
from enum import Enum

class BedCommand(str, Enum):
    LED =           "0c02000200000000000000000000"

    Flat =          "0c02080000000000000000000000"

    ZeroGravity =   "0c02000010000000000000000000"
    Reading =       "0c02000020000000000000000000"
    TV =            "0c02000040000000000000000000"
    Sleeping =      "0c02000080000000000000000000"

    HeadUp =        "0c02000000010000000000000000"
    HeadDown =      "0c02000000020000000000000000"
    FeetUp =        "0c02000000040000000000000000"
    FeetDown =      "0c02000000080000000000000000"

    M1 =            "0c02000100000000000000000000"
    M2 =            "0c02000400000000000000000000"

    def name(self) -> str:
        match self:
            case BedCommand.LED: return "LED"
            case BedCommand.Flat: return "Flat"
            case BedCommand.ZeroGravity: return "Zero Gravity"
            case BedCommand.Reading: return "Reading"
            case BedCommand.TV: return "TV"
            case BedCommand.Sleeping: return "Sleeping"
            case BedCommand.HeadUp: return "Head Up"
            case BedCommand.HeadDown: return "Head Down"
            case BedCommand.FeetUp: return "Feet Up"
            case BedCommand.FeetDown: return "Feet Down"
            case BedCommand.M1: return "M1"
            case BedCommand.M2: return "M2"



# LED =          binascii.a2b_hex()
# FLAT =          binascii.a2b_hex()


# ??
# TEST =          binascii.a2b_hex("0c02000002000000000000000000")
TEST =          "0c02000002000000000000000000"

# TEST =         binascii.a2b_hex("0c02000800000000000000000000")
RAMP_UP =      "0c02000000000010000000000000"
RAMP_DOWN =    "0c02000000000020000000000000"
# TEST =         binascii.a2b_hex("0c02000800000080000000000000")
# TEST =         binascii.a2b_hex("0c02000000000000000000000000")
STOP_MASSAGE = "0c02020000000000000000000000"

READ_NOTIFY_CONTROL_HANDLE = 15
WRITE_CONTROL_HANDLE = 18
