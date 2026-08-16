# Resident Bed — Agent Guide

Home Assistant custom integration for OKIN-controlled Resident adjustable bed
bases, driven over BLE GATT. Distributed through HACS.

This file is the canonical instruction set for all agents. `CLAUDE.md` and any
future `GEMINI.md` point here — put durable knowledge in this file, not in those.

---

## 1. Hard rules

1. **Never commit secrets.** `HA_URL` / `HA_TOKEN` live only in `.env`, which is
   gitignored. No token, no long-lived access token, and no bed MAC address may
   appear in a tracked file — including in docs, examples, or comments. Before
   any commit, run `git status` and confirm nothing under §4 is staged.
2. **Never `git add -A` / `git add .`** in this repo or its siblings. Stage
   named paths. (`../adaptive-lighting/` currently holds a plaintext HA token in
   untracked `fetch_*.py` scripts — a blanket add there would publish it.)
3. **Verify against the live instance before claiming a fix works.** This
   integration's failures are almost entirely runtime BLE failures that no
   static reading will reveal. Pressing a button and reading the log is the
   test. See §5.
4. **Don't guess at BLE behavior.** Confirm command bytes with
   `tools/ble_probe.py` against the physical bed before changing `bed_api/`.
5. **Ask before restarting Home Assistant.** It is a live household system
   running lights, alarms, and cameras. `tools/ha_api.py restart` prompts by
   design; don't pass `--yes` unprompted.

---

## 2. How the pieces fit

```
custom_components/resident_bed/
├── __init__.py        entry setup; forwards to the button platform
├── config_flow.py     BLE-discovery + manual flow; pairs and creates the entry
├── base.py            ResidentBedEntity — shared entity base
├── button.py          one button entity per BedCommand; owns connection caching
├── const.py           DOMAIN
├── manifest.json      HACS/hassfest metadata; BLE discovery service_uuid
├── strings.json       config-flow copy + entity names
├── translations/en.json   must be kept in sync with strings.json
└── bed_api/
    ├── command.py     BedCommand enum: name -> hex payload; GATT handles
    └── resident_bed.py  ResidentBed: characteristic discovery + send_command
```

**Layering rule:** `bed_api/` is pure protocol and must not import Home
Assistant. Everything HA-aware lives one level up. This is what makes
`tools/ble_probe.py` able to exercise the protocol with no HA in the loop —
preserve it.

### BLE facts

- Service UUID `62741523-52f9-8864-b1ab-3b3a8d65950b` (advertised; drives
  discovery via `manifest.json`).
- Control characteristic `62741525-52f9-8864-b1ab-3b3a8d65950b` — both `write`
  and `notify`. Commands are written with `response=True`.
- Advertised device name is `OKIN-<digits>`. OKIN makes the actuator; several
  bed brands rebadge it, so this integration likely works beyond "Resident".
- Payloads are fixed-length hex bit-masks; a byte position selects the motor or
  preset. Most are 14 bytes, but `HeadFeetUp`/`HeadFeetDown` are 10 — the
  protocol is not uniform, so don't assume a single frame layout.

### Deployment topology (important)

- Home Assistant is **remote** (URL in `.env` as `HA_URL`; currently 2026.8.0
  on Python 3.14). Local `ls /config` tells you nothing about it.
- The integration is delivered **via HACS**, installed to
  `/config/custom_components/resident_bed`. There is no SSH/rsync path.
- BLE does **not** go through a local adapter on the HA host. It is proxied
  through an **ESPHome Bluetooth Proxy** (`bleak_esphome` in every traceback).
  This shapes the failure modes — see §6.
- Debug logging is already enabled in the HA config repo
  (`../ha-dev/home-assistant-config/configuration.yaml`):
  `logger: logs: custom_components.resident_bed: debug`.

---

## 3. The development loop

