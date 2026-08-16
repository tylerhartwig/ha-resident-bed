"""Shared entity base and helpers for the Resident Bed integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .bed_api.resident_bed import ResidentBed
from .const import DOMAIN


def async_reachability_hint(hass: HomeAssistant, address: str) -> str | None:
    """Explain why an address may be unreachable, if Home Assistant can tell.

    Home Assistant knows which adapters and proxies can see a device and how
    well; surfacing that beats a bare "connection failed". Guarded so the
    integration still loads on builds without this helper.
    """
    diagnostics = getattr(
        bluetooth, "async_address_reachability_diagnostics", None
    )
    intent_enum = getattr(bluetooth, "BluetoothReachabilityIntent", None)
    if diagnostics is None or intent_enum is None:
        return None

    try:
        return diagnostics(hass, address, intent_enum.CONNECTION)
    except Exception:  # noqa: BLE001 - diagnostics must never mask the real error
        return None


class ResidentBedEntity(Entity):
    """Base entity tied to one bed base."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, bed: ResidentBed) -> None:
        self._bed = bed
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, bed.address)},
            connections={(CONNECTION_BLUETOOTH, bed.address)},
            name=bed.name,
            manufacturer="OKIN",
            model="Adjustable Bed Base",
        )

    @property
    def available(self) -> bool:
        """Whether the bed can currently be reached."""
        return self._bed.available

    async def async_added_to_hass(self) -> None:
        """Track connection-state changes so availability stays accurate."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._bed.register_state_callback(self._handle_state_change)
        )

    def _handle_state_change(self) -> None:
        """Called from the BLE layer when the connection state changes."""
        if self.hass is not None:
            self.schedule_update_ha_state()
