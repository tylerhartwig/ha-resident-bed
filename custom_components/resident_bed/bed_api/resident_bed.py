import binascii
import os
import platform
import logging

from bleak import BleakClient

from .command import *

_LOGGER = logging.getLogger(__name__)

class ResidentBed:

    def __init__(self, bleak_client):
        self.control_char = None
        self.notification_char = None
        self.service_collection = None
        self.bleak_client = bleak_client


    async def async_setup(self):

        self.service_collection = self.bleak_client.services
        characteristics = self.service_collection.characteristics
        _LOGGER.debug(f"Service collection: {self.service_collection}")
        _LOGGER.debug(f"characteristics: {characteristics}")

        for key, characteristic in characteristics.items():
            _LOGGER.debug(f"Characteristic: {key}, {characteristics}")
            if "62741525-52f9-8864-b1ab-3b3a8d65950b" == characteristic.uuid and 'write' in characteristic.properties:
                _LOGGER.debug(f"Write Characteristic UUID: {characteristic.uuid}")
                self.control_char = characteristic

            if "62741525-52f9-8864-b1ab-3b3a8d65950b" == characteristic.uuid and 'notify' in characteristic.properties:
                _LOGGER.debug(f"Notify Characteristic UUID: {characteristic.uuid}")
                self.notification_char = characteristic



    async def send_command(self, command: BedCommand):
        _LOGGER.debug(f"Sending command: {command}")
        if self.bleak_client.is_connected:
            _LOGGER.debug(f"Writing gatt char {self.control_char}")
            await self.bleak_client.write_gatt_char(
                self.control_char,
                binascii.a2b_hex(command.value),
                response=True)
        else:
            _LOGGER.error(f"Bleak Client not connected")



    # async def tv_mode(self):
    #     await self.send_command(BedCommand.TV)
    #
    #
    # async def m1_mode(self):
    #     await self.send_command(BedCommand.M1)
    #
    async def test(self):
        await self.send_command(TEST)


