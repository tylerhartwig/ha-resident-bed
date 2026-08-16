# CLAUDE.md

**Read [AGENT.md](./AGENT.md) first and follow it.** It is the canonical guide
for this repo — architecture, the HACS development loop, secret-handling rules,
and the reliability design behind the BLE code. This file only adds Claude Code
specifics.

## Quick orientation

Home Assistant custom integration for OKIN-based Resident adjustable beds over
BLE. Ships via HACS to a **remote** HA instance — there is no local HA to run
against, and no SSH path to it.

Layering that matters: `bed_api/` is pure protocol and must never import Home
Assistant. That boundary is what lets `tests/` and `tools/ble_probe.py` exercise
the real connection code with no HA install.

## Tooling

Credentials come from `.env` (gitignored, already populated). These run on macOS
system `python3`:

| Need | Command |
|---|---|
| Integration logs | `python3 tools/ha_logs.py` |
| Tail while testing | `python3 tools/ha_logs.py --follow` |
| BLE stack errors | `python3 tools/ha_logs.py --filter bleak` |
| **Diagnose flaky connections** | `python3 tools/ha_diag.py routes` |
| List entities | `python3 tools/ha_api.py entities` |
| Fire a command | `python3 tools/ha_api.py press button.<id>` |
| Check HACS update mode | `python3 tools/ha_api.py state update.resident_bed_update` |

These need the venv (`bleak` requires Python 3.10+):

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check custom_components/ tools/
.venv/bin/python tools/ble_probe.py scan
```

## Working agreements

- **Verify, don't infer.** Everything asserted in AGENT.md was confirmed by
  reading live logs, running code, or reading library/HA source. Hold new claims
  to that bar, and say what you actually ran.
- **Two traps are documented in AGENT.md §6 — read it before touching BLE code.**
  `establish_connection`'s `ble_device_callback` parameter is a no-op, and
  `BluetoothServiceInfoBleak` is not in `helpers.service_info.bluetooth`.
- **Run the tests.** `tests/` is import-free of HA and covers the connection
  state machine. A BLE change that isn't provable there isn't finished.
- **HA-facing modules can't be imported locally.** Check symbols against
  `raw.githubusercontent.com/home-assistant/core/<version>/...` instead of
  assuming. Local `python3` is 3.9; use `/opt/homebrew/bin/python3.12` for
  anything touching `custom_components/`.
- **Don't restart Home Assistant without asking.** It runs a live household.
- **Never `git add -A`.** Stage named paths. See AGENT.md §1 and §4 — a sibling
  repo has a plaintext token in untracked files.
- **Keep it generic.** No addresses, adapter names, or deployment assumptions in
  the integration. Tunables belong in the options flow, not in constants.
- **`strings.json` / `translations/en.json` are generated from `BedCommand`.**
  Regenerate both together; `command.py` asserts every member has a label.
