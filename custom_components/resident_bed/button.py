"""Button entities for the Resident Bed integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ResidentBedConfigEntry
from .base import ResidentBedEntity, async_reachability_hint
from .bed_api.command import BedCommand
from .bed_api.resident_bed import ResidentBed, ResidentBedError, ResidentBedNotFound
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ResidentBedConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one button per bed command."""
    bed: ResidentBed = entry.runtime_data
    async_add_entities(ResidentBedButton(bed, command) for command in BedCommand)


class ResidentBedButton(ResidentBedEntity, ButtonEntity):
    """A single bed command, exposed as a button."""

    def __init__(self, bed: ResidentBed, command: BedCommand) -> None:
        super().__init__(bed)
        self._command = command
        self._attr_unique_id = f"{DOMAIN}_{bed.address}_{command.name}"
        self._attr_translation_key = command.name.lower()
        # Fallback for the case where a translation is missing; with
        # _attr_has_entity_name the device name is prepended automatically.
        self._attr_name = command.display_name

    async def async_press(self) -> None:
        """Send this command to the bed."""
        try:
            await self._bed.async_send_command(self._command)
        except ResidentBedNotFound as err:
            hint = async_reachability_hint(self.hass, self._bed.address)
            raise HomeAssistantError(
                f"{self._bed.name} is not reachable over Bluetooth. "
                + (hint or "It may be asleep, unplugged, or out of range of any "
                           "Bluetooth adapter or proxy.")
            ) from err
        except ResidentBedError as err:
            raise HomeAssistantError(
                f"Failed to send {self._command.display_name} to "
                f"{self._bed.name}: {err}"
            ) from err
