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
        # try:
        # except Exception as e:
        #     _LOGGER.error(f"Failed to connect to Resident Bed with exception {e}")
        #     return False


        try:
            if platform.system() == "Darwin":
                await self.bleak_client.connect()
                _LOGGER.info(f"Connection Complete!")
                _LOGGER.info("Running on macOS, reading char to initiate pair")
                await self.bleak_client.read_gatt_char(READ_NOTIFY_CONTROL_HANDLE)

            else:
                _LOGGER.info("Running on Linux, Initiating Pairing")
                await self.bleak_client.pair()
                _LOGGER.info("Pairing Complete")


            self.service_collection = self.bleak_client.services
            characteristics = self.service_collection.characteristics
            _LOGGER.info(f"Service collection: {self.service_collection}")
            _LOGGER.info(f"characteristics: {characteristics}")

            for key, characteristic in characteristics.items():
                if "62741525-52f9-8864-b1ab-3b3a8d65950b" == characteristic.uuid and 'write' in characteristic.properties:
                    self.control_char = characteristic

                if "62741525-52f9-8864-b1ab-3b3a8d65950b" == characteristic.uuid and 'notify' in characteristic.properties:
                    self.notification_char = characteristic

            return True

        except Exception as e:
            _LOGGER.error(f"Failed to connect with exception {e}")
            return False

    async def send_command(self, command: BedCommand):
        if self.bleak_client.is_connected:
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


