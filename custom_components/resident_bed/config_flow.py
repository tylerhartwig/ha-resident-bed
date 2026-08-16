"""Config flow for the Resident Bed integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import callback

from .base import async_reachability_hint
from .bed_api.command import SERVICE_UUID
from .bed_api.resident_bed import ResidentBed, ResidentBedError
from .const import (
    CONF_ADDRESS,
    CONF_ALWAYS_CONNECTED,
    CONF_KEEPALIVE,
    CONF_NAME,
    AUTOMATIC_SOURCE,
    CONF_LAST_GOOD_SOURCE,
    CONF_PAIR,
    CONF_PREFERRED_SOURCE,
    DEFAULT_ALWAYS_CONNECTED,
    DEFAULT_KEEPALIVE,
    DEFAULT_PAIR,
    DOMAIN,
    MAX_KEEPALIVE,
    MIN_KEEPALIVE,
)

_LOGGER = logging.getLogger(__name__)


class ResidentBedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual setup of a bed base."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._address: str | None = None
        self._name: str | None = None
        self._last_good_source: str | None = None

    # -- discovery ---------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a bed discovered over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self._address = discovery_info.address
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_configure()

    # -- manual ------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick from beds currently visible over Bluetooth."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_configure()

        candidates = self._discovered_beds()
        if not candidates:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(candidates)}
            ),
        )

    def _discovered_beds(self) -> dict[str, str]:
        """Addresses of unconfigured beds currently advertising, keyed for a picker."""
        configured = self._async_current_ids()
        candidates: dict[str, str] = {}

        for info in bluetooth.async_discovered_service_info(
            self.hass, connectable=True
        ):
            if SERVICE_UUID not in info.service_uuids:
                continue
            if info.address in configured:
                continue
            candidates[info.address] = f"{info.name or 'Bed'} ({info.address})"

        return candidates

    # -- naming + verification --------------------------------------------

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a name, then verify we can actually reach the bed."""
        assert self._address is not None

        if user_input is None:
            suggested = self._name or self._default_name()
            return self.async_show_form(
                step_id="configure",
                data_schema=vol.Schema(
                    {vol.Required(CONF_NAME, default=suggested): str}
                ),
                description_placeholders={"address": self._address},
            )

        self._name = user_input[CONF_NAME]
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify connectivity, guiding the user through a power-cycle on failure.

        Some bases only accept a new central after being power-cycled, so a
        failure here is recoverable rather than fatal.
        """
        assert self._address is not None and self._name is not None

        # First pass: plain connect. On retry (after the user power-cycles),
        # also attempt to pair -- these bases typically only accept a new bond
        # during a short window after power-on.
        error = await self._async_test_connection(pair=user_input is not None)
        if error is None:
            data = {CONF_ADDRESS: self._address, CONF_NAME: self._name}
            if self._last_good_source:
                data[CONF_LAST_GOOD_SOURCE] = self._last_good_source
            return self.async_create_entry(title=self._name, data=data)

        # Still failing: show the power-cycle instructions. Submitting the form
        # retries this step, so the user can loop until the bed comes up.
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            errors={"base": "cannot_connect"},
            description_placeholders={"error": error},
        )

    async def _async_test_connection(self, pair: bool = False) -> str | None:
        """Return None on success, or a human-readable error string.

        With `pair=True` a bond is attempted. A bond is held against the
        adapter or proxy that creates it, so whichever one succeeds here is
        recorded as this bed's route.
        """
        assert self._address is not None

        @callback
        def _ble_device():
            return bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )

        if _ble_device() is None:
            return async_reachability_hint(self.hass, self._address) or (
                "The bed is not visible to any connectable Bluetooth adapter or "
                "proxy right now."
            )

        bed = ResidentBed(
            address=self._address,
            name=self._name or self._address,
            ble_device_callback=_ble_device,
            always_connected=False,
            pair=pair,
        )
        try:
            await bed.async_connect()
        except ResidentBedError as err:
            return str(err)
        except Exception as err:  # never leave the flow hanging
            _LOGGER.exception("Unexpected error while verifying the bed connection")
            return str(err)
        finally:
            self._last_good_source = bed.last_route
            await bed.async_disconnect()

        return None

    def _default_name(self) -> str:
        if self._discovery_info is not None and self._discovery_info.name:
            return self._discovery_info.name
        return "Resident Bed"

    # -- options -----------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> ResidentBedOptionsFlow:
        return ResidentBedOptionsFlow()


class ResidentBedOptionsFlow(OptionsFlow):
    """Connection-behaviour options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ALWAYS_CONNECTED,
                        default=options.get(
                            CONF_ALWAYS_CONNECTED, DEFAULT_ALWAYS_CONNECTED
                        ),
                    ): bool,
                    vol.Required(
                        CONF_KEEPALIVE,
                        default=options.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_KEEPALIVE, max=MAX_KEEPALIVE),
                    ),
                    vol.Required(
                        CONF_PAIR,
                        default=options.get(CONF_PAIR, DEFAULT_PAIR),
                    ): bool,
                    vol.Required(
                        CONF_PREFERRED_SOURCE,
                        default=options.get(
                            CONF_PREFERRED_SOURCE, AUTOMATIC_SOURCE
                        ),
                    ): vol.In(self._source_choices()),
                }
            ),
        )

    def _source_choices(self) -> dict[str, str]:
        """Adapters and proxies that can currently see this bed, best first.

        Built from the live instance, so it reflects whatever hardware is
        actually present rather than any assumed layout.
        """
        address = self.config_entry.data.get(CONF_ADDRESS) or self.config_entry.data.get(
            "mac"
        )
        choices = {AUTOMATIC_SOURCE: "Automatic (strongest signal)"}
        if not address:
            return choices

        devices = list(
            bluetooth.async_scanner_devices_by_address(
                self.hass, address, connectable=True
            )
        )
        devices.sort(
            key=lambda d: d.advertisement.rssi if d.advertisement else -127,
            reverse=True,
        )
        for device in devices:
            rssi = device.advertisement.rssi if device.advertisement else "?"
            choices[device.scanner.source] = (
                f"{device.scanner.name or device.scanner.source} ({rssi} dBm)"
            )

        # Keep a previously chosen source selectable even if it cannot see the
        # bed right now, so opening the form does not silently reset the pin.
        current = self.config_entry.options.get(CONF_PREFERRED_SOURCE)
        if current and current not in choices:
            choices[current] = f"{current} (not currently visible)"

        return choices
