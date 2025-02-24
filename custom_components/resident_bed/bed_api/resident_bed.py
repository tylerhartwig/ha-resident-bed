import binascii
import os
import platform

from bleak import BleakClient

from .command import *


class ResidentBed:

    def __init__(self, bleak_client: BleakClient):
        self.control_char = None
        self.notification_char = None
        self.service_collection = None
        # self.bleak_client = bleak_client


    async def async_setup(self, bleak_client):
        print("Connecting")
        con_result = await bleak_client.connect()
        print(f"Connection result: {con_result}")

        self.service_collection = bleak_client.services
        self.notification_char = self.service_collection.get_characteristic(READ_NOTIFY_CONTROL_HANDLE)
        self.control_char = self.service_collection.get_characteristic(READ_NOTIFY_CONTROL_HANDLE)

        try:
            if platform.system() == "Darwin":
                await bleak_client.read_gatt_char(READ_NOTIFY_CONTROL_HANDLE)
                return True
            else:
                await bleak_client.read_gatt_char(READ_NOTIFY_CONTROL_HANDLE)
                await bleak_client.pair()
                return True

        except:
            print("Failed to connect")
            return False


    async def send_command(self, bleak_client, command: BedCommand):
        await bleak_client.write_gatt_char(
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


