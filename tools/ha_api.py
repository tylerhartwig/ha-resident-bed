#!/usr/bin/env python3
"""Talk to the live Home Assistant instance while testing the integration.

  python3 tools/ha_api.py entities                 # this integration's entities
  python3 tools/ha_api.py state button.bed_tv
  python3 tools/ha_api.py press button.bed_tv      # fire a bed command
  python3 tools/ha_api.py service homeassistant/reload_config_entry \
      --data '{"entity_id": "button.bed_tv"}'
  python3 tools/ha_api.py bluetooth                # BLE adapters / scanners
  python3 tools/ha_api.py restart                  # full HA restart (prompts)
  python3 tools/ha_api.py config
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ha

DOMAIN = "resident_bed"


def dump(payload):
    print(json.dumps(payload, indent=2, sort_keys=True))


def all_states():
    return _ha.request("GET", "/api/states").json()


def cmd_entities(args):
    """Best-effort: match entities whose id or friendly name looks like the bed."""
    needle = (args.match or "bed").lower()
    hits = [
        state for state in all_states()
        if needle in state["entity_id"].lower()
        or needle in str(state.get("attributes", {}).get("friendly_name", "")).lower()
    ]
    if not hits:
        print("No entities matching %r.\n"
              "The integration may not be loaded -- check: "
              "python3 tools/ha_logs.py" % needle)
        return
    for state in sorted(hits, key=lambda s: s["entity_id"]):
        print("%-45s %-22s %s" % (
            state["entity_id"],
            state["state"],
            state.get("attributes", {}).get("friendly_name", ""),
        ))


def cmd_state(args):
    if not args.param:
        sys.exit("usage: ha_api.py state <entity_id>")
    dump(_ha.request("GET", "/api/states/" + args.param).json())


def cmd_press(args):
    if not args.param:
        sys.exit("usage: ha_api.py press <entity_id>")
    dump(_ha.request("POST", "/api/services/button/press",
                     {"entity_id": args.param}).json())


def cmd_service(args):
    if not args.param or "/" not in args.param:
        sys.exit("usage: ha_api.py service <domain>/<service> [--data JSON]")
    domain, service = args.param.split("/", 1)
    body = json.loads(args.data) if args.data else {}
    dump(_ha.request("POST", "/api/services/%s/%s" % (domain, service), body).json())


def cmd_bluetooth(args):
    hits = [s for s in all_states() if "bluetooth" in s["entity_id"].lower()]
    if not hits:
        print("No bluetooth entities exposed. Check Settings -> Devices & "
              "Services -> Bluetooth for adapter/proxy health.")
    for state in hits:
        dump(state)


def cmd_config(args):
    dump(_ha.request("GET", "/api/config").json())


def cmd_restart(args):
    if not args.yes:
        answer = input("Restart Home Assistant at %s? [y/N] "
                       % _ha.config()[0]).strip().lower()
        if answer != "y":
            sys.exit("aborted")
    _ha.request("POST", "/api/services/homeassistant/restart", {})
    print("Restart requested. Watch it come back with:\n"
          "  python3 tools/ha_logs.py --follow")


COMMANDS = {
    "entities": cmd_entities,
    "state": cmd_state,
    "press": cmd_press,
    "service": cmd_service,
    "bluetooth": cmd_bluetooth,
    "config": cmd_config,
    "restart": cmd_restart,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=sorted(COMMANDS))
    parser.add_argument("param", nargs="?")
    parser.add_argument("--data", help="JSON body for `service`")
    parser.add_argument("--match", help="substring for `entities` (default: bed)")
    parser.add_argument("--yes", action="store_true", help="skip the restart prompt")
    args = parser.parse_args()
    COMMANDS[args.action](args)


if __name__ == "__main__":
    main()
