"""Config flow for the Spin EV Charger integration."""

import asyncio
from ipaddress import ip_address
import logging
import re
from typing import Any, override

from habluetooth import HaBleakClientWrapper
from spinev_ble import (
    ADVERTISED_NAME_PATTERN,
    BleTransport,
    OcppConfig,
    SpinEvCharger,
    SpinEvError,
)
import voluptuous as vol

from homeassistant.components import bluetooth, network
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ADDRESS, CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_CHARGE_POINT_ID,
    CONF_CONNECTION_MODE,
    CONF_SERIAL,
    CONF_TRANSPORT,
    CONNECTION_MODES,
    DEFAULT_CONNECTION_MODE,
    DEFAULT_OCPP_PATH,
    DOMAIN,
    OCPP_CONNECT_TIMEOUT,
    TRANSPORT_BLE,
    TRANSPORT_OCPP,
)
from .coordinator import SpinEvConfigEntry
from .hub import OcppHubError, async_get_hub
from .util import is_same_charger, mask

_LOGGER = logging.getLogger(__name__)

#: Prefix that tells the charger its OCPP host is a name to resolve.
DNS_PREFIX = "dns:"

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_MODE): SelectSelector(
            SelectSelectorConfig(
                options=CONNECTION_MODES,
                mode=SelectSelectorMode.LIST,
                translation_key=CONF_CONNECTION_MODE,
            )
        )
    }
)

HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


def serial_from_name(name: str | None) -> str | None:
    """Return the serial from an advertised name, or None if it is not one.

    The service UUID the charger advertises is a generic serial over BLE
    tunnel used by many unrelated devices, so the name is what actually tells
    a charger apart from them.
    """
    if name is None or not re.match(ADVERTISED_NAME_PATTERN, name):
        return None
    return name.strip().split("_")[0]


def charger_host(host: str) -> str:
    """Return ``host`` the way the charger stores it.

    The charger takes an IP address as is, and needs a name marked as one.
    """
    host = host.strip()
    try:
        ip_address(host)
    except ValueError:
        return f"{DNS_PREFIX}{host}"
    return host


def display_host(host: str) -> str:
    """Return a host the charger stores, as a person would write it."""
    return host.removeprefix(DNS_PREFIX)


def ocpp_url(config: OcppConfig) -> str:
    """Return the address the charger connects to for OCPP."""
    path = f"/{config.path.strip('/')}" if config.path.strip("/") else ""
    return (
        f"ws://{display_host(config.host)}:{config.port}{path}/{config.charge_point_id}"
    )


