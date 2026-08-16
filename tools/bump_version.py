#!/usr/bin/env python3
"""Bump the integration version in manifest.json.

Only needed if you publish GitHub releases. This repo currently has none, so
HACS tracks the default branch by commit SHA and a plain `git push` already
offers an update -- verify with:
    python3 tools/ha_api.py state update.resident_bed_update
A short hex installed_version means commit-tracking mode; a semver means HACS
has switched to release mode, where only tagged commits are offered.

  python3 tools/bump_version.py            # patch: 0.1.0 -> 0.1.1
  python3 tools/bump_version.py --minor
  python3 tools/bump_version.py --set 1.0.0
"""

import argparse
import json
import os
import re
import sys

MANIFEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components", "resident_bed", "manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--minor", action="store_true")
    group.add_argument("--major", action="store_true")
    group.add_argument("--set", dest="explicit")
    args = parser.parse_args()

    with open(MANIFEST) as handle:
        manifest = json.load(handle)

    current = manifest.get("version", "0.0.0")
    if args.explicit:
        new = args.explicit
    else:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", current)
        if not match:
            sys.exit("version %r is not semver; use --set" % current)
        major, minor, patch = (int(g) for g in match.groups())
        if args.major:
            major, minor, patch = major + 1, 0, 0
        elif args.minor:
            minor, patch = minor + 1, 0
        else:
            patch += 1
        new = "%d.%d.%d" % (major, minor, patch)

    manifest["version"] = new
    with open(MANIFEST, "w") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    print("%s -> %s" % (current, new))
    print("Next:\n"
          "  git commit -am 'Release %s' && git tag v%s && git push --tags\n"
          "  HACS -> Resident Bed -> Redownload -> restart Home Assistant"
          % (new, new))


if __name__ == "__main__":
    main()
