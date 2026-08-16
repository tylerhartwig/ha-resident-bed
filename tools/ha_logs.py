#!/usr/bin/env python3
"""Fetch Home Assistant logs, filtered to this integration by default.

  python3 tools/ha_logs.py                    # recent resident_bed lines
  python3 tools/ha_logs.py --all              # no filter
  python3 tools/ha_logs.py --filter bleak     # anything BLE-related
  python3 tools/ha_logs.py --fetch 5000       # dig further back
  python3 tools/ha_logs.py --follow           # poll for new lines
  python3 tools/ha_logs.py --save             # also write logs/<timestamp>.log
  python3 tools/ha_logs.py --type supervisor  # supervisor / host logs

Uses the Supervisor proxy `/api/hassio/<type>/logs`, which is what works on
this instance -- core's `/api/error_log` was removed in recent HA versions
and is only tried as a fallback.

Nothing is printed unless `custom_components.resident_bed: debug` is set under
`logger:` in configuration.yaml. It already is, in ha-dev/home-assistant-config.
"""

import argparse
import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ha

DEFAULT_FILTER = "resident_bed"
LOG_DIR = os.path.join(_ha.REPO_ROOT, "logs")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def fetch(log_type, lines):
    """Return decolorized log text, falling back to the legacy endpoint."""
    try:
        text = _ha.request(
            "GET", "/api/hassio/%s/logs?lines=%d" % (log_type, lines)).text
    except SystemExit:
        if log_type != "core":
            raise
        text = _ha.request("GET", "/api/error_log").text
    return ANSI.sub("", text)


def select(text, needle, tail):
    lines = [line for line in text.splitlines() if line.strip()]
    if needle:
        lines = [line for line in lines if needle.lower() in line.lower()]
    return lines[-tail:] if tail > 0 else lines


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--filter", default=DEFAULT_FILTER,
                        help="case-insensitive substring (default: %s)" % DEFAULT_FILTER)
    parser.add_argument("--all", action="store_true", help="no filtering")
    parser.add_argument("--tail", type=int, default=200,
                        help="matching lines to show (0 = all)")
    parser.add_argument("--fetch", type=int, default=2000,
                        help="raw lines to pull from HA before filtering")
    parser.add_argument("--type", default="core",
                        choices=["core", "supervisor", "host", "dns", "audio", "multicast"])
    parser.add_argument("--follow", action="store_true", help="poll every --interval seconds")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--save", action="store_true", help="also write to logs/ (gitignored)")
    args = parser.parse_args()

    needle = None if args.all else args.filter
    lines = select(fetch(args.type, args.fetch), needle, args.tail)

    if lines:
        print("\n".join(lines))
    else:
        print("No lines matching %r in the last %d log lines.\n"
              "  * widen with --fetch 10000, or --all\n"
              "  * confirm debug logging is on in configuration.yaml:\n"
              "      logger:\n        logs:\n          custom_components.resident_bed: debug"
              % (needle, args.fetch))

    if args.save:
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(LOG_DIR, "%s-%s.log" % (stamp, needle or "all"))
        with open(dest, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        print("\n[saved] %s" % dest, file=sys.stderr)

    if not args.follow:
        return

    seen = set(lines)
    print("\n--- following (Ctrl-C to stop) ---", file=sys.stderr)
    try:
        while True:
            time.sleep(args.interval)
            for line in select(fetch(args.type, args.fetch), needle, 0):
                if line not in seen:
                    seen.add(line)
                    print(line)
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)


if __name__ == "__main__":
    main()
