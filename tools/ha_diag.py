#!/usr/bin/env python3
"""Show how Home Assistant can currently reach each configured bed.

Flaky bed connections are usually a routing problem: the bed is being served by
an adapter or proxy that barely hears it while a much closer one sits unused, or
the serving adapter is out of connection slots. Home Assistant already tracks
all of this -- this prints it.

  python3 tools/ha_diag.py routes      # per-adapter RSSI + slots for each bed
  python3 tools/ha_diag.py adapters    # adapter/proxy inventory
  python3 tools/ha_diag.py entries     # config entries for this integration

Nothing is hardcoded: beds, adapters, and addresses are all read from the
running instance.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ha

DOMAIN = "resident_bed"
BLUETOOTH_DOMAIN = "bluetooth"


def _entries():
    return _ha.request("GET", "/api/config/config_entries/entry").json()


def _bed_entries():
    """Every configured bed, as (title, address, state)."""
    beds = []
    for entry in _entries():
        if entry.get("domain") != DOMAIN:
            continue
        data = entry.get("data") or {}
        address = data.get("address") or data.get("mac")
        # Older entries may not expose data over the API; fall back to the
        # address embedded in the entry title by earlier versions.
        if not address and entry.get("title", "").count(":") == 5:
            address = entry["title"].rsplit("-", 1)[-1]
        beds.append((entry.get("title") or DOMAIN, address, entry.get("state")))
    return beds


def _bluetooth_diagnostics():
    """Diagnostics from any loaded bluetooth entry (they all share a manager)."""
    for entry in _entries():
        if entry.get("domain") != BLUETOOTH_DOMAIN or entry.get("state") != "loaded":
            continue
        try:
            return _ha.request(
                "GET", "/api/diagnostics/config_entry/" + entry["entry_id"]
            ).json()["data"]["manager"]
        except SystemExit:
            continue
    sys.exit("No loaded bluetooth config entry exposed diagnostics.")


def cmd_adapters(_args):
    manager = _bluetooth_diagnostics()
    allocations = manager.get("allocations") or {}

    print("%-46s %-11s %-9s %-7s %-8s %s"
          % ("ADAPTER / PROXY", "CONNECTABLE", "SLOTS", "MODE",
             "UPTIME", "ALL-DEVICE ok/fail"))
    for scanner in manager.get("scanners", []):
        source = scanner.get("source")
        alloc = allocations.get(source, {})
        slots = ("%s/%s free" % (alloc.get("free", "?"), alloc.get("slots", "?"))
                 if alloc else "n/a")
        mode = (scanner.get("current_mode") or {}).get("repr", "")
        mode = mode.split(".")[-1].split(":")[0] if mode else "?"
        # Counters are scanner-wide and reset on adapter restart, so print
        # uptime alongside them -- zeros on a freshly restarted adapter mean
        # "no data", not "never used".
        uptime = scanner.get("monotonic_time", 0) - scanner.get("start_time", 0)
        print("%-46s %-11s %-9s %-7s %-8s %s/%s"
              % (scanner.get("name", "?")[:45], scanner.get("connectable"),
                 slots, mode, "%.1fh" % (uptime / 3600),
                 scanner.get("connect_completed_total", 0),
                 scanner.get("connect_failed_total", 0)))


def cmd_routes(_args):
    manager = _bluetooth_diagnostics()
    beds = _bed_entries()
    if not beds:
        print("No %s config entries found." % DOMAIN)
        return

    allocations = manager.get("allocations") or {}
    scanners = manager.get("scanners", [])

    last_good_by_address = {}
    for entry in _entries():
        if entry.get("domain") == DOMAIN:
            data = entry.get("data") or {}
            addr = data.get("address") or data.get("mac")
            if addr:
                last_good_by_address[addr] = data.get("last_good_source")

    for title, address, state in beds:
        last_good = last_good_by_address.get(address)
        print("=" * 78)
        print("%s   [%s]" % (title, state))
        if not address:
            print("  (could not determine address from the config entry)")
            continue

        seen = []
        for scanner in scanners:
            for device in scanner.get("discovered_devices_and_advertisement_data") or []:
                if device.get("address") != address:
                    continue
                timestamps = scanner.get("discovered_device_timestamps") or {}
                now = scanner.get("monotonic_time")
                age = (round(now - timestamps[address], 1)
                       if now and address in timestamps else None)
                seen.append((scanner, device.get("rssi"), age))

        if not seen:
            print("  Not currently visible to any adapter or proxy.")
            print("  The base may be asleep or unplugged; press a button on the")
            print("  physical remote, or power-cycle it, then re-run.")
            continue

        seen.sort(key=lambda row: (row[1] is None, -(row[1] or 0)))
        if last_good:
            print("  last good route: %s" % last_good)
        print("  %-44s %-6s %-7s %-11s %s"
              % ("ADAPTER / PROXY", "RSSI", "AGE_s", "SLOTS", "FAILS(this bed)"))
        for index, (scanner, rssi, age) in enumerate(seen):
            source = scanner.get("source")
            alloc = allocations.get(source, {})
            slots = ("%s/%s" % (alloc.get("free", "?"), alloc.get("slots", "?"))
                     if alloc else "n/a")
            # NOTE: connect_completed_total / connect_failed_total are
            # scanner-wide across every device that adapter has talked to, and
            # reset when the adapter restarts. Only connect_failures is keyed by
            # address, so that is the only per-bed number shown here.
            failures = (scanner.get("connect_failures") or {}).get(address, 0)
            marker = "  <- strongest" if index == 0 else ""
            print("  %-44s %-6s %-7s %-11s %s%s"
                  % (scanner.get("name", "?")[:43], rssi,
                     age if age is not None else "?", slots, failures, marker))

        best = seen[0]
        if not best[0].get("connectable"):
            print("  ! The strongest adapter is not connectable (scan-only).")
            print("    Enable active connections on it to use it for control.")
        weak = [row for row in seen if row[1] is not None and row[1] < -85]
        if len(weak) == len(seen):
            print("  ! Every adapter hears this bed weakly (all below -85 dBm).")
            print("    Consider adding a Bluetooth proxy nearer the bed.")


def cmd_entries(_args):
    for title, address, state in _bed_entries():
        print("%-40s %-20s %s" % (title, address or "?", state))


COMMANDS = {"routes": cmd_routes, "adapters": cmd_adapters, "entries": cmd_entries}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=sorted(COMMANDS), nargs="?", default="routes")
    args = parser.parse_args()
    COMMANDS[args.action](args)


if __name__ == "__main__":
    main()
