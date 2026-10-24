"""Tests for the Spin EV Charger config flow."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from ocpp_csms import CsmsConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from spinev_ble import OcppConfig, SpinEvError

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    SOURCE_BLUETOOTH,
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
)
from homeassistant.const import CONF_ADDRESS, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType

from .conftest import ConnectCharger
from .const import (
    ADDRESS,
    CHARGE_POINT_ID,
    ENTRY_DATA,
    ENTRY_OPTIONS,
    HA_HOST,
    OCPP_ENTRY_DATA,
    OCPP_ONLY_ENTRY_DATA,
    PRE_OCPP_ENTRY_DATA,
    SERIAL,
)
from custom_components.spinev.const import (
    CONF_CHARGE_POINT_ID,
    CONF_CONNECTION_MODE,
    CONF_SERIAL,
    CONF_TRANSPORT,
    DOMAIN,
    MODE_PERSISTENT,
    TRANSPORT_BLE,
)
from custom_components.spinev.hub import async_get_hub


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


def suggested_host(result: FlowResult) -> str:
    """Return the host a form suggests."""
    schema = result["data_schema"]
    assert schema is not None
    (key,) = schema.schema
    return str(key.description["suggested_value"])


def ha_ocpp_config(hass: HomeAssistant, host: str = HA_HOST) -> OcppConfig:
    """Return the settings that point the charger at Home Assistant."""
    return OcppConfig(
        host=host,
        port=async_get_hub(hass).port,
        path="ocpp",
        charge_point_id=CHARGE_POINT_ID,
    )


async def start_discovered(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> FlowResult:
    """Confirm a discovered charger, ending on the transport menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def start_moving_to_ocpp(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> FlowResult:
    """Confirm a discovered charger and choose OCPP, ending on the host form."""
    result = await start_discovered(hass, service_info)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bluetooth_to_ocpp"}
    )


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_bluetooth_discovery(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """A discovered charger can stay on Bluetooth, with sane defaults."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {"name": SERIAL}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "transport"
    assert result["menu_options"] == ["bluetooth_to_ocpp", "finish_bluetooth"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

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


@pytest.mark.parametrize(
    ("unique_id", "data"),
    [
        pytest.param(ADDRESS, ENTRY_DATA, id="same-address"),
        pytest.param(CHARGE_POINT_ID, OCPP_ONLY_ENTRY_DATA, id="set-up-over-ocpp"),
    ],
)
@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_discovery_of_a_configured_charger(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    unique_id: str,
    data: dict[str, str],
) -> None:
    """A charger that is already set up, either way, is not offered again."""
    MockConfigEntry(
        domain=DOMAIN, unique_id=unique_id, data=data, minor_version=2
    ).add_to_hass(hass)

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

    result = await start_discovered(hass, service_info)

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

    result = await start_discovered(hass, service_info)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def start_user_bluetooth(hass: HomeAssistant) -> FlowResult:
    """Start a flow by hand and choose Bluetooth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["pick_bluetooth", "ocpp"]

    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "pick_bluetooth"}
    )


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_user_flow(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """A charger already seen by the Bluetooth manager can be picked by hand."""
    with patch_discovered([service_info]):
        result = await start_user_bluetooth(hass)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "pick_bluetooth"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "transport"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == SERIAL
    assert result["data"] == ENTRY_DATA


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_user_flow_with_nothing_to_offer(hass: HomeAssistant) -> None:
    """Nothing recognisable in range means there is nothing to configure."""
    with patch_discovered([]):
        result = await start_user_bluetooth(hass)

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
        result = await start_user_bluetooth(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


@pytest.mark.usefixtures("mock_ble_device")
async def test_user_flow_when_the_charger_does_not_answer(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """The picker comes back with an error so the charger can be tried again."""
    mock_charger.async_get_state_value.side_effect = SpinEvError("busy")

    with patch_discovered([service_info]):
        result = await start_user_bluetooth(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "pick_bluetooth"
        assert result["errors"] == {"base": "cannot_connect"}

        mock_charger.async_get_state_value.side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "transport"


@pytest.mark.parametrize(
    ("host", "stored_host"),
    [
        pytest.param(HA_HOST, HA_HOST, id="ip-address"),
        pytest.param("ha.example.com", "dns:ha.example.com", id="host-name"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_to_ocpp(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
    connect_charger: ConnectCharger,
    host: str,
    stored_host: str,
) -> None:
    """The charger is pointed at Home Assistant over Bluetooth, then waited for."""
    result = await start_moving_to_ocpp(hass, service_info)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_to_ocpp"
    assert result["description_placeholders"] == {
        "name": SERIAL,
        "current": f"ws://ocpp.example.com:443/ocpp/{CHARGE_POINT_ID}",
        "port": str(async_get_hub(hass).port),
    }
    # The detected address is offered, to confirm or override.
    assert suggested_host(result) == HA_HOST

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: host}
    )

    mock_charger.async_set_ocpp_config.assert_awaited_once_with(
        ha_ocpp_config(hass, stored_host)
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "ocpp_wait"

    await connect_charger(CHARGE_POINT_ID)
    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == SERIAL
    assert result["data"] == OCPP_ENTRY_DATA
    assert result["result"].unique_id == ADDRESS


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_to_ocpp_keeps_a_charger_already_pointed_here(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
    connect_charger: ConnectCharger,
) -> None:
    """A charger that already connects here is neither written nor restarted."""
    result = await start_discovered(hass, service_info)
    # The flow holds the central system from here, so the charger can connect.
    await async_get_hub(hass).async_acquire()
    mock_charger.async_get_ocpp_config.return_value = ha_ocpp_config(hass)
    await connect_charger(CHARGE_POINT_ID)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bluetooth_to_ocpp"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HA_HOST}
    )

    mock_charger.async_set_ocpp_config.assert_not_awaited()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == OCPP_ENTRY_DATA
    async_get_hub(hass).async_release()


async def time_out_moving_to_ocpp(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> FlowResult:
    """Point a discovered charger here and let it fail to connect."""
    with patch("custom_components.spinev.config_flow.OCPP_CONNECT_TIMEOUT") as timeout:
        timeout.total_seconds.return_value = 0.01
        result = await start_moving_to_ocpp(hass, service_info)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HA_HOST}
        )
        await hass.async_block_till_done()
        return await hass.config_entries.flow.async_configure(result["flow_id"])


@pytest.mark.parametrize(
    ("next_step_id", "data"),
    [
        pytest.param("ocpp_finish", OCPP_ENTRY_DATA, id="use-ocpp-anyway"),
        pytest.param("finish_bluetooth", ENTRY_DATA, id="stay-on-bluetooth"),
    ],
)
@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_bluetooth_to_ocpp_when_the_charger_does_not_connect(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    next_step_id: str,
    data: dict[str, str],
) -> None:
    """A charger that never connects can still be kept on either transport."""
    result = await time_out_moving_to_ocpp(hass, service_info)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ocpp_timeout"
    assert result["menu_options"] == ["ocpp_wait", "ocpp_finish", "finish_bluetooth"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": next_step_id}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == data


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_after_a_timeout_restores_the_ocpp_settings(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """A charger kept on Bluetooth goes back to where it connected before."""
    original = mock_charger.async_get_ocpp_config.return_value
    result = await time_out_moving_to_ocpp(hass, service_info)

    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert mock_charger.async_set_ocpp_config.await_count == 2
    mock_charger.async_set_ocpp_config.assert_awaited_with(original)


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_after_a_timeout_leaves_a_charger_pointed_here_before(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """Settings this flow never changed are not written back."""
    # Holding the central system first gives it the port the settings name.
    await async_get_hub(hass).async_acquire()
    mock_charger.async_get_ocpp_config.return_value = ha_ocpp_config(hass)
    result = await time_out_moving_to_ocpp(hass, service_info)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_charger.async_set_ocpp_config.assert_not_awaited()
    async_get_hub(hass).async_release()


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_after_a_timeout_when_restoring_fails(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """A failed restore can be tried again, or skipped."""
    result = await time_out_moving_to_ocpp(hass, service_info)
    mock_charger.async_set_ocpp_config.side_effect = SpinEvError("busy")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ocpp_restore_failed"
    assert result["menu_options"] == ["finish_bluetooth", "finish_bluetooth_as_is"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth_as_is"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_to_ocpp_when_reading_fails(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """A charger that cannot be read is not written blind, and can stay on Bluetooth."""
    mock_charger.async_get_ocpp_config.side_effect = SpinEvError("busy")

    result = await start_moving_to_ocpp(hass, service_info)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ocpp_read_failed"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA
    mock_charger.async_set_ocpp_config.assert_not_awaited()


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_to_ocpp_with_an_empty_host(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """An empty address is never written to the charger."""
    result = await start_moving_to_ocpp(hass, service_info)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "  "}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}
    mock_charger.async_set_ocpp_config.assert_not_awaited()


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_to_ocpp_when_writing_fails(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """A failed write can be tried again, without reading the charger twice."""
    mock_charger.async_set_ocpp_config.side_effect = SpinEvError("busy")

    result = await start_moving_to_ocpp(hass, service_info)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HA_HOST}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ocpp_write_failed"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bluetooth_to_ocpp"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_to_ocpp"
    mock_charger.async_get_ocpp_config.assert_awaited_once()


@pytest.mark.usefixtures("mock_ble_device")
async def test_bluetooth_when_writing_fails(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    mock_charger: AsyncMock,
) -> None:
    """A charger that cannot be moved to OCPP is still set up over Bluetooth."""
    mock_charger.async_set_ocpp_config.side_effect = SpinEvError("busy")

    result = await start_moving_to_ocpp(hass, service_info)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HA_HOST}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_bluetooth_to_ocpp_when_the_port_is_taken(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """A central system that cannot listen still lets Bluetooth be used."""
    with patch(
        "custom_components.spinev.hub.CentralSystem.async_start",
        side_effect=CsmsConnectionError("address in use"),
    ):
        result = await start_moving_to_ocpp(hass, service_info)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ocpp_port_in_use"
    assert result["menu_options"] == ["bluetooth_to_ocpp", "finish_bluetooth"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_bluetooth"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA


async def test_ocpp_only(hass: HomeAssistant, connect_charger: ConnectCharger) -> None:
    """A charger pointed here by the phone app is picked once it connects."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ocpp"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ocpp"
    assert result["description_placeholders"] == {
        "host": HA_HOST,
        "port": str(async_get_hub(hass).port),
        "path": "ocpp",
    }

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["errors"] == {"base": "no_charger_connected"}

    await connect_charger(CHARGE_POINT_ID)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ocpp_pick"

    with patch("custom_components.spinev.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CHARGE_POINT_ID: CHARGE_POINT_ID}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == CHARGE_POINT_ID
    assert result["data"] == OCPP_ONLY_ENTRY_DATA
    assert result["result"].unique_id == CHARGE_POINT_ID
    # The discovery the connection raised is answered by this entry.
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_ocpp_only_skips_a_charger_set_up_over_bluetooth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    connect_charger: ConnectCharger,
) -> None:
    """A charger whose id ends with a configured serial is the same charger."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ocpp"}
    )
    await connect_charger(CHARGE_POINT_ID)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["errors"] == {"base": "no_charger_connected"}


async def test_unknown_charger_is_discovered(
    hass: HomeAssistant, connect_charger: ConnectCharger
) -> None:
    """A charger that connects unasked is offered for setup."""
    hub = async_get_hub(hass)
    await hub.async_acquire()

    await connect_charger(CHARGE_POINT_ID)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "ocpp_discovery_confirm"
    assert flows[0]["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY

    with patch("custom_components.spinev.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == OCPP_ONLY_ENTRY_DATA
    hub.async_release()


@pytest.mark.parametrize(
    ("serial", "flows"),
    [
        pytest.param(SERIAL, 0, id="serial-ends-the-id"),
        pytest.param(SERIAL[-4:], 1, id="too-short-to-be-a-serial"),
    ],
)
async def test_charger_set_up_over_bluetooth_is_not_discovered(
    hass: HomeAssistant, connect_charger: ConnectCharger, serial: str, flows: int
) -> None:
    """Only a whole serial at the end of a charge point id ties it to an entry."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={**ENTRY_DATA, CONF_SERIAL: serial},
        minor_version=2,
    ).add_to_hass(hass)
    hub = async_get_hub(hass)
    await hub.async_acquire()

    await connect_charger(CHARGE_POINT_ID)

    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == flows
    hub.async_release()


@pytest.mark.parametrize(
    ("unique_id", "data"),
    [
        pytest.param(ADDRESS, ENTRY_DATA, id="set-up-over-bluetooth"),
        pytest.param(CHARGE_POINT_ID, OCPP_ONLY_ENTRY_DATA, id="set-up-over-ocpp"),
    ],
)
async def test_discovery_over_ocpp_of_a_configured_charger(
    hass: HomeAssistant, unique_id: str, data: dict[str, str]
) -> None:
    """A charger that is already set up, either way, is not offered again."""
    MockConfigEntry(
        domain=DOMAIN, unique_id=unique_id, data=data, minor_version=2
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_CHARGE_POINT_ID: CHARGE_POINT_ID},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# The write restarts the charger; nothing here needs to wait that out.
@patch("custom_components.spinev.coordinator.REBOOT_SETTLE", timedelta(0))
async def test_reconfigure_bluetooth_to_ocpp(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    connect_charger: ConnectCharger,
) -> None:
    """A charger on Bluetooth is read, shown, and moved once confirmed."""
    result = await init_integration.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_ocpp"
    assert result["description_placeholders"]["current"] == (
        f"ws://ocpp.example.com:443/ocpp/{CHARGE_POINT_ID}"
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HA_HOST}
    )

    mock_charger.async_set_ocpp_config.assert_awaited_once_with(ha_ocpp_config(hass))
    assert result["type"] is FlowResultType.SHOW_PROGRESS

    await connect_charger(CHARGE_POINT_ID)
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data == OCPP_ENTRY_DATA
    assert init_integration.runtime_data.over_ocpp


async def test_reconfigure_when_writing_fails(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """A loaded entry stays as it is, so the form is shown again."""
    mock_charger.async_set_ocpp_config.side_effect = SpinEvError("busy")
    result = await init_integration.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HA_HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_ocpp"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_when_the_port_is_taken(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A loaded entry stays as it is, so the flow ends with the reason."""
    with patch(
        "custom_components.spinev.hub.CentralSystem.async_start",
        side_effect=CsmsConnectionError("address in use"),
    ):
        result = await init_integration.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "ocpp_port_in_use"


async def test_reconfigure_back_to_bluetooth(
    hass: HomeAssistant, mock_charger: AsyncMock, mock_ble_device: MagicMock
) -> None:
    """A charger moved to OCPP can be reached over Bluetooth again."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data=OCPP_ENTRY_DATA,
        options=ENTRY_OPTIONS,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["reconfigure_ocpp", "reconfigure_bluetooth"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "reconfigure_bluetooth"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_TRANSPORT] == TRANSPORT_BLE


@pytest.mark.parametrize(
    ("data", "minor_version"),
    [
        pytest.param(ENTRY_DATA, 2, id="migrated"),
        pytest.param(PRE_OCPP_ENTRY_DATA, 1, id="never_set_up"),
    ],
)
async def test_reconfigure_needs_a_working_entry(
    hass: HomeAssistant, data: dict[str, str], minor_version: int
) -> None:
    """The charger is read through its entry, so that must be loaded."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data=data, minor_version=minor_version
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_options_flow(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Options are stored, and the entry reloads so they take effect."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONNECTION_MODE: MODE_PERSISTENT}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {CONF_CONNECTION_MODE: MODE_PERSISTENT}


async def test_no_bluetooth_options_over_ocpp(hass: HomeAssistant) -> None:
    """The Bluetooth connection mode means nothing to a charger on OCPP."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data=OCPP_ENTRY_DATA, minor_version=2
    )
    entry.add_to_hass(hass)

    assert not entry.supports_options


async def test_bluetooth_options_before_migration(hass: HomeAssistant) -> None:
    """A disabled entry from before OCPP support is listed with its options."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=PRE_OCPP_ENTRY_DATA)
    entry.add_to_hass(hass)

    assert entry.supports_options
