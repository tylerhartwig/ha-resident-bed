"""Tests for the BLE connection state machine.

Everything here is transport-agnostic: routes are arbitrary opaque strings, so
nothing depends on any particular adapter, proxy, or address.
"""

import asyncio

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from bed_api import resident_bed as module
from bed_api.command import CONTROL_UUID, BedCommand
from bed_api.resident_bed import ResidentBed, ResidentBedError, ResidentBedNotFound

ADDRESS = "AA:BB:CC:DD:EE:FF"


def make_device(route):
    return BLEDevice(ADDRESS, "TEST-BASE", {"source": route})


class FakeServices:
    def __init__(self, has_control=True):
        self._has_control = has_control

    def get_characteristic(self, uuid):
        return object() if (self._has_control and uuid == CONTROL_UUID) else None


class FakeClient:
    def __init__(self, has_control=True, write_error=None):
        self.is_connected = True
        self.services = FakeServices(has_control)
        self.writes = []
        self.disconnected = False
        self._write_error = write_error

    async def write_gatt_char(self, uuid, payload, response=True):
        if self._write_error is not None:
            err, self._write_error = self._write_error, None
            raise err
        self.writes.append((uuid, payload, response))

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False


@pytest.fixture(autouse=True)
def _no_stale_cleanup(monkeypatch):
    async def _noop(address, only_other_adapters=False):
        return None

    monkeypatch.setattr(module, "close_stale_connections_by_address", _noop)


@pytest.fixture
def connect_recorder(monkeypatch):
    """Patch establish_connection and record the route used for each attempt."""
    calls = {"routes": [], "clients": [], "behaviour": None}

    async def fake_establish(client_class, device, name, **kwargs):
        route = device.details["source"]
        calls["routes"].append(route)
        behaviour = calls["behaviour"]
        if behaviour is not None:
            result = behaviour(route, len(calls["routes"]))
            if isinstance(result, Exception):
                raise result
            if result is not None:
                calls["clients"].append(result)
                result._disconnect_cb = kwargs.get("disconnected_callback")
                return result
        client = FakeClient()
        client._disconnect_cb = kwargs.get("disconnected_callback")
        calls["clients"].append(client)
        return client

    monkeypatch.setattr(module, "establish_connection", fake_establish)
    return calls


# -- routing ---------------------------------------------------------------


async def test_reresolves_route_between_rounds(connect_recorder):
    """A failing route must not be retried blindly; the next round re-resolves."""
    routes = iter(["weak-route", "strong-route", "strong-route"])
    current = {"route": "weak-route"}

    def ble_device():
        current["route"] = next(routes, current["route"])
        return make_device(current["route"])

    def behaviour(route, attempt):
        if route == "weak-route":
            return BleakError("[Errno 104] Connection reset by peer")
        return None

    connect_recorder["behaviour"] = behaviour
    bed = ResidentBed(ADDRESS, "Test", ble_device, always_connected=False)

    await bed.async_connect()

    assert connect_recorder["routes"] == ["weak-route", "strong-route"]
    assert bed.last_route == "strong-route"
    assert bed.is_connected


async def test_gives_up_after_all_rounds(connect_recorder):
    connect_recorder["behaviour"] = lambda route, attempt: BleakError("nope")
    bed = ResidentBed(ADDRESS, "Test", lambda: make_device("r"), always_connected=False)

    with pytest.raises(ResidentBedError):
        await bed.async_connect()

    assert len(connect_recorder["routes"]) == module.CONNECT_ROUNDS


async def test_not_visible_raises_not_found(connect_recorder):
    bed = ResidentBed(ADDRESS, "Test", lambda: None, always_connected=False)

    with pytest.raises(ResidentBedNotFound):
        await bed.async_connect()

    assert connect_recorder["routes"] == []


async def test_missing_control_characteristic_is_rejected(connect_recorder):
    connect_recorder["behaviour"] = lambda route, attempt: FakeClient(has_control=False)
    bed = ResidentBed(ADDRESS, "Test", lambda: make_device("r"), always_connected=False)

    with pytest.raises(ResidentBedError, match="control characteristic"):
        await bed.async_connect()

    assert not bed.is_connected


# -- commands --------------------------------------------------------------


