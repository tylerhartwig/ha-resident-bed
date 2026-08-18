"""The Resident Bed integration."""

from __future__ import annotations

import asyncio
import logging
import re

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .bed_api.resident_bed import ResidentBed
from .const import (
    CONF_ADDRESS,
    CONF_ALWAYS_CONNECTED,
    CONF_KEEPALIVE,
    CONF_LAST_GOOD_SOURCE,
    CONF_NAME,
    CONF_PAIR,
    CONF_PREFERRED_SOURCE,
    DEFAULT_ALWAYS_CONNECTED,
    DEFAULT_KEEPALIVE,
    DEFAULT_PAIR,
    DOMAIN,
    LEGACY_CONF_MAC,
)

_LOGGER = logging.getLogger(__name__)

# Startup warm-ups are serialized. Several beds are typically served by the same
# adapter or proxy, and entries set up concurrently, so their warm-up connects
# land within milliseconds of each other and contend for the same connection
# slots. Observed: two beds warming up 5ms apart, the second losing a full
# 12s round before succeeding on its retry.
_WARMUP_LOCK = asyncio.Lock()

PLATFORMS: list[Platform] = [Platform.BUTTON]

# ConfigEntry is generic over runtime_data.
type ResidentBedConfigEntry = ConfigEntry[ResidentBed]

# Entities created before the BedCommand.name fix carry a unique_id containing
# a bound-method repr, e.g.
#   resident_bed_BED_AA:BB:..._<bound method BedCommand.name of <BedCommand.TV: '0c02...'>>
# Pull the member name back out of it so existing entities keep their entity_id
# instead of being orphaned and recreated with a _2 suffix.
_LEGACY_UNIQUE_ID_RE = re.compile(r"<BedCommand\.(?P<command>\w+):")


def _address_of(entry: ConfigEntry) -> str:
    """Read the bed address, tolerating entries written before version 2."""
    return entry.data.get(CONF_ADDRESS) or entry.data[LEGACY_CONF_MAC]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 2:
        # Downgrade is not supported.
        return False

    if entry.version == 1:
        data = {**entry.data}
        address = data.pop(LEGACY_CONF_MAC, None) or data.get(CONF_ADDRESS)
        if address:
            data[CONF_ADDRESS] = address

        updates: dict = {"data": data, "version": 2}

        # Version 1 used a "<domain>-<address>" unique_id. Normalize to the bare
        # address, which is the convention for Bluetooth integrations and what
        # the current flow sets -- otherwise rediscovery would not recognise
        # this bed as already configured and would offer a duplicate.
        if address and entry.unique_id != address:
            updates["unique_id"] = address

        # Version 1 titled entries "<domain>-<address>"; prefer the user's name.
        if data.get(CONF_NAME) and entry.title.startswith(f"{DOMAIN}-"):
            updates["title"] = data[CONF_NAME]

        hass.config_entries.async_update_entry(entry, **updates)
        _LOGGER.debug("Migrated %s to version 2", entry.title)

    return True


