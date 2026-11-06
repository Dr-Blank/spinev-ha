"""Tests for how the coordinator tracks and records the charger's condition."""

import logging
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)
from spinev_ble import ChargerState, ChargerStatus, SpinEvError

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError

from .const import SERIAL
from custom_components.exicom_spin_ble.coordinator import _EVENT_LOG_SIZE

VEHICLE_CONNECTED = "binary_sensor.123456789012_vehicle_connected"
CHARGING_SWITCH = "switch.123456789012_charging"
COORDINATOR_LOGGER = "custom_components.exicom_spin_ble.coordinator"
FAULT = ChargerStatus(
    state=ChargerState.FAULT,
    state_value=ChargerState.FAULT.value,
    voltage_v=264.9,
    alarms=("Mains High", "L1 Voltage High"),
)


async def async_poll(entry: MockConfigEntry, hass: HomeAssistant) -> None:
    """Run one coordinator refresh."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        pytest.param(ChargerState.AVAILABLE, STATE_OFF, id="nothing_plugged_in"),
        pytest.param(ChargerState.CHARGING, STATE_ON, id="vehicle_plugged_in"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_vehicle_connected_holds_through_a_failed_poll_and_a_fault(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    before: ChargerState,
    expected: str,
) -> None:
    """A fault leaves the last known plug state, even after a failed poll."""
    mock_charger.async_get_status.return_value = ChargerStatus(state=before)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(VEHICLE_CONNECTED).state == expected

    mock_charger.async_get_status.side_effect = SpinEvError("no reply")
    await async_poll(mock_config_entry, hass)
    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_UNAVAILABLE

    mock_charger.async_get_status.side_effect = None
    mock_charger.async_get_status.return_value = FAULT
    await async_poll(mock_config_entry, hass)
    assert hass.states.get(VEHICLE_CONNECTED).state == expected


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(FAULT, id="fault"),
        pytest.param(ChargerStatus(state=None, state_value=99), id="unrecognised"),
    ],
)
@pytest.mark.parametrize(
    ("restored", "expected"),
    [
        pytest.param(STATE_ON, STATE_ON, id="restored_on"),
        pytest.param(STATE_OFF, STATE_OFF, id="restored_off"),
        pytest.param(STATE_UNAVAILABLE, STATE_OFF, id="restored_unavailable"),
        pytest.param(None, STATE_OFF, id="nothing_to_restore"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_vehicle_connected_starts_from_its_last_state_without_a_reading(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    status: ChargerStatus,
    restored: str | None,
    expected: str,
) -> None:
    """A start with no reading of the plug restores it, and is never unknown."""
    mock_restore_cache(hass, [State(VEHICLE_CONNECTED, restored)] if restored else [])
    mock_charger.async_get_status.return_value = status
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(VEHICLE_CONNECTED).state == expected


@pytest.mark.usefixtures("mock_ble_device")
async def test_a_reading_of_the_plug_beats_the_restored_state(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """A state that shows the plug is more recent than what was restored."""
    mock_restore_cache(hass, [State(VEHICLE_CONNECTED, STATE_ON)])
    mock_charger.async_get_status.return_value = ChargerStatus(
        state=ChargerState.AVAILABLE
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_OFF


@pytest.mark.usefixtures("mock_ble_device")
async def test_vehicle_connected_holds_through_an_unrecognised_state(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """A state this library cannot name says nothing about the plug either."""
    mock_charger.async_get_status.return_value = ChargerStatus(
        state=ChargerState.CHARGING
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_charger.async_get_status.return_value = ChargerStatus(
        state=None, state_value=99
    )
    await async_poll(mock_config_entry, hass)

    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_ON


@pytest.mark.usefixtures("mock_ble_device")
async def test_vehicle_connected_follows_the_state_once_a_fault_clears(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """A state that can tell replaces whatever was held through the fault."""
    mock_charger.async_get_status.return_value = FAULT
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_charger.async_get_status.return_value = ChargerStatus(
        state=ChargerState.AVAILABLE
    )
    await async_poll(mock_config_entry, hass)

    assert hass.states.get(VEHICLE_CONNECTED).state == STATE_OFF


async def test_a_state_and_alarm_change_is_logged_and_recorded(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fault's start shows the state, alarms and voltage by name."""
    mock_charger.async_get_status.return_value = FAULT
    with caplog.at_level(logging.DEBUG, logger=COORDINATOR_LOGGER):
        await async_poll(init_integration, hass)

    assert (
        "state CHARGING -> FAULT, alarms: Mains High, L1 Voltage High, 264.9 V"
        in caplog.text
    )
    event = init_integration.runtime_data.events[-1]
    assert event["event"] == "state_changed"
    assert event["from_state"] == "CHARGING"
    assert event["to_state"] == "FAULT"
    assert event["alarms"] == ["Mains High", "L1 Voltage High"]
    assert event["voltage_v"] == 264.9
    assert SERIAL not in caplog.text