async def test_send_command_writes_payload(connect_recorder):
    bed = ResidentBed(ADDRESS, "Test", lambda: make_device("r"), always_connected=False)

    await bed.async_send_command(BedCommand.TV)

    client = connect_recorder["clients"][0]
    assert client.writes == [(CONTROL_UUID, BedCommand.TV.payload, True)]


async def test_write_failure_reconnects_and_retries_once(connect_recorder):
    """A link that died while idle should cost a retry, not a lost press."""
    clients = [
        FakeClient(write_error=BleakError("not connected")),
        FakeClient(),
    ]
    connect_recorder["behaviour"] = lambda route, attempt: clients[attempt - 1]

    bed = ResidentBed(ADDRESS, "Test", lambda: make_device("r"), always_connected=False)
    await bed.async_send_command(BedCommand.Flat)

    assert clients[0].writes == []
    assert clients[1].writes == [(CONTROL_UUID, BedCommand.Flat.payload, True)]
    assert clients[0].disconnected


async def test_concurrent_presses_share_one_connection(connect_recorder):
    """Simultaneous presses must not each open a client and burn a slot."""
    connects = {"n": 0}

    async def slow_establish(client_class, device, name, **kwargs):
        connects["n"] += 1
        await asyncio.sleep(0.05)
        client = FakeClient()
        client._disconnect_cb = kwargs.get("disconnected_callback")
        connect_recorder["clients"].append(client)
        return client

    module.establish_connection = slow_establish
    bed = ResidentBed(ADDRESS, "Test", lambda: make_device("r"), always_connected=False)

    await asyncio.gather(*(
        bed.async_send_command(c)
        for c in (BedCommand.HeadUp, BedCommand.FeetUp, BedCommand.TV)
    ))

    assert connects["n"] == 1
    assert len(connect_recorder["clients"][0].writes) == 3


# -- idle / reconnect ------------------------------------------------------


async def test_idle_disconnect_when_not_always_connected(connect_recorder):
    bed = ResidentBed(
        ADDRESS, "Test", lambda: make_device("r"),
        keepalive=0.05, always_connected=False,
    )
    await bed.async_send_command(BedCommand.TV)
    assert bed.is_connected

    await asyncio.sleep(0.2)
    assert not bed.is_connected


async def test_always_connected_holds_the_link(connect_recorder):
    bed = ResidentBed(
        ADDRESS, "Test", lambda: make_device("r"),
        keepalive=0.05, always_connected=True,
    )
    await bed.async_send_command(BedCommand.TV)

    await asyncio.sleep(0.2)
    assert bed.is_connected, "always-connected must not schedule an idle disconnect"
    await bed.async_disconnect()


async def test_reconnects_when_bed_advertises_again(connect_recorder):
    bed = ResidentBed(
        ADDRESS, "Test", lambda: make_device("r"), always_connected=True,
    )
    await bed.async_connect()
    client = connect_recorder["clients"][0]

    # Simulate the bed dropping the link.
    module_cb = client._disconnect_cb
    client.is_connected = False
    module_cb(client)
    assert not bed.is_connected

    # Speed up the backoff, then signal that it is advertising again.
    module.RECONNECT_MIN_DELAY = 0.01
    bed._reconnect_delay = 0.01
    bed.async_on_advertisement()
    await asyncio.sleep(0.2)

    assert bed.is_connected
    await bed.async_disconnect()


async def test_availability_tracks_visibility(connect_recorder):
    visible = {"yes": True}
    bed = ResidentBed(
        ADDRESS, "Test",
        lambda: make_device("r") if visible["yes"] else None,
        always_connected=False,
    )
    assert bed.available

    visible["yes"] = False
    assert not bed.available


async def test_state_callbacks_fire_on_connect_and_disconnect(connect_recorder):
    events = []
    bed = ResidentBed(ADDRESS, "Test", lambda: make_device("r"), always_connected=False)
    unsubscribe = bed.register_state_callback(lambda: events.append(bed.is_connected))

    await bed.async_connect()
    assert events == [True]

    unsubscribe()
    await bed.async_disconnect()
    assert events == [True], "unsubscribe must stop delivery"


