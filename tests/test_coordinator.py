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
    CONF_CONNECTION_MODE,
    DEFAULT_CHARGING_INTERVAL,
    DEFAULT_IDLE_INTERVAL,
    MODE_PERSISTENT,
    REBOOT_SETTLE,
)

CHARGING_SWITCH = "switch.123456789012_charging"
STATE_SENSOR = "sensor.123456789012_state"
CURRENT_LIMIT = "number.123456789012_current_limit"
APPLY_CONFIG = "button.123456789012_apply_config"
REFRESH = "button.123456789012_refresh"


async def test_a_per_poll_connection_is_released(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """The default mode hands the charger back between polls."""
    mock_charger.async_disconnect.assert_awaited()


@pytest.mark.usefixtures("mock_ble_device")
async def test_a_persistent_connection_is_held(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Persistent mode keeps the link, and the phone app out."""
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
        pytest.param(STATUS, DEFAULT_CHARGING_INTERVAL, id="charging"),
        pytest.param(IDLE_STATUS, DEFAULT_IDLE_INTERVAL, id="idle"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_the_poll_interval_follows_the_session(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    status: object,
    expected: int,
) -> None:
    """Polling is fast during a session and slow while idle."""
    mock_charger.async_get_status.return_value = status
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.update_interval == timedelta(seconds=expected)


async def test_a_failed_poll_makes_entities_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A charger that stops answering is reported as unavailable, not stale."""
    assert hass.states.get(STATE_SENSOR).state != STATE_UNAVAILABLE

    mock_charger.async_get_status.side_effect = SpinEvError("gone")
    freezer.tick(timedelta(seconds=DEFAULT_CHARGING_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(STATE_SENSOR).state == STATE_UNAVAILABLE


async def test_the_extra_config_registers_are_only_read_when_asked(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Extra config registers are read on the first poll, not on every one.

    Timezone, start delay and load balancing together cost nine round trips,
    and re-reading the editable ones would overwrite an unapplied edit.
    """
    assert mock_charger.async_get_timezone.await_count == 1

    freezer.tick(timedelta(seconds=DEFAULT_CHARGING_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_charger.async_get_status.await_count == 2
    assert mock_charger.async_get_timezone.await_count == 1


async def test_refresh_rereads_the_config(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Refresh throws the config draft away and asks the charger again."""
    await hass.services.async_call(
        "button", "press", {"entity_id": REFRESH}, blocking=True
    )

    assert mock_charger.async_get_timezone.await_count == 2


async def test_a_charger_without_load_balancing_still_works(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    mock_ble_device: AsyncMock,
) -> None:
    """Not every model answers on those registers, and the rest still should."""
    mock_charger.async_get_load_balancing.side_effect = SpinEvError("no such register")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.load_balancing is None
    assert hass.states.get(STATE_SENSOR).state == "charging"


async def test_applying_an_unchanged_config_writes_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Nothing was edited, so the charger is left alone rather than restarted."""
    await hass.services.async_call(
        "button", "press", {"entity_id": APPLY_CONFIG}, blocking=True
    )

    mock_charger.async_commit.assert_not_awaited()
    mock_charger.async_set_current_limit.assert_not_awaited()


async def test_a_current_limit_change_is_not_committed(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Committing a current limit would restart the charger for no reason."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": CURRENT_LIMIT, "value": 16},
        blocking=True,
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": APPLY_CONFIG}, blocking=True
    )

    mock_charger.async_set_current_limit.assert_awaited_once_with(16.0, commit=False)
    mock_charger.async_commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("number", "value", "method", "expected_args"),
    [
        pytest.param(
            "number.123456789012_timezone_offset_hours",
            1,
            "async_set_timezone",
            (1, 30),
            id="timezone",
        ),
        pytest.param(
            "number.123456789012_start_delay",
            600,
            "async_set_random_delay",
            (600,),
            id="start_delay",
        ),
    ],
)
async def test_a_committed_change_is_reread_after_the_restart(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    freezer: FrozenDateTimeFactory,
    number: str,
    value: int,
    method: str,
    expected_args: tuple[int, ...],
) -> None:
    """A commit restarts the charger, so the re-read waits for it to come back."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": number, "value": value},
        blocking=True,
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": APPLY_CONFIG}, blocking=True
    )

    getattr(mock_charger, method).assert_awaited_once_with(*expected_args, commit=False)
    mock_charger.async_commit.assert_awaited_once()
    assert mock_charger.async_get_timezone.await_count == 1

    freezer.tick(REBOOT_SETTLE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_charger.async_get_timezone.await_count == 2


async def test_setting_a_number_does_not_touch_the_charger(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """The numbers are a draft; only Apply config sends them."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": CURRENT_LIMIT, "value": 16},
        blocking=True,
    )

    mock_charger.async_set_current_limit.assert_not_awaited()
    assert hass.states.get(CURRENT_LIMIT).state == "16.0"


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
async def test_a_rejected_write_is_reported(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
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

    freezer.tick(timedelta(seconds=DEFAULT_CHARGING_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    mock_charger.async_disconnect.assert_awaited()
    assert hass.states.get(STATE_SENSOR).state == "charging"


async def test_a_poll_fails_when_the_charger_goes_out_of_range(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_ble_device: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An address the Bluetooth manager stops resolving fails the poll."""
    mock_ble_device.return_value = None

    freezer.tick(timedelta(seconds=DEFAULT_CHARGING_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(STATE_SENSOR).state == STATE_UNAVAILABLE
