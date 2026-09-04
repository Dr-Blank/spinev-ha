"""Tests for the Spin EV Charger polling and write behaviour."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from spinev_ble import SpinEvBusyError, SpinEvCommandRejectedError, SpinEvError

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import IDLE_STATUS, STATUS
from custom_components.spinev.const import (
    CHARGING_INTERVAL,
    CONF_CONNECTION_MODE,
    IDLE_INTERVAL,
    MODE_PERSISTENT,
    REBOOT_SETTLE,
    WRITE_DEBOUNCE,
)

CHARGING_SWITCH = "switch.123456789012_charging"
STATE_SENSOR = "sensor.123456789012_state"
CURRENT_LIMIT = "number.123456789012_current_limit"
START_DELAY = "number.123456789012_start_delay"
LOAD_BALANCING = "binary_sensor.123456789012_load_balancing"


async def async_settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let a debounced number write reach the charger."""
    freezer.tick(WRITE_DEBOUNCE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("init_integration")
async def test_a_per_poll_connection_is_released(mock_charger: AsyncMock) -> None:
    """The default mode hands the charger back between polls."""
    mock_charger.async_disconnect.assert_awaited()


@pytest.mark.usefixtures("mock_ble_device")
async def test_a_persistent_connection_is_held(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Persistent mode keeps the link, and everyone else out."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_CONNECTION_MODE: MODE_PERSISTENT},
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_charger.async_disconnect.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(STATUS, CHARGING_INTERVAL, id="charging"),
        pytest.param(IDLE_STATUS, IDLE_INTERVAL, id="idle"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_the_poll_interval_follows_the_session(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    status: object,
    expected: timedelta,
) -> None:
    """Polling is fast during a session and slow while idle."""
    mock_charger.async_get_status.return_value = status
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.update_interval == expected


@pytest.mark.usefixtures("init_integration")
async def test_a_failed_poll_makes_entities_unavailable(
    hass: HomeAssistant,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A charger that stops answering is reported as unavailable, not stale."""
    assert hass.states.get(STATE_SENSOR).state != STATE_UNAVAILABLE

    mock_charger.async_get_status.side_effect = SpinEvError("gone")
    freezer.tick(CHARGING_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(STATE_SENSOR).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("init_integration")
async def test_the_settings_registers_are_read_only_at_setup(
    hass: HomeAssistant,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The start delay and load balancing cost eight extra round trips.

    Only this integration and the phone app change them, so they are read once
    at setup rather than on every poll.
    """
    assert mock_charger.async_get_random_delay.await_count == 1
    assert mock_charger.async_get_load_balancing.await_count == 1

    freezer.tick(CHARGING_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_charger.async_get_status.await_count == 2
    assert mock_charger.async_get_random_delay.await_count == 1
    assert mock_charger.async_get_load_balancing.await_count == 1


@pytest.mark.usefixtures("mock_ble_device")
async def test_a_charger_without_load_balancing_still_works(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
) -> None:
    """Not every model answers on those registers, and the rest still should."""
    mock_charger.async_get_load_balancing.side_effect = SpinEvError("no such register")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.load_balancing is None
    assert hass.states.get(LOAD_BALANCING) is None
    assert hass.states.get(STATE_SENSOR).state == "charging"


@pytest.mark.usefixtures("init_integration")
async def test_a_current_limit_change_is_written_but_not_committed(
    hass: HomeAssistant, mock_charger: AsyncMock, freezer: FrozenDateTimeFactory
) -> None:
    """Committing a current limit would restart the charger for no reason."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": CURRENT_LIMIT, "value": 16},
        blocking=True,
    )
    await async_settle(hass, freezer)

    mock_charger.async_set_current_limit.assert_awaited_once_with(16.0, commit=False)
    mock_charger.async_commit.assert_not_awaited()


@pytest.mark.usefixtures("init_integration")
async def test_a_start_delay_change_is_reread_after_the_restart(
    hass: HomeAssistant,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A commit restarts the charger, so the re-read waits for it to come back."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": START_DELAY, "value": 600},
        blocking=True,
    )
    await async_settle(hass, freezer)

    mock_charger.async_set_random_delay.assert_awaited_once_with(600)
    # The charger is still restarting, so the new value comes from the write
    # rather than from a re-read that would only fail.
    assert hass.states.get(START_DELAY).state == "600.0"

    polls_before = mock_charger.async_get_status.await_count
    freezer.tick(REBOOT_SETTLE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_charger.async_get_status.await_count > polls_before


@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        pytest.param(SpinEvBusyError("busy"), "charger_busy", id="busy"),
        pytest.param(
            SpinEvCommandRejectedError("nope"), "command_rejected", id="rejected"
        ),
        pytest.param(SpinEvError("no reply"), "cannot_write", id="unreachable"),
    ],
)
@pytest.mark.usefixtures("init_integration")
async def test_a_rejected_write_is_reported(
    hass: HomeAssistant,
    mock_charger: AsyncMock,
    error: Exception,
    translation_key: str,
) -> None:
    """A write the charger refuses surfaces as a translated error."""
    mock_charger.async_stop_charging.side_effect = error

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": CHARGING_SWITCH}, blocking=True
        )

    assert err.value.translation_key == translation_key


@pytest.mark.usefixtures("mock_ble_device")
async def test_a_held_link_that_drops_is_rebuilt(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """In persistent mode the client outlives a poll, so a dead one is replaced."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_CONNECTION_MODE: MODE_PERSISTENT},
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_charger.is_connected = False
    mock_charger.async_disconnect.reset_mock()

    freezer.tick(CHARGING_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    mock_charger.async_disconnect.assert_awaited()
    assert hass.states.get(STATE_SENSOR).state == "charging"


@pytest.mark.usefixtures("init_integration")
async def test_a_poll_fails_when_the_charger_goes_out_of_range(
    hass: HomeAssistant,
    mock_ble_device: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An address the Bluetooth manager stops resolving fails the poll."""
    mock_ble_device.return_value = None

    freezer.tick(CHARGING_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(STATE_SENSOR).state == STATE_UNAVAILABLE
