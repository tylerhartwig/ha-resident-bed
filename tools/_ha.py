"""Shared config + HTTP helpers for the Resident Bed dev tools.

Credentials come from `.env` at the repo root (gitignored) or the real
environment. Nothing in this file may print or log HA_TOKEN.

Targets Python 3.9+ so it runs on macOS system python3 without a venv.
"""

import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip3 install requests")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO_ROOT, ".env")


def load_env():
    """Load .env into os.environ without clobbering real env vars."""
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, "r") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def config():
    """Return (url, token, verify_ssl). Exits with guidance if unconfigured."""
    load_env()
    url = (os.environ.get("HA_URL") or "").rstrip("/")
    token = os.environ.get("HA_TOKEN") or ""
    verify = (os.environ.get("HA_VERIFY_SSL", "true").lower()
              not in ("false", "0", "no"))

    if not url or not token:
        sys.exit(
            "Home Assistant is not configured.\n"
            "  cp .env.example .env   # then set HA_URL and HA_TOKEN\n"
            "Create a token: HA Profile -> Security -> Long-lived access tokens"
        )
    return url, token, verify


def request(method, path, json_body=None, stream=False):
    """Call the HA REST API. `path` starts with '/api/...'."""
    url, token, verify = config()
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }
    try:
        response = requests.request(
            method,
            url + path,
            headers=headers,
            json=json_body,
            verify=verify,
            stream=stream,
            timeout=60,
        )
    except requests.exceptions.SSLError as err:
        sys.exit("TLS error talking to %s: %s\n"
                 "If this instance uses a self-signed cert, set "
                 "HA_VERIFY_SSL=false in .env." % (url, err))
    except requests.exceptions.RequestException as err:
        sys.exit("Could not reach %s: %s" % (url, err))

    if response.status_code == 401:
        sys.exit("401 Unauthorized -- HA_TOKEN is invalid or revoked. "
                 "Mint a new long-lived token in your HA profile.")
    if response.status_code == 404:
        sys.exit("404 Not Found for %s -- endpoint unavailable on this "
                 "instance (Supervisor endpoints need the Supervisor API)." % path)
    if response.status_code >= 400:
        sys.exit("HTTP %s for %s\n%s"
                 % (response.status_code, path, response.text[:2000]))
    return response
