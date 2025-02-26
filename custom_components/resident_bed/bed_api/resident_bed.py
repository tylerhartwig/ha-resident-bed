import binascii
import os
import platform
import logging

from bleak import BleakClient

from .command import *

_LOGGER = logging.getLogger(__name__)

class ResidentBed:

    def __init__(self, bleak_client: BleakClient):
        self.control_char = None
        self.notification_char = None
        self.service_collection = None
        self.bleak_client = bleak_client


    async def async_setup(self):
        _LOGGER.info("Connecting to Resident Bed")
        try:
            await self.bleak_client.connect()
            _LOGGER.info(f"Connection Complete!")
        except:
            _LOGGER.error("Failed to connect to Resident Bed")

        self.service_collection = self.bleak_client.services
        self.notification_char = self.service_collection.get_characteristic(READ_NOTIFY_CONTROL_HANDLE)
        self.control_char = self.service_collection.get_characteristic(READ_NOTIFY_CONTROL_HANDLE)

        try:
            if platform.system() == "Darwin":
                _LOGGER.info("Running on macOS, reading char to initiate pair")
                await self.bleak_client.read_gatt_char(READ_NOTIFY_CONTROL_HANDLE)
                return True
            else:
                _LOGGER.info("Running on Linux, Initiating Pairing")
                await self.bleak_client.pair()
                _LOGGER.info("Pairing Complete")
                return True

        except:
            _LOGGER.error("Failed to connect")
            return False


    async def send_command(self, command: BedCommand):
        await self.bleak_client.write_gatt_char(
            WRITE_CONTROL_HANDLE,
            binascii.a2b_hex(command.value),
            response=True)


    # async def tv_mode(self):
    #     await self.send_command(BedCommand.TV)
    #
    #
    # async def m1_mode(self):
    #     await self.send_command(BedCommand.M1)
    #
    async def test(self):
        await self.send_command(TEST)