class SpinEvOptionsFlow(OptionsFlowWithReload):
    """Handle the options for a charger."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how the Bluetooth link is held."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA,
                {
                    CONF_CONNECTION_MODE: self.config_entry.options.get(
                        CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE
                    )
                },
            ),
        )


class SpinEvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Spin EV Charger.

    A charger is set up over Bluetooth, over Bluetooth and then moved to OCPP,
    or over OCPP alone. Moving to OCPP points the charger at the central
    system this integration runs, over Bluetooth, so the phone app is not
    needed.
    """

    VERSION = 1
    MINOR_VERSION = 2

    _address: str
    _serial: str

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered: dict[str, str] = {}
        self._holds_hub = False
        self._current: OcppConfig | None = None
        self._charge_point_id: str | None = None
        self._wait_task: asyncio.Task[bool] | None = None
        self._ocpp_candidates: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(entry: SpinEvConfigEntry) -> SpinEvOptionsFlow:
        """Return the options flow."""
        return SpinEvOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Offer the Bluetooth options only to chargers reached over Bluetooth."""
        # Asked of entries that were never set up, so never migrated either.
        return bool(config_entry.data.get(CONF_TRANSPORT) != TRANSPORT_OCPP)

    @callback
    @override
    def async_remove(self) -> None:
        """Let go of the central system when the flow ends."""
        if self._wait_task is not None:
            self._wait_task.cancel()
        if self._holds_hub:
            self._holds_hub = False
            async_get_hub(self.hass).async_release()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to reach the charger."""
        return self.async_show_menu(
            step_id="user", menu_options=["pick_bluetooth", "ocpp"]
        )

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
        self._abort_if_serial_configured(serial)

        self._address = discovery_info.address
        self._serial = serial
        self.context["title_placeholders"] = {"name": serial}

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered charger."""
        if user_input is not None:
            if await self._async_charger_answers(self._address, self._serial):
                return await self.async_step_transport()
            # There is nothing to correct on a confirm step, so a charger that
            # will not answer ends the flow rather than looping on itself.
            return self.async_abort(reason="cannot_connect")

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._serial},
        )

    async def async_step_pick_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a charger from the ones already seen."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            serial = self._discovered[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._abort_if_serial_configured(serial)
            if await self._async_charger_answers(address, serial):
                self._address = address
                self._serial = serial
                return await self.async_step_transport()
            errors["base"] = "cannot_connect"
        else:
            # The charger only answers a connectable scan, and a passive-only
            # adapter will not have it in range yet on the first pass.
            await bluetooth.async_request_active_scan(self.hass)

            current = self._async_current_ids(include_ignore=False)
            for info in async_discovered_service_info(self.hass, connectable=True):
                if info.address in current:
                    continue
                if (found := serial_from_name(info.name)) is not None:
                    self._discovered[info.address] = found

            if not self._discovered:
                return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="pick_bluetooth",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
            errors=errors,
        )

    async def async_step_transport(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between staying on Bluetooth and moving to OCPP."""
        return self.async_show_menu(
            step_id="transport",
            menu_options=["bluetooth_to_ocpp", "finish_bluetooth"],
            description_placeholders={"name": self._serial},
        )

    async def async_step_finish_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Store a charger reached over Bluetooth."""
        return self.async_create_entry(
            title=self._serial,
            data={
                CONF_ADDRESS: self._address,
                CONF_SERIAL: self._serial,
                CONF_TRANSPORT: TRANSPORT_BLE,
            },
            options={CONF_CONNECTION_MODE: DEFAULT_CONNECTION_MODE},
        )

    async def async_step_bluetooth_to_ocpp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the charger at this central system, over Bluetooth."""
        return await self._async_step_point_at_hub("bluetooth_to_ocpp", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move a charger to OCPP, repoint it, or move it back to Bluetooth."""
        entry = self._get_reconfigure_entry()
        if (
            entry.data.get(CONF_TRANSPORT) == TRANSPORT_OCPP
            and CONF_ADDRESS in entry.data
        ):
            return self.async_show_menu(
                step_id="reconfigure",
                menu_options=["reconfigure_ocpp", "reconfigure_bluetooth"],
            )
        return await self.async_step_reconfigure_ocpp()

    async def async_step_reconfigure_ocpp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point a configured charger at this central system."""
        entry = self._get_reconfigure_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        self._serial = entry.data[CONF_SERIAL]
        return await self._async_step_point_at_hub("reconfigure_ocpp", user_input)

    async def async_step_reconfigure_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reach a charger over Bluetooth again instead of OCPP."""
        if user_input is None:
            return self.async_show_form(step_id="reconfigure_bluetooth")
        return self.async_update_reload_and_abort(
            self._get_reconfigure_entry(),
            data_updates={CONF_TRANSPORT: TRANSPORT_BLE},
        )

    async def _async_step_point_at_hub(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Read where the charger connects, then point it here once confirmed.

        The host suggested is this Home Assistant's own address. Nothing is
        written, and the charger is not restarted, if it already connects here.
        """
        if not await self._async_hold_hub():
            if self.source == SOURCE_RECONFIGURE:
                return self.async_abort(reason="ocpp_port_in_use")
            return await self.async_step_ocpp_port_in_use()
        errors: dict[str, str] = {}

        if self._current is None:
            try:
                self._current = await self._async_read_ocpp_config()
            except (SpinEvError, HomeAssistantError) as err:
                _LOGGER.debug(
                    "Could not read the OCPP settings of charger %s: %s",
                    mask(self._serial),
                    err,
                )
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_abort(reason="cannot_connect")
                return await self.async_step_ocpp_read_failed()
            _LOGGER.debug(
                "Charger %s connects for OCPP on port %s, %s charge point id",
                mask(self._serial),
                self._current.port,
                "with a" if self._current.charge_point_id else "without a",
            )

        current = self._current
        port = async_get_hub(self.hass).port
        self._charge_point_id = current.charge_point_id or self._serial

        if user_input is not None and not user_input[CONF_HOST].strip():
            errors[CONF_HOST] = "invalid_host"
        elif user_input is not None:
            wanted = OcppConfig(
                host=charger_host(user_input[CONF_HOST]),
                port=port,
                path=current.path or DEFAULT_OCPP_PATH,
                charge_point_id=self._charge_point_id,
            )
            if wanted == current:
                _LOGGER.debug(
                    "Charger %s already connects here, leaving it as it is",
                    mask(self._serial),
                )
                return await self.async_step_ocpp_wait()
            _LOGGER.debug(
                "Pointing charger %s at port %s; it restarts to apply this",
                mask(self._serial),
                port,
            )
            try:
                await self._async_write_ocpp_config(wanted)
            except (SpinEvError, HomeAssistantError) as err:
                _LOGGER.debug(
                    "Could not write the OCPP settings of charger %s: %s",
                    mask(self._serial),
                    err,
                )
                if self.source != SOURCE_RECONFIGURE:
                    return await self.async_step_ocpp_write_failed()
                errors["base"] = "cannot_connect"
            else:
                self._current = wanted
                return await self.async_step_ocpp_wait()

        suggested = await network.async_get_source_ip(self.hass)
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                HOST_SCHEMA, {CONF_HOST: suggested}
            ),
            description_placeholders={
                "name": self._serial,
                "current": ocpp_url(current) if current.host else "-",
                "port": str(port),
            },
            errors=errors,
        )

    async def async_step_ocpp_port_in_use(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer Bluetooth when the central system cannot listen."""
        return self._async_show_ocpp_fallback("ocpp_port_in_use")

    async def async_step_ocpp_read_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer Bluetooth when the charger's OCPP settings could not be read."""
        return self._async_show_ocpp_fallback("ocpp_read_failed")

    async def async_step_ocpp_write_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer Bluetooth when the charger could not be pointed here."""
        return self._async_show_ocpp_fallback("ocpp_write_failed")

    @callback
    def _async_show_ocpp_fallback(self, step_id: str) -> ConfigFlowResult:
        """Offer to try OCPP again, or to set the charger up over Bluetooth."""
        return self.async_show_menu(
            step_id=step_id,
            menu_options=["bluetooth_to_ocpp", "finish_bluetooth"],
            description_placeholders={
                "name": self._serial,
                "port": str(async_get_hub(self.hass).port),
            },
        )

    async def async_step_ocpp_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait for the charger to connect to the central system."""
        if self._charge_point_id is None:
            raise RuntimeError("no charge point to wait for")
        if self._wait_task is None:
            self._wait_task = self.hass.async_create_task(
                async_get_hub(self.hass).async_wait_connected(
                    self._charge_point_id, OCPP_CONNECT_TIMEOUT.total_seconds()
                )
            )
        if not self._wait_task.done():
            return self.async_show_progress(
                step_id="ocpp_wait",
                progress_action="ocpp_wait",
                progress_task=self._wait_task,
                description_placeholders={"name": self._serial},
            )
        connected = self._wait_task.result()
        self._wait_task = None
        _LOGGER.debug(
            "Charger %s %s",
            mask(self._charge_point_id),
            "connected" if connected else "did not connect in time",
        )
        return self.async_show_progress_done(
            next_step_id="ocpp_finish" if connected else "ocpp_timeout"
        )

    async def async_step_ocpp_timeout(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to wait longer, keep OCPP anyway, or stay on Bluetooth."""
        options = ["ocpp_wait", "ocpp_finish"]
        if self.source != SOURCE_RECONFIGURE:
            options.append("finish_bluetooth")
        return self.async_show_menu(
            step_id="ocpp_timeout",
            menu_options=options,
            description_placeholders={"name": self._serial},
        )

    async def async_step_ocpp_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Store a charger reached over OCPP."""
        ocpp_data = {
            CONF_TRANSPORT: TRANSPORT_OCPP,
            CONF_CHARGE_POINT_ID: self._charge_point_id,
        }
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=ocpp_data
            )
        return self.async_create_entry(
            title=self._serial,
            data={CONF_ADDRESS: self._address, CONF_SERIAL: self._serial, **ocpp_data},
        )

    async def async_step_ocpp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show where to point a charger, then pick it once it has connected."""
        if not await self._async_hold_hub():
            return self.async_abort(reason="ocpp_port_in_use")
        errors: dict[str, str] = {}

        if user_input is not None:
            entries = self._async_current_entries(include_ignore=False)
            self._ocpp_candidates = {
                charge_point_id: charge_point_id
                for charge_point_id in async_get_hub(self.hass).connected_ids()
                if not any(
                    is_same_charger(entry.data, charge_point_id) for entry in entries
                )
            }
            _LOGGER.debug(
                "%s new chargers connected over OCPP", len(self._ocpp_candidates)
            )
            if self._ocpp_candidates:
                return await self.async_step_ocpp_pick()
            errors["base"] = "no_charger_connected"

        host = await network.async_get_source_ip(self.hass)
        return self.async_show_form(
            step_id="ocpp",
            description_placeholders={
                "host": host,
                "port": str(async_get_hub(self.hass).port),
                "path": DEFAULT_OCPP_PATH,
            },
            errors=errors,
        )

    async def async_step_ocpp_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one of the chargers connected to the central system."""
        if user_input is not None:
            return await self._async_create_ocpp_only(user_input[CONF_CHARGE_POINT_ID])
        return self.async_show_form(
            step_id="ocpp_pick",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHARGE_POINT_ID): vol.In(self._ocpp_candidates)}
            ),
        )

    @override
    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle a charger that connected to the central system unasked."""
        charge_point_id: str = discovery_info[CONF_CHARGE_POINT_ID]
        await self.async_set_unique_id(charge_point_id)
        self._abort_if_unique_id_configured()
        self._abort_if_charge_point_configured(charge_point_id)
        self._charge_point_id = charge_point_id
        self.context["title_placeholders"] = {"name": charge_point_id}
        return await self.async_step_ocpp_discovery_confirm()

    async def async_step_ocpp_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a charger discovered over OCPP."""
        if self._charge_point_id is None:
            raise RuntimeError("no charge point discovered")
        if user_input is not None:
            return await self._async_create_ocpp_only(self._charge_point_id)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="ocpp_discovery_confirm",
            description_placeholders={"name": self._charge_point_id},
        )

    async def _async_create_ocpp_only(self, charge_point_id: str) -> ConfigFlowResult:
        """Store a charger reached over OCPP alone, keyed by its charge point id."""
        await self.async_set_unique_id(charge_point_id, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        self._abort_if_charge_point_configured(charge_point_id)
        charge_point = async_get_hub(self.hass).charge_point(charge_point_id)
        serial = charge_point_id
        if charge_point is not None and charge_point.boot is not None:
            serial = charge_point.boot.serial_number or charge_point_id
        return self.async_create_entry(
            title=serial,
            data={
                CONF_SERIAL: serial,
                CONF_TRANSPORT: TRANSPORT_OCPP,
                CONF_CHARGE_POINT_ID: charge_point_id,
            },
        )

    @callback
    def _abort_if_serial_configured(self, serial: str) -> None:
        """Abort if a charger set up over OCPP alone has this serial."""
        for entry in self._async_current_entries(include_ignore=False):
            charge_point_id: str | None = entry.data.get(CONF_CHARGE_POINT_ID)
            if charge_point_id is not None and charge_point_id.endswith(serial):
                raise AbortFlow("already_configured")

    @callback
    def _abort_if_charge_point_configured(self, charge_point_id: str) -> None:
        """Abort if any entry, over either transport, is this charger."""
        for entry in self._async_current_entries(include_ignore=False):
            if is_same_charger(entry.data, charge_point_id):
                raise AbortFlow("already_configured")

    async def _async_hold_hub(self) -> bool:
        """Hold the central system for this flow, returning False if it fails."""
        if self._holds_hub:
            return True
        try:
            await async_get_hub(self.hass).async_acquire()
        except OcppHubError as err:
            _LOGGER.warning("Could not start the OCPP central system: %s", err)
            return False
        self._holds_hub = True
        return True

    async def _async_read_ocpp_config(self) -> OcppConfig:
        """Read the charger's OCPP settings, through its entry if it has one."""
        if self.source == SOURCE_RECONFIGURE:
            entry: SpinEvConfigEntry = self._get_reconfigure_entry()
            return await entry.runtime_data.async_get_ocpp_config()
        async with self._ble_charger() as charger:
            return await charger.async_get_ocpp_config()

    async def _async_write_ocpp_config(self, config: OcppConfig) -> None:
        """Write the charger's OCPP settings, restarting it."""
        if self.source == SOURCE_RECONFIGURE:
            entry: SpinEvConfigEntry = self._get_reconfigure_entry()
            await entry.runtime_data.async_set_ocpp_config(config)
            return
        async with self._ble_charger() as charger:
            await charger.async_set_ocpp_config(config)

    def _ble_charger(self) -> SpinEvCharger:
        """Return a client for the charger this flow found over Bluetooth."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            raise HomeAssistantError("the charger is out of Bluetooth range")
        return SpinEvCharger(
            BleTransport(ble_device, client_class=HaBleakClientWrapper)
        )

    async def _async_charger_answers(self, address: str, serial: str) -> bool:
        """Return True if the charger is in range and replies to a read."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device is None:
            return False

        charger = SpinEvCharger(
            BleTransport(ble_device, client_class=HaBleakClientWrapper)
        )
        try:
            async with charger:
                await charger.async_get_state_value()
        except SpinEvError as err:
            _LOGGER.debug("Could not reach charger %s: %s", mask(serial), err)
            return False
        return True
