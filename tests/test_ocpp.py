"""Tests for reaching the charger through the integration's OCPP central system."""

import json
import logging
from unittest.mock import AsyncMock, patch

from aiohttp import ClientConnectorError, ClientSession, ClientWebSocketResponse
from freezegun.api import FrozenDateTimeFactory
from ocpp_csms import CsmsConnectionError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from spinev_ble import ChargerState, ChargerStatus, OcppTunnelTransport

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .conftest import ConnectCharger
from .const import (
    ADDRESS,
    CHARGE_POINT_ID,
    ENTRY_DATA,
    ENTRY_OPTIONS,
    HA_HOST,
    OCPP_ENTRY_DATA,
    PRE_OCPP_ENTRY_DATA,
    SERIAL,
)
from custom_components.exicom_spin_ble.const import DOMAIN, OCPP_STOP_DELAY
from custom_components.exicom_spin_ble.hub import async_get_hub

STATE_SENSOR = "sensor.123456789012_state"
CONNECTION_TYPE_SENSOR = "sensor.123456789012_connection_type"
VEHICLE_CONNECTED = "binary_sensor.123456789012_vehicle_connected"


@pytest.fixture
def ocpp_entry() -> MockConfigEntry:
    """Return an entry for a charger moved from Bluetooth to OCPP."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=SERIAL,
        unique_id=ADDRESS,
        data=OCPP_ENTRY_DATA,
        options=ENTRY_OPTIONS,
        minor_version=2,
    )


@pytest.fixture
async def charger_socket(
    hass: HomeAssistant, connect_charger: ConnectCharger
) -> ClientWebSocketResponse:
    """Connect the charger, holding the central system open for it."""
    await async_get_hub(hass).async_acquire()
    return await connect_charger(CHARGE_POINT_ID)


@pytest.fixture
async def ocpp_integration(
    hass: HomeAssistant,
    ocpp_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> MockConfigEntry:
    """Set up a charger that is connected over OCPP."""
    ocpp_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ocpp_entry.entry_id)
    await hass.async_block_till_done()
    return ocpp_entry


async def send_status(
    socket: ClientWebSocketResponse, status: str, connector_id: int = 1
) -> None:
    """Report a connector status from the charger and read the answer."""
    await socket.send_str(
        json.dumps(
            [
                2,
                "1",
                "StatusNotification",
                {"connectorId": connector_id, "errorCode": "NoError", "status": status},
            ]
        )
    )
    await socket.receive()


async def async_enter_fault(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_charger: AsyncMock,
    before: ChargerState,
) -> None:
    """Read a state that shows the plug, then a fault that does not."""
    for state in (before, ChargerState.FAULT):
        mock_charger.async_get_status.return_value = ChargerStatus(state=state)
        await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_setup_tunnels_through_ocpp(
    hass: HomeAssistant,
    ocpp_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> None:
    """A charger on OCPP is read through its DataTransfer tunnel."""
    ocpp_entry.add_to_hass(hass)
    with patch(
        "custom_components.exicom_spin_ble.coordinator.OcppTunnelTransport",
        wraps=OcppTunnelTransport,
    ) as tunnel:
        await hass.config_entries.async_setup(ocpp_entry.entry_id)
        await hass.async_block_till_done()

    assert ocpp_entry.state is ConfigEntryState.LOADED
    tunnel.assert_called_once()
    mock_charger.async_get_status.assert_awaited()
    assert hass.states.get(STATE_SENSOR) is not None
    connection_type = hass.states.get(CONNECTION_TYPE_SENSOR)
    assert connection_type is not None
    assert connection_type.state == "ocpp"


@pytest.mark.usefixtures("mock_charger")
async def test_setup_retries_until_the_charger_connects(
    hass: HomeAssistant, ocpp_entry: MockConfigEntry
) -> None:
    """A charger not connected yet is a retry, not a failure."""
    ocpp_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(ocpp_entry.entry_id)
    await hass.async_block_till_done()

    assert ocpp_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_charger")
async def test_setup_retries_when_the_port_is_taken(
    hass: HomeAssistant, ocpp_entry: MockConfigEntry
) -> None:
    """A central system that cannot listen is a retry, not a failure."""
    ocpp_entry.add_to_hass(hass)

    with patch(
        "custom_components.exicom_spin_ble.hub.CentralSystem.async_start",
        side_effect=CsmsConnectionError("in use"),
    ):
        await hass.config_entries.async_setup(ocpp_entry.entry_id)
        await hass.async_block_till_done()

    assert ocpp_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("ocpp_integration")
async def test_status_from_the_charger_refreshes(
    hass: HomeAssistant,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> None:
    """What the charger reports by itself is picked up without waiting a poll."""
    mock_charger.async_get_status.reset_mock()

    await send_status(charger_socket, "Charging")
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_charger.async_get_status.assert_awaited()


@pytest.mark.parametrize(
    ("before", "status", "connector_id", "expected"),
    [
        pytest.param(ChargerState.CHARGING, "Available", 1, STATE_OFF, id="removed"),
        pytest.param(ChargerState.AVAILABLE, "Preparing", 1, STATE_ON, id="preparing"),
        pytest.param(ChargerState.AVAILABLE, "Charging", 1, STATE_ON, id="charging"),
        pytest.param(ChargerState.AVAILABLE, "SuspendedEV", 1, STATE_ON, id="susp_ev"),
        pytest.param(
            ChargerState.AVAILABLE, "SuspendedEVSE", 1, STATE_ON, id="susp_evse"
        ),
        pytest.param(ChargerState.CHARGING, "Faulted", 1, STATE_ON, id="faulted_on"),
        pytest.param(ChargerState.AVAILABLE, "Faulted", 1, STATE_OFF, id="faulted_off"),
        pytest.param(ChargerState.CHARGING, "Finishing", 1, STATE_ON, id="finishing"),
        pytest.param(ChargerState.AVAILABLE, "Reserved", 1, STATE_OFF, id="reserved"),
        pytest.param(
            ChargerState.AVAILABLE, "Unavailable", 1, STATE_OFF, id="unavailable"
        ),
        pytest.param(ChargerState.CHARGING, "Available", 0, STATE_ON, id="whole_off"),
        pytest.param(ChargerState.AVAILABLE, "Preparing", 0, STATE_OFF, id="whole_on"),
    ],
)
async def test_a_connector_status_sets_the_plug_state_during_a_fault(
    hass: HomeAssistant,
    ocpp_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
    before: ChargerState,
    status: str,
    connector_id: int,
    expected: str,
) -> None:
    """Only a status of the charging connector that shows the plug counts."""
    await async_enter_fault(hass, ocpp_integration, mock_charger, before)

    await send_status(charger_socket, status, connector_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(VEHICLE_CONNECTED).state == expected
    event = next(
        event
        for event in reversed(ocpp_integration.runtime_data.events)
        if event["event"] == "connector_status"
    )
    assert event["status"] == status
    assert event["connector_id"] == connector_id


async def test_a_connector_status_reaches_the_entity_without_a_refresh(
    hass: HomeAssistant,
    ocpp_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> None:
    """The refresh it prompts may be held back or fail, so it is not relied on."""
    await async_enter_fault(
        hass, ocpp_integration, mock_charger, ChargerState.AVAILABLE
    )

    with patch.object(ocpp_integration.runtime_data, "async_request_refresh"):
        await send_status(charger_socket, "Preparing")
        await hass.async_block_till_done()

    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_ON


async def test_a_state_that_shows_the_plug_overrides_a_connector_status(
    hass: HomeAssistant,
    ocpp_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> None:
    """A poll outside a fault has the final say on the plug state."""
    await async_enter_fault(hass, ocpp_integration, mock_charger, ChargerState.CHARGING)
    await send_status(charger_socket, "Available")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_OFF

    mock_charger.async_get_status.return_value = ChargerStatus(
        state=ChargerState.CHARGING
    )
    await ocpp_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_ON


async def test_a_lost_connection_makes_the_charger_unavailable(
    hass: HomeAssistant,
    ocpp_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> None:
    """Once the charger drops, polls fail."""
    await charger_socket.close()
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_charger.is_connected = False

    await ocpp_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(STATE_SENSOR)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_central_system_stops_after_its_last_user(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The port is given back a little after nothing needs it."""
    hub = async_get_hub(hass)
    await hub.async_acquire()
    port = hub.port
    hub.async_release()

    freezer.tick(OCPP_STOP_DELAY)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    async with ClientSession() as session:
        with pytest.raises(ClientConnectorError):
            await session.ws_connect(f"ws://127.0.0.1:{port}/ocpp/{CHARGE_POINT_ID}")


