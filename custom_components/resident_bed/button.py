import binascii
import logging

from bleak import BleakClient
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components import bluetooth

from .base import ResidentBedEntity

from .bed_api.command import *

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ):
    """Setup Resident Bed Buttons"""
    device_configs = config_entry.data
    _LOGGER.info(f"config entry: {device_configs}")
    mac = device_configs.get("mac")
    name = device_configs.get("name")

    buttons = []

    for command in BedCommand:
        button = ResidentBedButton(hass, name, mac, command)
        buttons.append(button)

    async_add_entities(buttons)


class ResidentBedButton(ResidentBedEntity):

    def __init__(self, hass, device_name, device_address, command: BedCommand):
        super().__init__(device_address)
        self.hass = hass
        self.mac = device_address
        self.device_name = device_name
        self.command = command
        self._attr_translation_key = f"{command.name}_button"
        self._attr_unique_id = f"{DOMAIN}_BED_{self.device_address}_{self.command.name}"

    async def _async_press_action(self) -> None:
        """Handle button press"""
        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.mac, connectable=True)
        async with BleakClient(ble_device) as client:
            await client.connect()
            service_collection = client.services
            characteristics = service_collection.characteristics
            _LOGGER.info(f"Service collection: {service_collection}")
            _LOGGER.info(f"characteristics: {characteristics}")

            control_char = None
            notify_char = None
            for key, characteristic in characteristics.items():
                if "62741525-52f9-8864-b1ab-3b3a8d65950b" == characteristic.uuid and 'write' in characteristic.properties:
                    control_char = characteristic

                if "62741525-52f9-8864-b1ab-3b3a8d65950b" == characteristic.uuid and 'notify' in characteristic.properties:
                    notify_char = characteristic


            _LOGGER.info(f"Control char: {control_char}")
            _LOGGER.info(f"Notify char: {notify_char}")

            await client.start_notify(notify_char, lambda a, b : None)
            data = await client.read_gatt_char(notify_char)
            _LOGGER.info(f"Read gatt char: {data}")


            _LOGGER.info(f"Writing gatt char")
            await client.write_gatt_char(
                control_char,
                binascii.a2b_hex(self.command.value), response=True)

        # _LOGGER.info(f"ble_device: {ble_device}")

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id


    @property
    def name(self) -> str:
        """Name of the entity."""
        return f"{self.device_name} {self.command.name()}"
