# Dev tools

Small, dependency-light scripts for testing this integration against the live
Home Assistant instance and against the bed itself. See `../AGENT.md` for the
full workflow.

## Setup

```bash
cp ../.env.example ../.env     # then fill in HA_URL / HA_TOKEN
```

`.env` is gitignored. Every script reads it via `_ha.py`; none of them print the
token. Real environment variables win over `.env` values.

`ha_logs.py`, `ha_api.py`, and `bump_version.py` run on macOS system `python3`
(3.9) and need only `requests`. `ble_probe.py` needs `bleak`, which needs
Python 3.10+:

```bash
/opt/homebrew/bin/python3.12 -m venv ../.venv
../.venv/bin/pip install -r ../requirements-dev.txt
```

## `ha_logs.py` — read the remote log

```bash
python3 tools/ha_logs.py                    # recent resident_bed lines
python3 tools/ha_logs.py --all --tail 50    # unfiltered
python3 tools/ha_logs.py --filter bleak     # BLE stack errors
python3 tools/ha_logs.py --fetch 20000      # pull more raw log before filtering
python3 tools/ha_logs.py --follow           # poll for new lines while testing
python3 tools/ha_logs.py --save             # snapshot into logs/ (gitignored)
python3 tools/ha_logs.py --type supervisor  # supervisor / host / dns / audio
```

Uses `/api/hassio/<type>/logs?lines=N` (the Supervisor proxy) and strips ANSI
color. Core's `/api/error_log` 404s on modern HA and is only a fallback. The
endpoint serves a bounded buffer — if a line seems missing, raise `--fetch`
before concluding the code didn't run.

## `ha_api.py` — poke the running instance

```bash
python3 tools/ha_api.py entities                    # bed entities and states
python3 tools/ha_api.py entities --match resident
python3 tools/ha_api.py state button.tyler_s_bed_tv
python3 tools/ha_api.py press button.tyler_s_bed_tv # send a bed command
python3 tools/ha_api.py service homeassistant/reload_config_entry \
    --data '{"entity_id": "button.tyler_s_bed_tv"}'
python3 tools/ha_api.py bluetooth                   # BLE adapter / proxy state
python3 tools/ha_api.py config
python3 tools/ha_api.py restart                     # prompts before restarting
```

## `ha_diag.py` — why is the connection flaky?

The usual cause is routing: the bed is served by an adapter or proxy that barely
hears it while a closer one sits idle, or the serving adapter is out of
connection slots. Home Assistant tracks all of that; this surfaces it.

```bash
python3 tools/ha_diag.py routes     # per-adapter RSSI, age, slots, failures per bed
python3 tools/ha_diag.py adapters   # adapter/proxy inventory
python3 tools/ha_diag.py entries    # configured beds
```

`routes` marks the strongest adapter for each bed, and warns when the strongest
is scan-only or when every adapter hears the bed below -85 dBm (add a proxy
nearer the bed). Beds and adapters are read from the running instance — nothing
is hardcoded.

## `ble_probe.py` — talk to the bed directly

No Home Assistant involved. This is the fast path for protocol work.

```bash
.venv/bin/python tools/ble_probe.py scan            # find the base
.venv/bin/python tools/ble_probe.py dump            # full GATT table
.venv/bin/python tools/ble_probe.py list            # known commands
.venv/bin/python tools/ble_probe.py send TV         # raw write
.venv/bin/python tools/ble_probe.py drive TV       # via the real connection manager
.venv/bin/python tools/ble_probe.py send-raw 0c02000040000000000000000000
.venv/bin/python tools/ble_probe.py listen --seconds 30
```

Set `BED_ADDRESS` in `.env` after scanning, or pass `--address`.

**macOS caveat:** CoreBluetooth reports an opaque per-host UUID, not a MAC. The
address that works here is *not* the address Home Assistant uses (HA reaches the
bed through an ESPHome Bluetooth proxy, which sees the real MAC). Don't copy one
into the other.

The bed only advertises while awake — if a scan comes up empty, press a button on
the physical remote or power-cycle the base, then retry.

## `bump_version.py` — cut a HACS release

```bash
python3 tools/bump_version.py            # 0.1.0 -> 0.1.1
python3 tools/bump_version.py --minor
python3 tools/bump_version.py --set 1.0.0
```

**Only needed if you tag GitHub releases.** This repo currently has none, so
HACS tracks the default branch by commit SHA and a plain `git push` already
offers an update. Check which mode is live with:

```bash
python3 tools/ha_api.py state update.resident_bed_update
```

A short hex `installed_version` means commit-tracking; a semver means HACS has
switched to release mode, and from then on only tagged commits are offered.
