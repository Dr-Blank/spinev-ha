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
from spinev_ble import OcppTunnelTransport

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
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
from custom_components.spinev.const import DOMAIN, OCPP_STOP_DELAY
from custom_components.spinev.hub import async_get_hub

STATE_SENSOR = "sensor.123456789012_state"
CONNECTION_TYPE_SENSOR = "sensor.123456789012_connection_type"


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


async def send_status(socket: ClientWebSocketResponse, status: str) -> None:
    """Report a connector status from the charger and read the answer."""
    await socket.send_str(
        json.dumps(
            [
                2,
                "1",
                "StatusNotification",
                {"connectorId": 1, "errorCode": "NoError", "status": status},
            ]
        )
    )
    await socket.receive()


async def test_setup_tunnels_through_ocpp(
    hass: HomeAssistant,
    ocpp_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    charger_socket: ClientWebSocketResponse,
) -> None:
    """A charger on OCPP is read through its DataTransfer tunnel."""
    ocpp_entry.add_to_hass(hass)
    with patch(
        "custom_components.spinev.coordinator.OcppTunnelTransport",
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
        "custom_components.spinev.hub.CentralSystem.async_start",
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
    caplog.set_level(logging.DEBUG, logger="custom_components.spinev")

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
        if record.name.startswith("custom_components.spinev")
    ]
    assert any("…9012" in message for message in messages)
    for private in (SERIAL, CHARGE_POINT_ID, ADDRESS, HA_HOST, "ocpp.example.com"):
        assert not any(private in message for message in messages), private