async def test_an_unchanged_reading_records_no_event(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Only changes take up room in the buffer."""
    events = len(init_integration.runtime_data.events)

    await async_poll(init_integration, hass)

    assert len(init_integration.runtime_data.events) == events


async def test_every_failed_poll_is_logged_and_repeats_share_an_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A long outage stays visible without pushing out what led up to it."""
    events = init_integration.runtime_data.events
    before = list(events)
    mock_charger.async_get_status.side_effect = SpinEvError("no reply for register 67")

    with caplog.at_level(logging.DEBUG, logger=COORDINATOR_LOGGER):
        for _ in range(_EVENT_LOG_SIZE + 1):
            await async_poll(init_integration, hass)

    assert caplog.text.count("poll failed after") == _EVENT_LOG_SIZE + 1
    assert list(events)[: len(before)] == before
    assert events[-1]["event"] == "poll_failed"
    assert events[-1]["error"] == "no reply for register 67"
    assert events[-1]["count"] == _EVENT_LOG_SIZE + 1


async def test_a_poll_after_a_failure_records_the_recovery(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """The end of an outage is as visible as its start."""
    mock_charger.async_get_status.side_effect = SpinEvError("gone")
    await async_poll(init_integration, hass)
    mock_charger.async_get_status.side_effect = None
    await async_poll(init_integration, hass)

    assert init_integration.runtime_data.events[-1]["event"] == "poll_recovered"


async def test_a_recovery_is_recorded_after_a_failure_that_was_not_the_last_event(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """An event arriving during an outage does not hide its end."""
    coordinator = init_integration.runtime_data
    mock_charger.async_get_status.side_effect = SpinEvError("gone")
    await async_poll(init_integration, hass)
    coordinator.events.append({"event": "connector_status"})
    mock_charger.async_get_status.side_effect = None
    await async_poll(init_integration, hass)

    assert coordinator.events[-1]["event"] == "poll_recovered"


async def test_a_failure_with_no_charger_error_records_only_its_key(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_ble_device: AsyncMock
) -> None:
    """A message built around the Bluetooth address is reduced to its key."""
    mock_ble_device.return_value = None

    await async_poll(init_integration, hass)

    assert init_integration.runtime_data.events[-1]["error"] == "device_not_found"


async def test_a_command_is_logged_and_recorded_with_its_result(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Accepted and failed commands both leave a trace."""
    with caplog.at_level(logging.DEBUG, logger=COORDINATOR_LOGGER):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": CHARGING_SWITCH}, blocking=True
        )
        accepted = next(
            event
            for event in init_integration.runtime_data.events
            if event["event"] == "command"
        )

        mock_charger.async_start_charging.side_effect = SpinEvError("link down")
        mock_charger.async_get_status.return_value = ChargerStatus(
            state=ChargerState.IDLE
        )
        await async_poll(init_integration, hass)
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "switch", "turn_on", {"entity_id": CHARGING_SWITCH}, blocking=True
            )

    assert accepted["command"] == "stop_charging"
    assert accepted["error"] is None
    event = init_integration.runtime_data.events[-1]
    assert event["command"] == "start_charging"
    assert event["error"] == "link down"
    assert "command stop_charging: accepted" in caplog.text
    assert "command start_charging: link down" in caplog.text


async def test_a_command_that_finds_no_charger_is_recorded(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_ble_device: AsyncMock
) -> None:
    """A write that cannot reach the charger still leaves a trace."""
    mock_ble_device.return_value = None

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": CHARGING_SWITCH}, blocking=True
        )

    event = init_integration.runtime_data.events[-1]
    assert event["command"] == "stop_charging"
    assert event["error"] == "device_not_found"
