"""Tests for setting the Spin EV Charger integration up and tearing it down."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from spinev_ble import SpinEvError

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.spinev.const import CONF_CONNECTION_MODE, MODE_PERSISTENT


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_setup_and_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The entry loads, then unloads cleanly."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_unload_releases_the_charger(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_charger: AsyncMock
) -> None:
    """Unloading hands the Bluetooth link back to the phone app."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_CONNECTION_MODE: MODE_PERSISTENT}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_charger.async_disconnect.reset_mock()

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_charger.async_disconnect.assert_awaited()


@pytest.mark.usefixtures("mock_charger")
async def test_setup_retries_when_the_charger_is_not_seen(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_ble_device: MagicMock,
) -> None:
    """An address the Bluetooth manager cannot resolve is a retry, not a failure."""
    mock_ble_device.return_value = None
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    "failing_read",
    [
        pytest.param("async_get_random_delay", id="settings"),
        pytest.param("async_get_status", id="status"),
    ],
)
@pytest.mark.usefixtures("mock_ble_device")
async def test_setup_retries_when_the_first_read_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    failing_read: str,
) -> None:
    """A charger that does not answer on setup is a retry, not a failure."""
    getattr(mock_charger, failing_read).side_effect = SpinEvError("no reply")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_charger.async_disconnect.assert_awaited()


@pytest.mark.usefixtures("mock_charger", "mock_ble_device")
async def test_changing_options_reloads(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A connection mode change only takes effect on a reload, so one is forced."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data

    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_CONNECTION_MODE: MODE_PERSISTENT},
    )
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is not coordinator
