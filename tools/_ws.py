"""Minimal Home Assistant websocket client.

The REST API does not expose config-entry `data` or the device/entity
registries; the websocket API does. Shared by the tools that need them.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ha

try:
    import websockets
except ImportError:
    sys.exit("Missing dependency: .venv/bin/pip install -r requirements-dev.txt\n"
             "(this tool needs the venv, not system python3)")


class Client:
    """Authenticated websocket connection, used as an async context manager."""

    def __init__(self):
        url, self._token, self._verify = _ha.config()
        self._ws_url = (
            url.replace("https://", "wss://").replace("http://", "ws://")
            + "/api/websocket"
        )
        self._id = 0
        self._ws = None

    async def __aenter__(self):
        kwargs = {}
        if self._ws_url.startswith("wss://") and not self._verify:
            import ssl as _ssl
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            kwargs["ssl"] = ctx

        self._ws = await websockets.connect(
            self._ws_url, max_size=64 * 1024 * 1024, **kwargs
        )
        await self._recv()  # auth_required
        await self._ws.send(json.dumps({"type": "auth", "access_token": self._token}))
        auth = await self._recv()
        if auth.get("type") != "auth_ok":
            sys.exit("Websocket auth failed: %s" % auth)
        return self

    async def __aexit__(self, *_):
        if self._ws is not None:
            await self._ws.close()

    async def _recv(self):
        return json.loads(await self._ws.recv())

    async def send(self, payload, timeout=180):  # noqa: ASYNC109
        self._id += 1
        await self._ws.send(json.dumps({**payload, "id": self._id}))
        while True:
            msg = await asyncio.wait_for(self._recv(), timeout)
            if msg.get("id") == self._id and msg.get("type") == "result":
                if not msg.get("success"):
                    raise RuntimeError(msg.get("error"))
                return msg.get("result")


async def bed_addresses(domain):
    """Map config_entry_id -> (name, bluetooth address) from the device registry.

    Reads the registry rather than parsing entry titles, which users rename.
    """
    async with Client() as client:
        devices = await client.send({"type": "config/device_registry/list"})

    result = {}
    for device in devices:
        for connection_type, value in device.get("connections") or []:
            if connection_type != "bluetooth":
                continue
            for entry_id in device.get("config_entries") or []:
                result[entry_id] = (
                    device.get("name_by_user") or device.get("name"),
                    value,
                )
        for identifier in device.get("identifiers") or []:
            if len(identifier) == 2 and identifier[0] == domain:
                for entry_id in device.get("config_entries") or []:
                    result.setdefault(
                        entry_id,
                        (device.get("name_by_user") or device.get("name"),
                         identifier[1]),
                    )
    return result
