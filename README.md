# Resident Bed

A Home Assistant custom integration for **Resident** adjustable bed bases
(OKIN-based controllers), driven over Bluetooth LE.

Bases advertise as `OKIN-<digits>`. Because OKIN builds the controller for
several rebadged bed brands, this may work beyond Resident-branded beds.

## Features

Exposes one button entity per bed command:

| Presets | Motors | Memory | Other |
|---|---|---|---|
| Flat, Zero Gravity, Reading, TV, Sleeping | Head Up/Down, Feet Up/Down, Head & Feet Up/Down | M1, M2 | LED |

## Installation (HACS)

1. HACS → three-dot menu → **Custom repositories**.
2. Add `https://github.com/tylerhartwig/ha-resident-bed`, category **Integration**.
3. Install **Resident Bed**, then restart Home Assistant.
4. The bed is discovered over Bluetooth. If it doesn't appear, add it from
   **Settings → Devices & Services → Add Integration → Resident Bed**.

During setup you'll be asked to power-cycle the base: unplug it, wait for the
light to go out, plug it back in, and continue once the light turns blue.

## Requirements

- Bluetooth reachability from Home Assistant — either a local adapter or an
  [ESPHome Bluetooth Proxy](https://esphome.io/projects/?type=bluetooth) within
  range of the bed.
- Home Assistant 2024.1 or newer.

## Options

Settings → Devices & Services → Resident Bed → **Configure**:

- **Keep the connection open** (default on) — holds the Bluetooth link so button
  presses are immediate instead of waiting to connect. Costs one connection slot
  on the adapter or proxy serving the bed (ESPHome proxies have 3 by default).
  Turn it off if slots are scarce.
- **Idle timeout** (default 90s) — when the above is off, how long to hold the
  connection after a press before dropping it.
- **Pair with the bed** (default off) — re-pair on the next connection. These
  bases generally only accept a new pairing for about 60 seconds after a fresh
  power-on, so unplug the bed, plug it back in, and enable this promptly. Only
  needed if the bed stopped accepting commands, or the adapter it paired with
  was replaced or reflashed.
- **Bluetooth adapter or proxy** (default automatic) — automatic keeps using
  whichever adapter last connected successfully, falling back to the strongest
  signal if that one cannot see the bed. Pin a specific one to override.

## Reliability

Connections use `bleak-retry-connector` with error-aware backoff, serialize
concurrent presses onto one connection, and reconnect automatically when the bed
reappears after being unplugged or out of range.

Crucially, the integration **sticks to the adapter or proxy that last worked**
rather than chasing signal strength. A BLE pairing bond is held against the
adapter that created it, so a bed paired via one proxy is rejected by every
other — and that rejection looks like a generic connection error. Following RSSI
across proxies is a common cause of intermittent bed control. The remembered
route is persisted, so a Home Assistant restart does not lose it. If presses are still slow or failing, the most common
cause is signal: no adapter or proxy is close enough to the bed. See
[tools/README.md](./tools/README.md) for `ha_diag.py`, which shows exactly which
adapters can hear the bed and how well.

## Status

Usable. There is no state feedback from the base — it does not report position,
so the buttons are write-only and stateless by design. See
[AGENT.md](./AGENT.md) §6 for the reliability design and §6b for what changed.

## Development

See [AGENT.md](./AGENT.md) for architecture and workflow, and
[tools/README.md](./tools/README.md) for the debugging scripts — including
`ble_probe.py`, which talks to the bed directly so protocol work doesn't require
a Home Assistant round-trip.

## Protocol notes

- Advertised service: `62741523-52f9-8864-b1ab-3b3a8d65950b`
- Control characteristic: `62741525-52f9-8864-b1ab-3b3a8d65950b` (write + notify)
- Commands are fixed-length hex bit-masks written with `response=True`; see
  [`bed_api/command.py`](./custom_components/resident_bed/bed_api/command.py).
