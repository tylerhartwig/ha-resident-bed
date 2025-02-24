import voluptuous as vol
from bleak import BleakClient
from homeassistant import config_entries
from homeassistant.components import bluetooth
import logging

from .const import DOMAIN
from .bed_api.resident_bed import ResidentBed

_LOGGER = logging.getLogger(__name__)

class ResidentBedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input=None):
        _LOGGER.info("In async_step_user")
        return self.async_create_entry(title=f'{DOMAIN}-data', data={})

    async def async_step_bluetooth(self, discovery_info = None):
        _LOGGER.info("In async_step_bluetooth")
        if discovery_info is not None:
            mac = discovery_info.address
            device = discovery_info.device
            name = device.name

            _LOGGER.info(f"Setting up for mac address: {mac}")
            _LOGGER.info(f"device is: {device}")

            await self.async_set_unique_id(f'{DOMAIN}-{mac}')

            async with BleakClient(device) as client:
                bed = ResidentBed(client)
                result = await bed.async_setup(client)

                self._abort_if_unique_id_configured()

                if not result:
                    return self.async_abort(reason="connection_error")
                else:
                    return self.async_create_entry(
                        title=f'{DOMAIN}-{mac}',
                        data={
                            "mac": mac,
                            "name": name
                        }
                    )
        else:
            _LOGGER.error("No discovery info")
            return self.async_abort(reason="connection_error")