@callback
def _migrate_entity_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rewrite legacy entity unique_ids in place."""
    registry = er.async_get(hass)
    address = _address_of(entry)

    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        match = _LEGACY_UNIQUE_ID_RE.search(registry_entry.unique_id)
        if match is None:
            continue

        new_unique_id = f"{DOMAIN}_{address}_{match.group('command')}"
        if registry.async_get_entity_id(
            registry_entry.domain, DOMAIN, new_unique_id
        ):
            # Target already exists; leave the stale one for the user to remove
            # rather than colliding.
            _LOGGER.debug(
                "Skipping unique_id migration for %s: %s already exists",
                registry_entry.entity_id, new_unique_id,
            )
            continue

        _LOGGER.info(
            "Migrating unique_id for %s", registry_entry.entity_id
        )
        registry.async_update_entity(
            registry_entry.entity_id, new_unique_id=new_unique_id
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ResidentBedConfigEntry
) -> bool:
    """Set up Resident Bed from a config entry."""
    address = _address_of(entry)
    name = entry.data.get(CONF_NAME) or f"Resident Bed {address}"

    _migrate_entity_unique_ids(hass, entry)

    @callback
    def _ble_device():
        """Resolve the best currently-reachable route to the bed.

        Called fresh before every connection round, so each attempt can be
        served by whichever adapter or proxy currently hears the bed best.
        """
        return bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        )

    @callback
    def _ble_device_by_source(source: str):
        """Resolve the bed via one specific adapter or proxy.

        Needed for bonded bases: a BLE bond is held against the central's
        identity address, and every proxy is a separate central, so the bond
        only works through the proxy it was created with.
        """
        for scanner_device in bluetooth.async_scanner_devices_by_address(
            hass, address, connectable=True
        ):
            if scanner_device.scanner.source == source:
                return scanner_device.ble_device
        return None

    @callback
    def _remember_route(source: str) -> None:
        """Persist the route that worked, so a restart keeps bond affinity."""
        if entry.data.get(CONF_LAST_GOOD_SOURCE) == source:
            return
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_LAST_GOOD_SOURCE: source}
        )

    bed = ResidentBed(
        address=address,
        name=name,
        ble_device_callback=_ble_device,
        ble_device_by_source_callback=_ble_device_by_source,
        last_good_source=entry.data.get(CONF_LAST_GOOD_SOURCE),
        on_route_changed=_remember_route,
        keepalive=entry.options.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE),
        always_connected=entry.options.get(
            CONF_ALWAYS_CONNECTED, DEFAULT_ALWAYS_CONNECTED
        ),
        pair=entry.options.get(CONF_PAIR, DEFAULT_PAIR),
        preferred_source=entry.options.get(CONF_PREFERRED_SOURCE) or None,
    )
    entry.runtime_data = bed

    @callback
    def _on_advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Reconnect as soon as the bed is seen again after being away."""
        bed.async_on_advertisement()

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _on_advertisement,
            {"address": address, "connectable": True},
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )
    # add_update_listener fires on *any* entry change, including the data-only
    # write that records the working route. Reload only when the user actually
    # changed an option, otherwise persisting a route would reload the entry,
    # which reconnects, which persists again -- an endless loop.
    options_at_setup = dict(entry.options)

    async def _async_entry_updated(
        hass: HomeAssistant, updated: ResidentBedConfigEntry
    ) -> None:
        if dict(updated.options) == options_at_setup:
            return
        await hass.config_entries.async_reload(updated.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Warm up in the background, whether or not the link is held open.
    #
    # The GATT service cache is per Home Assistant process, so the first
    # connection after a restart pays full service discovery -- measured at
    # 14-24s against ~0.6-3s once the cache is warm. Doing that here means the
    # user's first button press does not.
    #
    # Deliberately not awaited: the bed may be asleep or out of range, and that
    # must not block or fail setup. The advertisement callback above reconnects
    # once it reappears. In on-demand mode the idle timer drops this warm-up
    # connection normally.
    entry.async_create_background_task(
        hass, _async_initial_connect(bed), f"{DOMAIN}-connect-{address}"
    )

    return True


async def _async_initial_connect(bed: ResidentBed) -> None:
    """Best-effort connect at startup, one bed at a time."""
    async with _WARMUP_LOCK:
        try:
            await bed.async_connect()
        except Exception as err:  # noqa: BLE001 - startup must never fail on this
            _LOGGER.debug(
                "%s: initial connect did not succeed (%s); will retry when the "
                "bed advertises", bed.name, err,
            )


async def async_unload_entry(
    hass: HomeAssistant, entry: ResidentBedConfigEntry
) -> bool:
    """Unload a config entry, tearing the BLE connection down cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    bed: ResidentBed | None = getattr(entry, "runtime_data", None)
    if bed is not None:
        await bed.async_disconnect()
    return unload_ok