# -- route pinning / bonding ----------------------------------------------
#
# BLE bonds are held against the central's identity address, and every proxy is
# a separate central, so a bonded base must keep using one route.


def _by_source_factory(available):
    """available: {source: bool} -> callback returning a device for live sources."""
    def _by_source(source):
        return make_device(source) if available.get(source) else None
    return _by_source


async def test_preferred_source_overrides_strongest(connect_recorder):
    bed = ResidentBed(
        ADDRESS, "Test",
        ble_device_callback=lambda: make_device("strongest"),
        ble_device_by_source_callback=_by_source_factory({"pinned": True}),
        preferred_source="pinned",
        always_connected=False,
    )
    await bed.async_connect()

    assert connect_recorder["routes"] == ["pinned"]
    assert bed.last_route == "pinned"


async def test_preferred_source_falls_back_when_not_visible(connect_recorder):
    """A pin must not strand the bed if that adapter cannot see it right now."""
    bed = ResidentBed(
        ADDRESS, "Test",
        ble_device_callback=lambda: make_device("strongest"),
        ble_device_by_source_callback=_by_source_factory({"pinned": False}),
        preferred_source="pinned",
        always_connected=False,
    )
    await bed.async_connect()

    assert connect_recorder["routes"] == ["strongest"]


async def test_route_affinity_is_the_default(connect_recorder):
    """Stick to the route that worked, even when a stronger one appears.

    A BLE bond only works through the central that created it, so following
    signal strength across adapters breaks paired bases.
    """
    strongest = {"route": "bonded"}
    bed = ResidentBed(
        ADDRESS, "Test",
        ble_device_callback=lambda: make_device(strongest["route"]),
        ble_device_by_source_callback=_by_source_factory({"bonded": True}),
        always_connected=False,
    )
    await bed.async_connect()
    assert bed.last_route == "bonded"

    strongest["route"] = "nearer-but-unbonded"
    await bed._drop_client()
    await bed.async_connect()

    assert connect_recorder["routes"] == ["bonded", "bonded"]


async def test_affinity_yields_after_the_first_round_fails(connect_recorder):
    """A proxy can be moved or unplugged; affinity must not strand the bed."""
    def behaviour(route, attempt):
        return BleakError("rejected") if route == "stale" else None

    connect_recorder["behaviour"] = behaviour
    bed = ResidentBed(
        ADDRESS, "Test",
        ble_device_callback=lambda: make_device("healthy"),
        ble_device_by_source_callback=_by_source_factory({"stale": True}),
        last_good_source="stale",
        always_connected=False,
    )
    await bed.async_connect()

    assert connect_recorder["routes"] == ["stale", "healthy"]
    assert bed.last_route == "healthy"


async def test_persisted_route_is_used_on_the_first_connect(connect_recorder):
    """Affinity must survive a restart, so it is seeded from stored state."""
    bed = ResidentBed(
        ADDRESS, "Test",
        ble_device_callback=lambda: make_device("strongest"),
        ble_device_by_source_callback=_by_source_factory({"remembered": True}),
        last_good_source="remembered",
        always_connected=False,
    )
    await bed.async_connect()

    assert connect_recorder["routes"] == ["remembered"]


async def test_route_change_is_reported_once_for_persistence(connect_recorder):
    changes = []
    bed = ResidentBed(
        ADDRESS, "Test",
        ble_device_callback=lambda: make_device("routeA"),
        ble_device_by_source_callback=_by_source_factory({"routeA": True}),
        on_route_changed=changes.append,
        always_connected=False,
    )
    await bed.async_connect()
    await bed._drop_client()
    await bed.async_connect()

    assert changes == ["routeA"], "should report only on change, not every connect"


async def test_pair_flag_is_passed_to_establish_connection(monkeypatch):
    seen = {}

    async def fake_establish(client_class, device, name, **kwargs):
        seen.update(kwargs)
        client = FakeClient()
        client._disconnect_cb = kwargs.get("disconnected_callback")
        return client

    monkeypatch.setattr(module, "establish_connection", fake_establish)
    bed = ResidentBed(
        ADDRESS, "Test", lambda: make_device("r"), pair=True, always_connected=False
    )
    await bed.async_connect()

    assert seen["pair"] is True
