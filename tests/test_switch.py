"""Tests for the Spin EV Charger charging switch."""

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from spinev_ble import ChargerState, ChargerStatus

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

CHARGING_SWITCH = "switch.123456789012_charging"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        pytest.param(ChargerState.AVAILABLE, STATE_OFF, id="available"),
        pytest.param(ChargerState.IDLE, STATE_OFF, id="idle"),
        pytest.param(ChargerState.STARTING, STATE_ON, id="starting"),
        pytest.param(ChargerState.CHARGING, STATE_ON, id="charging"),
        # A vehicle pausing resumes without a command, so the switch stays on
        # rather than flapping mid-session.
        pytest.param(ChargerState.EV_SUSPENDED, STATE_ON, id="ev_suspended"),
        pytest.param(ChargerState.EVSE_SUSPENDED, STATE_ON, id="evse_suspended"),
        pytest.param(ChargerState.FINISHING, STATE_OFF, id="finishing"),
        # A state this library does not recognise leaves the switch with
        # nothing to report, so it goes unavailable rather than guessing.
        pytest.param(None, STATE_UNAVAILABLE, id="unrecognised"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_the_switch_follows_the_session(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    state: ChargerState | None,
    expected: str,
) -> None:
    """The switch is on for a whole session, including while it is paused."""
    mock_charger.async_get_status.return_value = ChargerStatus(state=state)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CHARGING_SWITCH).state == expected


@pytest.mark.usefixtures("mock_ble_device")
async def test_starting_a_charge(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """A plugged in vehicle can be told to start."""
    mock_charger.async_get_status.return_value = ChargerStatus(state=ChargerState.IDLE)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": CHARGING_SWITCH}, blocking=True
    )

    mock_charger.async_start_charging.assert_awaited_once()


@pytest.mark.parametrize(
    ("state", "translation_key"),
    [
        pytest.param(ChargerState.AVAILABLE, "no_vehicle_connected", id="no_vehicle"),
        pytest.param(ChargerState.BOOTING, "charger_booting", id="booting"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_starting_is_refused_when_it_could_only_do_nothing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    state: ChargerState | None,
    translation_key: str,
) -> None:
    """A start command that cannot take effect is refused rather than sent."""
    mock_charger.async_get_status.return_value = ChargerStatus(state=state)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": CHARGING_SWITCH}, blocking=True
        )

    assert err.value.translation_key == translation_key
    mock_charger.async_start_charging.assert_not_awaited()


async def test_stopping_a_charge(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Stopping is always allowed."""
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": CHARGING_SWITCH}, blocking=True
    )

    mock_charger.async_stop_charging.assert_awaited_once()
