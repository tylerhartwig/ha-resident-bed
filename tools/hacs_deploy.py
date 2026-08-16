#!/usr/bin/env python3
"""Refresh and install this integration through HACS, over the websocket API.

  python3 tools/hacs_deploy.py status     # HACS stage + this repo's versions
  python3 tools/hacs_deploy.py refresh    # force HACS to re-read the repo
  python3 tools/hacs_deploy.py install    # download the latest version

Why this exists: HACS only re-reads repositories on its own schedule, and if
its startup tasks fail it can stop noticing updates entirely. The HACS
frontend drives these same websocket commands, so this works when the update
entity is stale.

Needs `websockets` (see requirements-dev.txt), so run it from the venv:
  .venv/bin/python tools/hacs_deploy.py status
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ha

try:
    import websockets
except ImportError:
    sys.exit("Missing dependency: .venv/bin/pip install -r requirements-dev.txt")

REPO = "tylerhartwig/ha-resident-bed"


class Client:
    def __init__(self):
        url, self._token, self._verify = _ha.config()
        self._ws_url = url.replace("https://", "wss://").replace(
            "http://", "ws://"
        ) + "/api/websocket"
        self._id = 0
        self._ws = None

    async def __aenter__(self):
        ssl_arg = {}
        if self._ws_url.startswith("wss://") and not self._verify:
            import ssl as _ssl
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            ssl_arg["ssl"] = ctx

        self._ws = await websockets.connect(
            self._ws_url, max_size=32 * 1024 * 1024, **ssl_arg
        )
        await self._recv()  # auth_required
        await self._ws.send(
            json.dumps({"type": "auth", "access_token": self._token})
        )
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
        payload = {**payload, "id": self._id}
        await self._ws.send(json.dumps(payload))
        while True:
            msg = await asyncio.wait_for(self._recv(), timeout)
            if msg.get("id") == self._id and msg.get("type") == "result":
                if not msg.get("success"):
                    raise RuntimeError(msg.get("error"))
                return msg.get("result")


async def _find(client):
    repos = await client.send({"type": "hacs/repositories/list"})
    for repo in repos or []:
        if repo.get("full_name", "").lower() == REPO.lower():
            return repo
    sys.exit("%s is not known to HACS." % REPO)


async def cmd_status(_args):
    async with Client() as client:
        try:
            info = await client.send({"type": "hacs/info"})
            print("HACS stage: %s  version: %s"
                  % (info.get("stage"), info.get("version")))
        except RuntimeError as err:
            print("hacs/info failed: %s" % err)
        repo = await _find(client)
        for key in ("id", "installed_version", "available_version",
                    "installed", "status", "last_updated"):
            if key in repo:
                print("  %-20s %s" % (key, repo[key]))


async def cmd_refresh(_args):
    async with Client() as client:
        repo = await _find(client)
        print("refreshing %s (id=%s) ..." % (REPO, repo["id"]))
        await client.send(
            {"type": "hacs/repository/refresh", "repository": repo["id"]}
        )
        repo = await _find(client)
        print("  installed=%s available=%s"
              % (repo.get("installed_version"), repo.get("available_version")))


async def cmd_install(args):
    async with Client() as client:
        repo = await _find(client)
        payload = {"type": "hacs/repository/download", "repository": repo["id"]}
        if args.version:
            payload["version"] = args.version
        print("downloading %s %s ..." % (REPO, args.version or "(latest)"))
        await client.send(payload)
        repo = await _find(client)
        print("  installed=%s available=%s"
              % (repo.get("installed_version"), repo.get("available_version")))
        print("Restart Home Assistant to load the new code.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["status", "refresh", "install"])
    parser.add_argument("--version", help="specific ref/tag to install")
    args = parser.parse_args()
    asyncio.run(
        {"status": cmd_status, "refresh": cmd_refresh, "install": cmd_install}[
            args.action
        ](args)
    )


if __name__ == "__main__":
    main()
