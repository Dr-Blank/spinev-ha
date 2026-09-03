"""Config flow for the Spin EV Charger integration."""

import logging
import re
from typing import Any, override

from habluetooth import HaBleakClientWrapper
from spinev_ble import ADVERTISED_NAME_PATTERN, SpinEvCharger, SpinEvError
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_CHARGING_INTERVAL,
    CONF_CONNECTION_MODE,
    CONF_IDLE_INTERVAL,
    CONF_SERIAL,
    CONNECTION_MODES,
    DEFAULT_CHARGING_INTERVAL,
    DEFAULT_CONNECTION_MODE,
    DEFAULT_IDLE_INTERVAL,
    DOCS_CONNECTION_URL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .coordinator import SpinEvConfigEntry

_LOGGER = logging.getLogger(__name__)


def _interval_selector() -> NumberSelector:
    """Build a bounded, whole-second interval selector."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_POLL_INTERVAL,
            max=MAX_POLL_INTERVAL,
            step=30,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_MODE): SelectSelector(
            SelectSelectorConfig(
                options=CONNECTION_MODES,
                mode=SelectSelectorMode.LIST,
                translation_key=CONF_CONNECTION_MODE,
            )
        ),
        vol.Required(CONF_CHARGING_INTERVAL): _interval_selector(),
        vol.Required(CONF_IDLE_INTERVAL): _interval_selector(),
    }
)


def serial_from_name(name: str | None) -> str | None:
    """Return the serial from an advertised name, or None if it is not one.

    The service UUID the charger advertises is a generic serial over BLE
    tunnel used by many unrelated devices, so the name is what actually tells
    a charger apart from them.
    """
    if name is None or not re.match(ADVERTISED_NAME_PATTERN, name):
        return None
    return name.strip().split("_")[0]


class SpinEvOptionsFlow(OptionsFlow):
    """Handle the options for a charger."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how the Bluetooth link is held and how often to poll."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_IDLE_INTERVAL] < user_input[CONF_CHARGING_INTERVAL]:
                errors["base"] = "idle_interval_too_short"
            else:
                return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA,
                user_input
                or {
                    CONF_CONNECTION_MODE: options.get(
                        CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE
                    ),
                    CONF_CHARGING_INTERVAL: options.get(
                        CONF_CHARGING_INTERVAL, DEFAULT_CHARGING_INTERVAL
                    ),
                    CONF_IDLE_INTERVAL: options.get(
                        CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL
                    ),
                },
            ),
            errors=errors,
        )


class SpinEvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Spin EV Charger."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._address: str | None = None
        self._serial: str | None = None
        self._discovered: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(entry: SpinEvConfigEntry) -> SpinEvOptionsFlow:
        """Return the options flow."""
        return SpinEvOptionsFlow()

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a charger discovered over Bluetooth."""
        serial = serial_from_name(discovery_info.name)
        if serial is None:
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address
        self._serial = serial
        self.context["title_placeholders"] = {"name": serial}

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered charger."""
        assert self._address is not None
        assert self._serial is not None

        if user_input is not None:
            return await self._async_create(self._address, self._serial)

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._serial},
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a charger from the ones already seen."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self._async_create(address, self._discovered[address])

        current = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in current:
                continue
            if (serial := serial_from_name(info.name)) is not None:
                self._discovered[info.address] = serial

        if not self._discovered:
            return self.async_abort(
                reason="no_devices_found",
                description_placeholders={"docs_url": DOCS_CONNECTION_URL},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
        )

    async def _async_create(self, address: str, serial: str) -> ConfigFlowResult:
        """Check the charger answers, then store it."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device is None:
            return self.async_abort(
                reason="cannot_connect",
                description_placeholders={"docs_url": DOCS_CONNECTION_URL},
            )

        charger = SpinEvCharger(ble_device, client_class=HaBleakClientWrapper)
        try:
            async with charger:
                await charger.async_get_state_value()
        except SpinEvError as err:
            _LOGGER.debug("Could not reach charger %s: %s", serial, err)
            return self.async_abort(
                reason="cannot_connect",
                description_placeholders={"docs_url": DOCS_CONNECTION_URL},
            )

        return self.async_create_entry(
            title=serial,
            data={CONF_ADDRESS: address, CONF_SERIAL: serial},
            options={
                CONF_CONNECTION_MODE: DEFAULT_CONNECTION_MODE,
                CONF_CHARGING_INTERVAL: DEFAULT_CHARGING_INTERVAL,
                CONF_IDLE_INTERVAL: DEFAULT_IDLE_INTERVAL,
            },
        )
