"""Tests for the Spin EV Charger config flow."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from spinev_ble import SpinEvError

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .const import ADDRESS, ENTRY_DATA, ENTRY_OPTIONS, SERIAL
from custom_components.spinev.const import (
    CONF_CHARGING_INTERVAL,
    CONF_CONNECTION_MODE,
    CONF_IDLE_INTERVAL,
    CONF_SERIAL,
    DOMAIN,
    MODE_PERSISTENT,
)


@contextmanager
def patch_discovered(
    service_infos: list[BluetoothServiceInfoBleak],
) -> Iterator[None]:
    """Pretend the Bluetooth manager has seen exactly these devices."""
    with patch(
        "custom_components.spinev.config_flow.async_discovered_service_info",
        return_value=service_infos,
    ):
        yield


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_bluetooth_discovery(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """A discovered charger is confirmed and stored with sane defaults."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {"name": SERIAL}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == SERIAL
    assert result["data"] == ENTRY_DATA
    assert result["options"] == ENTRY_OPTIONS
    assert result["result"].unique_id == ADDRESS


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_discovery_of_another_device_on_the_same_service_uuid(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """The advertised service UUID is generic, so the name is what decides."""
    service_info.name = "Some other serial-over-BLE gadget"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_discovery_of_a_configured_charger(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A charger that is already set up is not offered again."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_ble_device")
async def test_discovery_when_the_charger_does_not_answer(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """A charger held by the phone app cannot be set up yet."""
    mock_charger.async_get_state_value.side_effect = SpinEvError("busy")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("mock_charger")
async def test_discovery_when_the_charger_is_out_of_range(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_ble_device: MagicMock,
) -> None:
    """An address the Bluetooth manager no longer resolves cannot be set up."""
    mock_ble_device.return_value = None

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_user_flow(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """A charger already seen by the Bluetooth manager can be picked by hand."""
    with patch_discovered([service_info]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == SERIAL
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_SERIAL: SERIAL}


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_user_flow_with_nothing_to_offer(hass: HomeAssistant) -> None:
    """Nothing recognisable in range means there is nothing to configure."""
    with patch_discovered([]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_user_flow_skips_configured_chargers(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A charger that is already set up is not offered in the picker."""
    mock_config_entry.add_to_hass(hass)

    with patch_discovered([service_info]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_options_flow(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Options are stored, and the entry reloads so they take effect."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CONNECTION_MODE: MODE_PERSISTENT,
            CONF_CHARGING_INTERVAL: 30,
            CONF_IDLE_INTERVAL: 600,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {
        CONF_CONNECTION_MODE: MODE_PERSISTENT,
        CONF_CHARGING_INTERVAL: 30,
        CONF_IDLE_INTERVAL: 600,
    }


async def test_options_flow_rejects_a_short_idle_interval(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Idling faster than charging defeats the point of the idle interval."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CONNECTION_MODE: MODE_PERSISTENT,
            CONF_CHARGING_INTERVAL: 300,
            CONF_IDLE_INTERVAL: 60,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "idle_interval_too_short"}
