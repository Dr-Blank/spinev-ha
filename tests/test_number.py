"""Tests for the Spin EV Charger numbers."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from spinev_ble import SpinEvError

from homeassistant.core import HomeAssistant

from custom_components.spinev.const import WRITE_DEBOUNCE

CURRENT_LIMIT = "number.123456789012_current_limit"


async def async_set(hass: HomeAssistant, value: float) -> None:
    """Set the current limit the way the frontend does."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": CURRENT_LIMIT, "value": value},
        blocking=True,
    )


@pytest.mark.usefixtures("init_integration")
async def test_a_value_is_shown_before_it_reaches_the_charger(
    hass: HomeAssistant, mock_charger: AsyncMock
) -> None:
    """A slider that snapped back for three seconds would be unusable."""
    await async_set(hass, 16)

    assert hass.states.get(CURRENT_LIMIT).state == "16.0"
    mock_charger.async_set_current_limit.assert_not_awaited()


@pytest.mark.usefixtures("init_integration")
async def test_a_dragged_slider_costs_one_write(
    hass: HomeAssistant, mock_charger: AsyncMock, freezer: FrozenDateTimeFactory
) -> None:
    """Each step of a drag arrives as its own call, and Bluetooth is slow."""
    for value in (30, 24, 20, 16):
        await async_set(hass, value)

    freezer.tick(WRITE_DEBOUNCE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    mock_charger.async_set_current_limit.assert_awaited_once_with(16.0, commit=False)


@pytest.mark.usefixtures("init_integration")
async def test_a_write_the_charger_refuses_stops_showing_its_value(
    hass: HomeAssistant, mock_charger: AsyncMock, freezer: FrozenDateTimeFactory
) -> None:
    """The service call is long gone, so the state is the only feedback left."""
    mock_charger.async_set_current_limit.side_effect = SpinEvError("busy charging")

    await async_set(hass, 16)
    assert hass.states.get(CURRENT_LIMIT).state == "16.0"

    freezer.tick(WRITE_DEBOUNCE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(CURRENT_LIMIT).state == "32.0"


@pytest.mark.usefixtures("init_integration")
async def test_a_value_set_again_mid_write_survives_the_first_one(
    hass: HomeAssistant, mock_charger: AsyncMock, freezer: FrozenDateTimeFactory
) -> None:
    """The second value is on its way out, so the first must not clear it."""
    writing = hass.loop.create_future()

    async def _hold(*args: object, **kwargs: object) -> None:
        await writing

    mock_charger.async_set_current_limit.side_effect = _hold

    await async_set(hass, 16)
    freezer.tick(WRITE_DEBOUNCE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    # Not block_till_done: the write is deliberately still in flight.
    for _ in range(10):
        await asyncio.sleep(0)

    await async_set(hass, 20)
    writing.set_result(None)
    await hass.async_block_till_done()

    assert hass.states.get(CURRENT_LIMIT).state == "20.0"