Connection/protocol work — fast, no HA, iterate freely:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv          # once; bleak needs 3.10+
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q                # connection state machine
.venv/bin/ruff check custom_components/ tools/
.venv/bin/python tools/ble_probe.py scan            # find the base
.venv/bin/python tools/ble_probe.py dump            # GATT table
.venv/bin/python tools/ble_probe.py drive TV        # via the real manager
```

`tests/` covers `bed_api/` only — that layer has no Home Assistant imports, so
the suite runs against plain bleak with no HA install. It mocks
`establish_connection` and asserts on route re-resolution, lock serialization,
write retry, idle disconnect, and reconnect-on-advertisement. Prove any change
to the connection state machine there before it reaches the bed.

The HA-facing modules cannot be imported locally (no HA install, and HA needs
Python 3.13+). Verify symbols against the real source instead:

```bash
curl -s https://raw.githubusercontent.com/home-assistant/core/<version>/homeassistant/components/bluetooth/__init__.py | grep -n '__all__' -A40
```

That check is not optional: `BluetoothServiceInfoBleak` is re-exported from
`homeassistant.components.bluetooth`, **not** from
`homeassistant.helpers.service_info.bluetooth` (which only defines
`BluetoothServiceInfo`). Importing the wrong one fails at load time.

Integration work — the slow loop, because HACS is the only delivery path:

```bash
git commit -am "..." && git push
.venv/bin/python tools/hacs_deploy.py refresh   # force HACS to re-read the repo
.venv/bin/python tools/hacs_deploy.py install
python3 tools/ha_api.py restart                     # ask the user first
python3 tools/ha_api.py entities                    # confirm entities came back
python3 tools/ha_api.py press button.<...>          # exercise it
python3 tools/ha_logs.py --follow                   # watch what happened
```

**HACS may not notice pushes on its own.** `startup_tasks` aborts on the first
exception, and everything after the failure point is skipped — including
`set_stage(HacsStage.RUNNING)` and the initial repository refresh. On this
install it was aborting with `ValueError: The repo id for <repo> is already set
to <id>` (a duplicate repository ID in HACS's stored data, unrelated to this
integration), leaving HACS stuck in the `startup` stage and silently not
detecting updates for *any* repository. Check with:

```bash
.venv/bin/python tools/hacs_deploy.py status    # want stage: running
```

`tools/hacs_deploy.py` drives the same websocket commands the HACS frontend
uses (`hacs/repository/refresh`, `hacs/repository/download`), so it works even
when the update entity is stale. It is a workaround, not a fix — the duplicate
repository ID still needs clearing in the HACS UI.

Custom-integration code changes require a **full Home Assistant restart**;
reloading the config entry re-runs setup against already-imported modules.

**This repo has no git releases, so HACS tracks the default branch by commit
SHA** — `update.resident_bed_update` currently reports `installed_version` as a
short SHA, not `0.1.0`. A plain push to `main` is therefore enough to surface an
update; you do *not* need to bump `manifest.json`. That changes the moment you
publish a GitHub release: HACS switches to release mode and will then ignore
untagged commits. If you start tagging, use `tools/bump_version.py` and keep the
manifest version and the tag in step.

Confirm which mode is live before trusting either path:

```bash
python3 tools/ha_api.py state update.resident_bed_update
```

A short hex `installed_version` means commit-tracking mode; a semver means
release mode.

---

## 4. What must never be committed

`.gitignore` covers all of this; the list is here so it is reviewable.

- `.env`, any `.env.*` except `.env.example`, `secrets.yaml`, `*.token`, keys.
- `logs/`, `diagnostics/`, `*.log`, BLE captures (`*.pcap`, `*.btsnoop`) —
  HA logs contain entity names, MACs, and household detail.
- Ad-hoc debug scripts: `fetch_*.py`, `reload_ha.py`, `set_*.py`,
  `turn_on_*.py`, and anything in `scratch/`. These are exactly the files that
  accumulate hardcoded tokens.
- `.venv/`, `__pycache__/`, `.idea/`, `.DS_Store`.

Bed MAC addresses are treated as sensitive here: they go in `.env` as
`BED_ADDRESS`, never in tracked files.

---

## 5. Getting logs and state

All tools read `.env` and are documented in `tools/README.md`.

```bash
python3 tools/ha_logs.py                     # recent resident_bed lines
python3 tools/ha_logs.py --filter bleak      # BLE stack errors
python3 tools/ha_logs.py --fetch 20000       # dig further back
python3 tools/ha_logs.py --follow            # tail while you press buttons
python3 tools/ha_logs.py --save              # snapshot to logs/ (gitignored)
python3 tools/ha_api.py entities             # what the integration exposes
python3 tools/ha_api.py press button.<id>    # trigger a command
```

`/api/error_log` was removed in recent Home Assistant versions and 404s on this
instance. `ha_logs.py` uses the Supervisor proxy `/api/hassio/core/logs?lines=N`
and only falls back to the old endpoint. Output is ANSI-colored; the tool strips
that. The endpoint returns a bounded journal buffer, so raise `--fetch` rather
than assuming an absent line means the code never ran.

---

## 6. Reliability design (why the BLE code looks the way it does)

Symptoms this addresses: the first press after idle taking many seconds, and
presses sometimes doing nothing at all.

Root causes, all verified from live logs and library source:

1. **No retry layer.** The old code called `BleakClient.connect()` directly, so
   a single `[Errno 104] Connection reset by peer` lost the press. Home
   Assistant logged a warning about this on every connect.
2. **A cached client pinned every attempt to one route.** A `BLEDevice` carries
   the route to a *specific* adapter or proxy. Reusing one means every retry
   goes back to the same place, even when a nearer adapter is idle.
3. **Connect-on-demand.** Every first press paid connect + GATT discovery.
4. **No lock.** Concurrent presses each opened a client and consumed a
   connection slot.
5. **Swallowed exceptions.** `get_resident_bed()` caught, logged, then returned
   `None`, and the caller immediately did `await bed.send_command(...)` --
   an `AttributeError` on `None`, presented to the user as silence.

The current design, in `bed_api/resident_bed.py`:

- `bleak_retry_connector.establish_connection()` with error-aware backoff.
- The `BLEDevice` is **re-resolved before every connection round**, so each
  round may take a different route. `CONNECT_ROUNDS` rounds x
  `ATTEMPTS_PER_ROUND` attempts, under a `CONNECT_TOTAL_TIMEOUT` ceiling so a
  press can never hang indefinitely.
- One `asyncio.Lock` serializes connect and write.
- `close_stale_connections_by_address()` before connecting, clearing half-open
  links that otherwise look like an unreachable device.
- Optional persistent connection (`always_connected`, default on) with
  exponential-backoff reconnect, plus reconnect-on-advertisement so a bed that
  was unplugged recovers the moment it is seen again rather than being polled.
- Errors surface as `HomeAssistantError` with Home Assistant's own
  `async_address_reachability_diagnostics()` explanation attached.

### Pairing pins a bed to one route — affinity is the default

A BLE bond is established between the peripheral and the **central's identity
address**. With Bluetooth proxies, each proxy is its own central with its own
BD_ADDR, so a bond created through proxy A is rejected by proxy B — and the
rejection is a *link termination*, not an authentication error. It surfaces as
`[Errno 104] Connection reset by peer` or `Not connected`, indistinguishable
from ordinary transport flakiness. Peripherals also have very few bond slots, so
repeatedly pairing from several proxies can evict earlier bonds.

These bases pair explicitly and only accept a new bond for roughly **60 seconds
after a fresh power-on**, which is why the config flow's recovery step tells the
user to power-cycle and then attempts `pair=True` on the retry.

Consequently `_device_for_round()` treats route affinity as the default, not an
optimization:

1. An explicit `preferred_source` pin — honoured every round.
2. The last route that connected — tried first, and **persisted to the config
   entry** (`last_good_source`) so a restart does not lose bond affinity.
3. Best current signal — for the first ever connection, and as fallback once the
   remembered route has failed a round (a proxy can be moved or reflashed).

**Do not "optimize" this into following RSSI.** Chasing signal across proxies is
what makes a paired base intermittent: it works when the manager happens to pick
the bonded proxy and fails when it does not.

### Determining whether a base actually bonds — carefully

Absence of `Insufficient Authentication` / `GATT_INSUF_*` in the logs does
**not** prove a base is unbonded. That error only appears when a connection is
established and then a protected characteristic is accessed. A base that refuses
to *connect* to an unbonded central produces link-termination errors instead.
An earlier analysis of this repo drew the wrong conclusion from exactly that gap.

Similarly, do not read the Bluetooth diagnostics counters naively:

- `connect_completed_total` / `connect_failed_total` are **scanner-wide across
  every device**, not per-bed, and they **reset when that adapter restarts**.
  Zeros on a freshly restarted proxy mean "no data", not "never used".
- Only `connect_failures` is keyed by address. It is the sole per-bed number.

`tools/ha_diag.py` reflects this: `routes` shows per-bed failures only, and
`adapters` prints uptime beside the scanner-wide counters.

The reliable signal is *correlation between route and outcome*: per-bed failures
concentrated on adapters other than the bonded one. Get that from
`tools/ha_diag.py routes`, and confirm which route is in use by enabling debug
logging for the proxy backend:

```bash
python3 tools/ha_api.py service logger/set_level \
  --data '{"bleak_esphome": "debug", "habluetooth": "debug"}'