async def test_central_system_held_again_keeps_running(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    connect_charger: ConnectCharger,
) -> None:
    """A user arriving within the delay keeps chargers connected."""
    hub = async_get_hub(hass)
    await hub.async_acquire()
    hub.async_release()
    await hub.async_acquire()

    freezer.tick(OCPP_STOP_DELAY)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    await connect_charger(CHARGE_POINT_ID)
    assert hub.connected_ids() == [CHARGE_POINT_ID]
    hub.async_release()


@pytest.mark.usefixtures("mock_charger")
async def test_central_system_kept_for_an_entry_retrying_setup(
    hass: HomeAssistant,
    ocpp_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    connect_charger: ConnectCharger,
) -> None:
    """Retries further apart than the stop delay still find the port open."""
    ocpp_entry.add_to_hass(hass)
    ocpp_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    hub = async_get_hub(hass)
    await hub.async_acquire()
    hub.async_release()

    # Twice, as the first check only puts the stop off.
    freezer.tick(OCPP_STOP_DELAY)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    freezer.tick(OCPP_STOP_DELAY)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    await connect_charger(CHARGE_POINT_ID)
    assert hub.connected_ids() == [CHARGE_POINT_ID]


async def test_central_system_stops_once_no_entry_is_retrying(
    hass: HomeAssistant,
    ocpp_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The port is given back once the entry it was kept for gives up."""
    ocpp_entry.add_to_hass(hass)
    ocpp_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    hub = async_get_hub(hass)
    await hub.async_acquire()
    port = hub.port
    hub.async_release()
    freezer.tick(OCPP_STOP_DELAY)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    ocpp_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    freezer.tick(OCPP_STOP_DELAY)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    async with ClientSession() as session:
        with pytest.raises(ClientConnectorError):
            await session.ws_connect(f"ws://127.0.0.1:{port}/ocpp/{CHARGE_POINT_ID}")


@pytest.mark.usefixtures("mock_charger")
async def test_entry_set_up_as_soon_as_its_charger_connects(
    hass: HomeAssistant,
    ocpp_entry: MockConfigEntry,
    connect_charger: ConnectCharger,
) -> None:
    """A charger connecting between retries does not wait for the next one."""
    ocpp_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ocpp_entry.entry_id)
    await hass.async_block_till_done()
    assert ocpp_entry.state is ConfigEntryState.SETUP_RETRY

    await connect_charger(CHARGE_POINT_ID)
    await hass.async_block_till_done()

    assert ocpp_entry.state is ConfigEntryState.LOADED


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_entries_from_before_ocpp_are_migrated(hass: HomeAssistant) -> None:
    """Every entry made before OCPP support used Bluetooth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=SERIAL,
        unique_id=ADDRESS,
        data=PRE_OCPP_ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == ENTRY_DATA
    assert entry.minor_version == 2


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_logs_carry_no_private_data(
    hass: HomeAssistant,
    service_info: BluetoothServiceInfoBleak,
    connect_charger: ConnectCharger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Debug logs name chargers by a masked id, and never the host or address."""
    caplog.set_level(logging.DEBUG, logger="custom_components.exicom_spin_ble")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bluetooth_to_ocpp"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HA_HOST}
    )
    socket = await connect_charger(CHARGE_POINT_ID)
    await hass.config_entries.flow.async_configure(result["flow_id"])
    await hass.async_block_till_done(wait_background_tasks=True)
    await socket.close()
    await hass.async_block_till_done(wait_background_tasks=True)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.exicom_spin_ble")
    ]
    assert any("…9012" in message for message in messages)
    for private in (SERIAL, CHARGE_POINT_ID, ADDRESS, HA_HOST, "ocpp.example.com"):
        assert not any(private in message for message in messages), private
