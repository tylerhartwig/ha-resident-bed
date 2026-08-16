"""Constants for the Resident Bed integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "resident_bed"

# Config entry data
CONF_ADDRESS: Final = "address"
CONF_NAME: Final = "name"

# Legacy key, written by config entries created before version 2.
LEGACY_CONF_MAC: Final = "mac"

# Options
CONF_ALWAYS_CONNECTED: Final = "always_connected"
CONF_KEEPALIVE: Final = "keepalive"
CONF_PAIR: Final = "pair"
CONF_PREFERRED_SOURCE: Final = "preferred_source"

# Config-entry data (state, not user configuration): the adapter or proxy that
# last connected successfully. Persisted so a Home Assistant restart does not
# lose route affinity -- which matters because a BLE bond only works through
# the central it was created with.
CONF_LAST_GOOD_SOURCE: Final = "last_good_source"

# Holding the link open removes connect latency from the first press, at the
# cost of one connection slot on the adapter or proxy serving the bed. Users
# with a single proxy and many BLE devices may prefer to turn this off.
# Off by default. Holding links open kept two connection slots busy on one
# proxy and produced sustained connect/disconnect churn, while an on-demand
# reconnect measured ~2s on a healthy route -- fast enough that the cost of
# holding the link is not worth it.
DEFAULT_ALWAYS_CONNECTED: Final = False

# Seconds to hold an idle connection open when always-connected is off.
DEFAULT_KEEPALIVE: Final = 90
MIN_KEEPALIVE: Final = 0
MAX_KEEPALIVE: Final = 3600

# BLE bonding is established between the peripheral and the *central's* identity
# address. With Bluetooth proxies each proxy is its own central, so a bond made
# through one proxy is not usable from another, and peripherals have very few
# bond slots. Bases that require bonding must therefore be pinned to a single
# route -- see AGENT.md section 6.
DEFAULT_PAIR: Final = False

# Empty means "use whichever adapter or proxy currently hears the bed best".
AUTOMATIC_SOURCE: Final = ""
