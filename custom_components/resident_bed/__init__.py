from homeassistant.components.device_tracker import config_entry
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.BUTTON]

async def async_setup_entry(hass, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    # hass.data[DOMAIN][PLATFORMS] = hass.data[DOMAIN][PLATFORMS]

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True