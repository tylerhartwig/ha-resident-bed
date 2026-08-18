"""Connection management for a single Resident/OKIN bed base.

Pure protocol -- this module must not import Home Assistant. The caller supplies
`ble_device_callback`, which returns the currently-best BLEDevice for this
address (or None if it is not visible). Keeping HA out of here lets
tools/ble_probe.py drive the same code path.

Reliability design, in order of impact:

1. `bleak_retry_connector.establish_connection` replaces `BleakClient.connect`.
   It retries with error-aware backoff and classifies transient vs. fatal
   failures, so one dropped connect no longer loses the button press.

2. The BLEDevice is re-resolved before every connection round. This matters on
   multi-adapter / Bluetooth-proxy setups: the device object carries the route
   to a specific adapter or proxy, so a cached one pins every retry to whatever
   answered first -- possibly a distant one -- while a nearer adapter sits idle.
   NOTE: establish_connection() accepts a `ble_device_callback` parameter, but
   as of bleak-retry-connector 4.6.3 it is never invoked (the parameter appears
   exactly once in the module: in the signature). Re-resolution is therefore
   done here, in the outer loop, rather than delegated to the library.

3. One asyncio.Lock serializes connect and write, so simultaneous presses share
   a connection instead of each opening a client and consuming a slot.

4. Optionally hold the connection open, with backoff reconnect and
   reconnect-on-advertisement, so a press never waits for connect + GATT
   discovery.

Nothing here is specific to any particular deployment: adapter counts, proxy
names, and addresses are all supplied by the caller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    close_stale_connections_by_address,
    establish_connection,
)

from .command import CONTROL_UUID, BedCommand

_LOGGER = logging.getLogger(__name__)

# Hold an idle connection this long before dropping it (on-demand mode only).
DEFAULT_KEEPALIVE = 90.0

# Reconnect backoff bounds for always-connected mode.
RECONNECT_MIN_DELAY = 5.0
RECONNECT_MAX_DELAY = 300.0

# Connection rounds. Each round re-resolves the BLEDevice, so each one may take
# a different route to the bed.
#
# The arithmetic here has to hold together: bleak-retry-connector uses a 20s
# per-attempt timeout, so N attempts per round can want N*20s. With 2 attempts
# and a 45s overall ceiling, round 1 alone consumed the whole budget and rounds
# 2 and 3 never ran -- the ceiling silently defeated the retry design. Keep one
# attempt per round (we retry at the round level, where the route can actually
# change) and give each round its own timeout that fits inside the total.
CONNECT_ROUNDS = 2
ATTEMPTS_PER_ROUND = 1
CONNECT_ROUND_TIMEOUT = 22.0

# Hard ceiling so a button press can never hang indefinitely.
CONNECT_TOTAL_TIMEOUT = 50.0


class ResidentBedError(Exception):
    """Base error for bed operations."""


class ResidentBedNotFound(ResidentBedError):
    """The bed is not visible to any connectable adapter or proxy."""


class ResidentBed:
    """Owns the BLE connection to one bed base and writes commands to it."""

    def __init__(
        self,
        address: str,
        name: str,
        ble_device_callback: Callable[[], BLEDevice | None],
        keepalive: float = DEFAULT_KEEPALIVE,
        always_connected: bool = True,
        pair: bool = False,
        preferred_source: str | None = None,
        ble_device_by_source_callback: Callable[[str], BLEDevice | None] | None = None,
        last_good_source: str | None = None,
        on_route_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.address = address
        self.name = name
        self._ble_device_callback = ble_device_callback
        self._by_source = ble_device_by_source_callback
        self._keepalive = keepalive
        self._always_connected = always_connected
        self._pair = pair
        self._preferred_source = preferred_source or None
        self._last_good_route: str | None = last_good_source or None
        self._on_route_changed = on_route_changed

        self._client: BleakClient | None = None
        self._control_char = None
        self._lock = asyncio.Lock()
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._disconnect_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_delay = RECONNECT_MIN_DELAY
        self._shutdown = False
        self._state_callbacks: list[Callable[[], None]] = []

        # Surfaced by the HA layer as diagnostic attributes.
        self.last_error: str | None = None
        self.last_connected_at: float | None = None
        self.last_route: str | None = None

    # -- state -------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def always_connected(self) -> bool:
        """Whether the link is held open rather than opened on demand."""
        return self._always_connected

    @property
    def available(self) -> bool:
        """Whether a command has a realistic chance of succeeding.

        Deliberately not the same as `is_connected`: in on-demand mode the bed
        is usually disconnected yet perfectly usable, so availability tracks
        whether anything can currently see it.
        """
        return self.is_connected or self._ble_device_callback() is not None

    def register_state_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe to connection-state changes. Returns an unsubscribe callable."""
        self._state_callbacks.append(callback)

        def _unsubscribe() -> None:
            if callback in self._state_callbacks:
                self._state_callbacks.remove(callback)

        return _unsubscribe

    def _notify_state(self) -> None:
        for callback in list(self._state_callbacks):
            try:
                callback()
            except Exception:
                _LOGGER.exception("%s: state callback failed", self.name)

    # -- connection --------------------------------------------------------

    async def async_connect(self) -> None:
        """Connect if not already connected. Safe to call repeatedly.

        Also arms the idle timer: a connection opened without a command (the
        startup cache warm-up) would otherwise hold a slot indefinitely, since
        only async_send_command used to schedule the disconnect.
        """
        async with self._lock:
            await self._connect_locked()
        self._schedule_disconnect()

    async def _connect_locked(self) -> BleakClient:
        """Connect, re-resolving the route on each round. Caller must hold the lock."""
        if self._client is not None and self._client.is_connected:
            return self._client

        try:
            async with asyncio.timeout(CONNECT_TOTAL_TIMEOUT):
                client = await self._connect_rounds()
        except TimeoutError as err:
            self.last_error = f"connect timed out after {CONNECT_TOTAL_TIMEOUT:.0f}s"
            _LOGGER.debug("%s: %s", self.name, self.last_error)
            raise ResidentBedError(f"{self.name}: {self.last_error}") from err

        self._client = client
        self.last_error = None
        self.last_connected_at = time.time()
        self._reconnect_delay = RECONNECT_MIN_DELAY

        # Resolve the *writable* control characteristic explicitly. These bases
        # expose more than one characteristic under CONTROL_UUID -- a notify one
        # and a write one -- and bleak's UUID lookup returns whichever comes
        # first, which may be the notify one. Writes to that are accepted at the
        # transport level and silently do nothing.
        self._control_char = _find_writable(client, CONTROL_UUID)
        if self._control_char is None:
            await self._disconnect_client(client)
            self._client = None
            self.last_error = "no writable control characteristic"
            raise ResidentBedError(
                f"{self.name}: no writable characteristic {CONTROL_UUID} found; "
                "this may not be an OKIN-compatible base"
            )

        _LOGGER.info(
            "%s: connected via %s, control handle=%s props=%s",
            self.name, self.last_route, self._control_char.handle,
            ",".join(self._control_char.properties),
        )
        self._notify_state()
        return client

    async def _connect_rounds(self) -> BleakClient:
        last_error: Exception | None = None

        for round_number in range(1, CONNECT_ROUNDS + 1):
            device = self._device_for_round(round_number)
            if device is None:
                if last_error is None:
                    self.last_error = "not visible to any connectable adapter or proxy"
                    raise ResidentBedNotFound(
                        f"{self.name} ({self.address}) is not visible to any "
                        "connectable Bluetooth adapter or proxy"
                    )
                break

            route = _route_of(device)
            _LOGGER.debug(
                "%s: connect round %s/%s via %s",
                self.name, round_number, CONNECT_ROUNDS, route,
            )

            # Clear any half-open link left on another adapter, which otherwise
            # presents as the device being unreachable.
            try:
                await close_stale_connections_by_address(self.address)
            except Exception as err:  # noqa: BLE001 - best effort only
                _LOGGER.debug("%s: stale-connection cleanup skipped: %s", self.name, err)

            try:
                async with asyncio.timeout(CONNECT_ROUND_TIMEOUT):
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        device,
                        self.name,
                        disconnected_callback=self._on_disconnect,
                        max_attempts=ATTEMPTS_PER_ROUND,
                        use_services_cache=True,
                        # Pairing is attempted separately below so that a
                        # pairing failure cannot fail an otherwise good link.
                        pair=False,
                    )
            except (BleakError, TimeoutError, OSError) as err:
                last_error = err
                self.last_error = str(err)
                _LOGGER.debug(
                    "%s: round %s/%s via %s failed after %.0fs budget: %s",
                    self.name, round_number, CONNECT_ROUNDS, route,
                    CONNECT_ROUND_TIMEOUT, err,
                )
                # Give the next round a chance to see a fresher/nearer route.
                await asyncio.sleep(0.5)
                continue

            if self._pair:
                await self._try_pair(client)

            self.last_route = route
            if route != self._last_good_route:
                self._last_good_route = route
                if self._on_route_changed is not None:
                    self._on_route_changed(route)
            return client

        if isinstance(last_error, BleakNotFoundError):
            raise ResidentBedNotFound(str(last_error)) from last_error
        raise ResidentBedError(
            f"Failed to connect to {self.name} after {CONNECT_ROUNDS} rounds: "
            f"{last_error}"
        ) from last_error

    async def _try_pair(self, client: BleakClient) -> None:
        """Attempt to bond, but never fail the connection over it.

        Bonds persist on the adapter, so once a base is paired every later
        connection works without pairing again. Re-pairing an already-bonded
        base is usually a no-op and is frequently refused outright -- these
        bases only accept a new bond for a short window after power-on. Letting
        that refusal fail the connection would break a link that works fine.
        """
        try:
            await client.pair()
            _LOGGER.info("%s: paired", self.name)
        except NotImplementedError:
            _LOGGER.warning(
                "%s: this adapter's firmware does not support pairing; "
                "if the bed refuses commands, pair it via a different adapter",
                self.name,
            )
        except Exception as err:  # noqa: BLE001 - pairing is best effort
            _LOGGER.debug(
                "%s: pairing not completed (%s); continuing with the existing "
                "bond", self.name, err,
            )

    def _device_for_round(self, round_number: int) -> BLEDevice | None:
        """Choose which route to attempt this round.

        Route affinity is the default, not an optimization. If a base is paired,
        the bond is held against the *central's* identity address, and every
        adapter or proxy is a separate central -- so a bond created through one
        is rejected by every other, usually as a link termination rather than an
        authentication error. Chasing signal strength across routes therefore
        breaks paired bases and looks exactly like flaky Bluetooth.

        1. An explicit pin, if set: honoured on every round. It is deliberate
           user intent, and for a bonded base no other route would work anyway.
        2. The route that last connected, on the first round. If it fails we do
           not keep spending rounds on it -- a proxy really can be moved,
           unplugged, or reflashed.
        3. Otherwise, whatever currently hears the bed best.
        """
        if self._by_source is not None:
            if self._preferred_source:
                device = self._by_source(self._preferred_source)
                if device is not None:
                    return device
                if round_number == 1:
                    _LOGGER.warning(
                        "%s: preferred source %s cannot currently see this bed; "
                        "falling back to the best available route",
                        self.name, self._preferred_source,
                    )

            if round_number == 1 and self._last_good_route:
                device = self._by_source(self._last_good_route)
                if device is not None:
                    _LOGGER.debug(
                        "%s: trying last known good route %s first",
                        self.name, self._last_good_route,
                    )
                    return device

        return self._ble_device_callback()

    def _on_disconnect(self, _client: BleakClient) -> None:
        """Invoked by bleak on the event loop when the link drops."""
        _LOGGER.info("%s: disconnected", self.name)
        self._client = None
        self._cancel_disconnect_timer()
        self._notify_state()
        if self._always_connected and not self._shutdown:
            self._schedule_reconnect()

    # -- commands ----------------------------------------------------------

    async def async_send_command(self, command: BedCommand) -> None:
        """Send a command, connecting first if needed.

        Retries once on write failure: the common cause is a link that died
        while idle whose disconnect callback has not fired yet, and a blind
        retry on a fresh connection is cheaper than detecting that.
        """
        async with self._lock:
            try:
                await self._write_locked(command)
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug(
                    "%s: write failed (%s); reconnecting and retrying once",
                    self.name, err,
                )
                await self._drop_client()
                await self._write_locked(command)

        self._schedule_disconnect()

    async def _write_locked(self, command: BedCommand) -> None:
        client = await self._connect_locked()
        characteristic = self._control_char
        _LOGGER.debug(
            "%s: sending %s (%s) to handle %s",
            self.name, command.name, command.value,
            getattr(characteristic, "handle", "?"),
        )
        await client.write_gatt_char(characteristic, command.payload, response=True)

    # -- teardown ----------------------------------------------------------

    async def async_disconnect(self) -> None:
        """Disconnect and stop all background activity."""
        self._shutdown = True
        self._cancel_disconnect_timer()
        for attr in ("_disconnect_task", "_reconnect_task"):
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                setattr(self, attr, None)
        async with self._lock:
            await self._drop_client()
        self._notify_state()

    async def _drop_client(self) -> None:
        client, self._client = self._client, None
        self._control_char = None
        if client is not None:
            await self._disconnect_client(client)

    async def _disconnect_client(self, client: BleakClient) -> None:
        try:
            await client.disconnect()
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.debug("%s: error while disconnecting: %s", self.name, err)

    # -- idle handling -----------------------------------------------------

    def _cancel_disconnect_timer(self) -> None:
        if self._disconnect_timer is not None:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

    def _schedule_disconnect(self) -> None:
        """Drop the link after an idle period, unless holding it open."""
        self._cancel_disconnect_timer()
        if self._always_connected or self._shutdown:
            return
        self._disconnect_timer = asyncio.get_running_loop().call_later(
            self._keepalive, self._idle_disconnect
        )

    def _idle_disconnect(self) -> None:
        self._disconnect_timer = None
        _LOGGER.debug("%s: idle %.0fs, disconnecting", self.name, self._keepalive)
        # Keep a reference: a bare create_task() may be garbage collected
        # before it runs, silently leaving the connection open.
        self._disconnect_task = asyncio.create_task(self._async_idle_disconnect())

    async def _async_idle_disconnect(self) -> None:
        async with self._lock:
            await self._drop_client()
        self._notify_state()

    # -- reconnect ---------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Restore the link, backing off on repeated failure."""
        while not self._shutdown and self._always_connected and not self.is_connected:
            await asyncio.sleep(self._reconnect_delay)
            if self._shutdown or self.is_connected:
                return
            try:
                await self.async_connect()
                return
            except ResidentBedNotFound:
                # Expected while the bed is asleep or out of range. Stop
                # burning attempts; async_on_advertisement() restarts us the
                # moment it is seen again.
                _LOGGER.debug(
                    "%s: not visible; waiting for it to advertise", self.name
                )
                return
            except ResidentBedError as err:
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_MAX_DELAY
                )
                _LOGGER.debug(
                    "%s: reconnect failed (%s); next attempt in %.0fs",
                    self.name, err, self._reconnect_delay,
                )

    def async_on_advertisement(self) -> None:
        """Call when the bed is seen advertising again.

        This is what recovers a bed that was unplugged or asleep -- reconnect
        when it actually reappears instead of polling a device that isn't there.
        """
        if self._shutdown or not self._always_connected or self.is_connected:
            return
        self._reconnect_delay = RECONNECT_MIN_DELAY
        self._schedule_reconnect()


def _find_writable(client: BleakClient, uuid: str):
    """Return the writable characteristic for `uuid`, or None.

    Prefers write-with-response, since that is what these bases acknowledge.
    Iterates every characteristic rather than using the UUID lookup, because
    more than one can share a UUID and only some accept writes.
    """
    fallback = None
    for service in client.services:
        for characteristic in service.characteristics:
            if characteristic.uuid.lower() != uuid.lower():
                continue
            if "write" in characteristic.properties:
                return characteristic
            if "write-without-response" in characteristic.properties:
                fallback = fallback or characteristic
    return fallback


def _route_of(device: BLEDevice) -> str:
    """Which adapter or proxy this BLEDevice is routed through, for logging."""
    details = getattr(device, "details", None)
    if isinstance(details, dict) and (source := details.get("source")):
        return str(source)
    return "local adapter"
