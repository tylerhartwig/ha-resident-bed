#!/usr/bin/env python3
"""Talk to the bed over BLE from this Mac, with no Home Assistant in the loop.

This is the fast iteration path for protocol work: HA only ever wraps
`bed_api/`, so verify command bytes here first, then deploy.

  python3 tools/ble_probe.py scan                  # find the controller
  python3 tools/ble_probe.py dump                  # full GATT table
  python3 tools/ble_probe.py list                  # known commands
  python3 tools/ble_probe.py send TV                # raw write
  python3 tools/ble_probe.py drive TV              # via the HA connection manager
  python3 tools/ble_probe.py send-raw 0c02000040000000000000000000
  python3 tools/ble_probe.py listen --seconds 30   # watch notifications

Needs bleak, which needs Python 3.10+:
  /opt/homebrew/bin/python3.12 -m venv .venv
  .venv/bin/pip install -r requirements-dev.txt
  .venv/bin/python tools/ble_probe.py scan

macOS note: CoreBluetooth reports an opaque per-host UUID, not the real MAC.
The address that works here will NOT be the address Home Assistant uses.
"""

import argparse
import asyncio
import binascii
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ha

sys.path.insert(0, os.path.join(_ha.REPO_ROOT, "custom_components", "resident_bed"))

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("Missing dependency: bleak (needs Python 3.10+)\n"
             "  /opt/homebrew/bin/python3.12 -m venv .venv\n"
             "  .venv/bin/pip install -r requirements-dev.txt\n"
             "  .venv/bin/python tools/ble_probe.py scan")

from bed_api.command import CONTROL_UUID, SERVICE_UUID, BedCommand
from bed_api.resident_bed import ResidentBed


def resolve_address(explicit):
    _ha.load_env()
    address = explicit or os.environ.get("BED_ADDRESS")
    if not address:
        sys.exit("No address. Run `ble_probe.py scan`, then set BED_ADDRESS "
                 "in .env or pass --address.")
    return address


async def do_scan(args):
    print("Scanning %ss for service %s ..." % (args.seconds, SERVICE_UUID))
    devices = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
    matched = False
    for device, adv in devices.values():
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        is_bed = SERVICE_UUID.lower() in uuids
        if is_bed or args.all:
            matched = matched or is_bed
            print("%s  %-28s rssi=%-5s %s"
                  % (device.address, device.name or "<unnamed>", adv.rssi,
                     "  <-- BED" if is_bed else ""))
    if not matched:
        print("\nNo bed found. It only advertises when awake -- press a button "
              "on the physical remote, or power-cycle the base, then retry.\n"
              "Re-run with --all to see every nearby device.")


async def do_dump(args):
    async with BleakClient(resolve_address(args.address), timeout=30) as client:
        print("connected=%s\n" % client.is_connected)
        for service in client.services:
            print("service %s  (%s)" % (service.uuid, service.description))
            for char in service.characteristics:
                print("  char %s  handle=%-4s props=%s"
                      % (char.uuid, char.handle, ",".join(char.properties)))
                for desc in char.descriptors:
                    print("    desc %s handle=%s" % (desc.uuid, desc.handle))


async def _write(address, payload):
    async with BleakClient(resolve_address(address), timeout=30) as client:
        print("connected=%s, writing %s to %s"
              % (client.is_connected, payload.hex(), CONTROL_UUID))
        await client.write_gatt_char(CONTROL_UUID, payload, response=True)
        print("write ok")


async def do_send(args):
    try:
        command = BedCommand[args.command]
    except KeyError:
        sys.exit("Unknown command %r. Known: %s"
                 % (args.command, ", ".join(BedCommand.__members__)))
    await _write(args.address, command.payload)


async def do_drive(args):
    """Send a command through the real ResidentBed connection manager.

    Same code path Home Assistant uses -- retries, route re-resolution, service
    cache, keepalive -- so reliability work can be exercised without deploying.
    """
    from bleak import BleakScanner

    address = resolve_address(args.address)
    device = await BleakScanner.find_device_by_address(address, timeout=args.seconds)
    if device is None:
        sys.exit("Could not find %s while scanning for %ss." % (address, args.seconds))

    try:
        command = BedCommand[args.command]
    except KeyError:
        sys.exit("Unknown command %r. Known: %s"
                 % (args.command, ", ".join(BedCommand.__members__)))

    bed = ResidentBed(
        address=address,
        name=device.name or address,
        ble_device_callback=lambda: device,
        always_connected=False,
    )
    try:
        await bed.async_send_command(command)
        print("sent %s via %s" % (command.display_name, bed.last_route))
    finally:
        await bed.async_disconnect()


async def do_send_raw(args):
    await _write(args.address, binascii.a2b_hex("".join(args.hex)))


async def do_listen(args):
    def on_notify(_sender, data):
        print("notify: %s" % data.hex())

    async with BleakClient(resolve_address(args.address), timeout=30) as client:
        await client.start_notify(CONTROL_UUID, on_notify)
        print("listening %ss on %s (Ctrl-C to stop)" % (args.seconds, CONTROL_UUID))
        await asyncio.sleep(args.seconds)
        await client.stop_notify(CONTROL_UUID)


def do_list(_args):
    for name, member in BedCommand.__members__.items():
        print("%-14s %-30s %s" % (name, member.display_name, member.value))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--address", help="override BED_ADDRESS")
    sub = parser.add_subparsers(dest="action", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--seconds", type=float, default=10.0)
    scan.add_argument("--all", action="store_true", help="show every device")

    sub.add_parser("dump")
    sub.add_parser("list")

    send = sub.add_parser("send")
    send.add_argument("command")

    raw = sub.add_parser("send-raw")
    raw.add_argument("hex", nargs="+", help="hex bytes, spaces allowed")

    listen = sub.add_parser("listen")
    listen.add_argument("--seconds", type=float, default=30.0)

    drive = sub.add_parser(
        "drive", help="send via the real connection manager (as HA does)")
    drive.add_argument("command")
    drive.add_argument("--seconds", type=float, default=10.0)

    args = parser.parse_args()
    if args.action == "list":
        do_list(args)
        return

    handler = {
        "scan": do_scan, "dump": do_dump, "send": do_send,
        "send-raw": do_send_raw, "listen": do_listen, "drive": do_drive,
    }[args.action]
    try:
        asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
