from typing import Any

import voluptuous as vol
from bleak import BleakClient
from bluetooth_data_tools import human_readable_name
from habluetooth import BluetoothServiceInfoBleak
from homeassistant import config_entries
from homeassistant.components import bluetooth
import logging

from .const import DOMAIN
from .bed_api.resident_bed import ResidentBed

_LOGGER = logging.getLogger(__name__)

class ResidentBedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self):
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self.display_name: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        _LOGGER.info("In async_step_user")

        if user_input is not None:
            self.display_name = user_input["name"]
            return await self.async_step_setup_pair()
        else:
            data_schema = vol.Schema({
                vol.Required("name"): str
            })
            return self.async_show_form(step_id="user", data_schema=data_schema, last_step=False)

        # self.
        # return self.async_create_entry(title=f'{DOMAIN}-data', data={})


    async def async_step_setup_pair(self, user_input: dict[str, Any] | None = None):
        _LOGGER.info(f"In async_step_setup_pair, current input is {user_input}")
        if user_input is not None:
            return await self.async_step_connect()
        else:
            return self.async_show_form(step_id="setup_pair", data_schema=vol.Schema({}), last_step=False)

    async def async_step_connect(self, user_input: dict[str, Any] | None = None):
        _LOGGER.info(f"In async_step_connect, current input is {user_input}")

        mac = self._discovery_info.address
        bed = ResidentBed(BleakClient(mac))
        connection_result = await bed.async_setup()

        if connection_result:
            _LOGGER.info(f"Successfully connected to bed")

            return self.async_create_entry(
                title=f'{DOMAIN}-{mac}',
                data={
                    "mac": mac,
                    "name": self.display_name
                }
            )

        else:
            _LOGGER.info(f"Failed to connect to bed")
            return await self.async_step_setup_pair()
        # if user_input is not None:
        # else:

        return self.async_show_form(step_id="connect", data_schema=vol.Schema({}), last_step=False)

    async def async_step_complete(self, user_input: dict[str, Any] | None = None):
        _LOGGER.info(f"In async_step_complete, current input is {user_input}")
        return self.async_abort(reason="Implement")

    async def async_step_bluetooth(self, discovery_info = None):
        _LOGGER.info("In async_step_bluetooth")
        if discovery_info is not None:
            mac = discovery_info.address
            device = discovery_info.device
            name = device

            _LOGGER.info(f"Setting up for mac address: {mac}")
            _LOGGER.info(f"device is: {device}")

            await self.async_set_unique_id(f'{DOMAIN}-{mac}')

            self._abort_if_unique_id_configured()
            self._discovery_info = discovery_info
            self.context["title_placeholders"] = {"name": human_readable_name(f"{device}", f"{name}", mac)}

            return await self.async_step_user()
            # async with BleakClient(device) as client:
                # bed = ResidentBed(client)
                # result = await bed.async_setup(client)



                # if not result:
                #     return self.async_abort(reason="connection_error")
                # else:
                #     return self.async_create_entry(
                #         title=f'{DOMAIN}-{mac}',
                #         data={
                #             "mac": mac,
                #             "name": name
                #         }
                #     )
        else:
            _LOGGER.error("No discovery info")
            return self.async_abort(reason="connection_error")
