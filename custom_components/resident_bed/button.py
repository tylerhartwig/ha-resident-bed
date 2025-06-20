import binascii
import logging
import platform

from bleak import BleakClient
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components import bluetooth

from .base import ResidentBedEntity

from .bed_api.command import *
from .bed_api.resident_bed import ResidentBed

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


    async def get_resident_bed(self):
        bed = self.hass.data[DOMAIN].get(self.mac)

        def on_disconnect(client):
            self.hass.data[DOMAIN][self.mac] = None

        if not bed:
            _LOGGER.info(f"No Bed device found for mac {self.mac}, setting up")
            ble_device = bluetooth.async_ble_device_from_address(self.hass, self.mac, connectable=True)

            _LOGGER.debug(f"BLE Device is: {ble_device}")
            client = BleakClient(ble_device, disconnected_callback=on_disconnect, timeout=30)

            if not client.is_connected:
                _LOGGER.info(f"Client not connected, connecting")
                await client.connect()
            # _LOGGER.info(f"Created BleakClient: {client}")

            try:
                if platform.system() == "Darwin":
                    _LOGGER.info("Running on macOS, reading char to initiate pair")
                    await client.read_gatt_char(READ_NOTIFY_CONTROL_HANDLE)

                else:
                    _LOGGER.info(f"Running on Linux, Initiating Pairing with client")

                    await client.pair()
                    _LOGGER.info("Pairing Complete")
                    # if not self.bleak_client.is_connected:
                    #     _LOGGER.info(f"BleakClient not connected, connecting now")
                    #     await self.bleak_client.connect()


                bed = ResidentBed(client)

                _LOGGER.info(f"Created new bed device, mac {self.mac}, setting up now")

                if await bed.async_setup():
                    self.hass.data[DOMAIN][self.mac] = bed

            except Exception as e:
                _LOGGER.error(f"Failed to connect with exception {e}")

        else:
            _LOGGER.debug(f"Bed device found for mac {self.mac}, using cached bed")

        return bed

    async def _async_press_action(self) -> None:
        """Handle button press"""
        bed = await self.get_resident_bed()
        await bed.send_command(self.command)


    @property
    def unique_id(self) -> str:
        return self._attr_unique_id


    @property
    def name(self) -> str:
        """Name of the entity."""
        return f"{self.device_name} {self.command.name()}"
