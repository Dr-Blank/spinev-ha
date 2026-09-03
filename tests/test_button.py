"""Tests for the Spin EV Charger buttons."""

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

BUTTONS = "button.123456789012_{}"


@pytest.mark.parametrize(
    ("button", "method"),
    [
        pytest.param("sync_clock", "async_sync_clock", id="sync_clock"),
        pytest.param("restart", "async_reboot", id="restart"),
    ],
)
async def test_a_button_that_restarts_the_charger(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
    button: str,
    method: str,
) -> None:
    """These commit, so the link is dropped and the re-read is deferred."""
    await hass.services.async_call(
        "button", "press", {"entity_id": BUTTONS.format(button)}, blocking=True
    )

    getattr(mock_charger, method).assert_awaited_once()
    # The charger restarts a few seconds after a commit, so re-reading now
    # would only fail; the refresh waits instead.
    assert mock_charger.async_get_status.await_count == 1