python3 tools/ha_logs.py --filter <bed-address> --follow
```

### A trap: `ble_device_callback` is a no-op

`establish_connection()` accepts a `ble_device_callback` parameter, and its name
strongly implies it re-resolves the device between retries. **It does not.** In
bleak-retry-connector 4.6.3 the identifier appears exactly once in the entire
module -- in the function signature. The client is constructed once, before the
retry loop, from the `device` argument.

```python
# Verify before relying on it:
.venv/bin/python -c "import inspect,bleak_retry_connector as b; \
    print(inspect.getsource(b.establish_connection).count('ble_device_callback'))"
```

That is why the round loop lives in `_connect_rounds()` rather than being
delegated to the library. If a future version implements the parameter, the
outer loop can be simplified.

### Tuning

Nothing is tuned to a particular deployment. Behaviour is per-bed configurable
via the options flow (Settings -> Devices & Services -> Resident Bed ->
Configure):

- **Keep the connection open** (`always_connected`, default on) -- removes
  connect latency, costs one connection slot on whichever adapter or proxy
  serves that bed. ESPHome proxies default to 3 slots each. Turn it off if
  slots are scarce.
- **Idle timeout** (`keepalive`, default 90s) -- only used when the above is
  off; how long to hold the link after a press.

### Diagnosing a specific install

Home Assistant already knows which adapters see a device and how well. Rather
than guessing, read it:

```bash
python3 tools/ha_diag.py routes     # per-adapter RSSI + slots for each bed
python3 tools/ha_diag.py adapters   # adapter/proxy inventory
```

`tools/ha_diag.py` reports, for every configured bed, which adapters/proxies can
see it, at what RSSI, how many connection slots each has free, and each
adapter's connect success/failure counts. A bed being served by a weak adapter
while a strong one sits unused is the classic cause of flaky connections, and
this is how you see it.

## 6b. Fixed in 0.2.0 (do not "re-fix")

- `BedCommand.name` no longer shadows the Enum attribute; use
  `command.display_name` for labels. Translation keys are `command.name.lower()`.
- Buttons are real `ButtonEntity` subclasses, so state and last-pressed work.
  (Presses previously worked only because the `button.press` service is
  registered by *method name* and the class happened to define
  `_async_press_action`.)
- Existing entities are preserved: `__init__.py` rewrites legacy unique_ids
  that embedded a bound-method repr. Do not change `_LEGACY_UNIQUE_ID_RE`
  without considering installs that have not yet started once.
- Config entries migrated v1 -> v2 (`mac` -> `address`).
- `async_unload_entry` exists and tears the BLE link down.
- `strings.json` / `translations/en.json` are generated from `BedCommand`, and
  `command.py` asserts at import time that every member has a label.
- `manifest.json` declares `bluetooth_adapters`, `iot_class`, `documentation`,
  `issue_tracker`, `codeowners`, and no longer requires the unused `result`.
- The config flow no longer crashes when started manually: it lists beds
  currently advertising instead of dereferencing a `None` discovery info.

## 7. Related repositories

- `../ha-dev/` — HA config, deployment mandates, and the `ha-dev-toolkit` skill.
  Its `AGENT.md` governs config/automation work; **this** file governs
  integration code. Its toolkit scripts read credentials from
  `.gemini/settings.json`, which does not exist locally — prefer the `.env`-based
  tools here.
- `../ha-dev/home-assistant-config/` — live HA config (a git submodule). Note it
  gitignores `custom_components/`, since those are managed through the HACS UI.
- `../adaptive-lighting/` — a fork being modified in parallel. Contains
  untracked scripts with a plaintext HA token; do not stage them.
