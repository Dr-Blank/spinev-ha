"""Tests for the Spin EV Charger diagnostics."""

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from spinev_ble import SpinEvError
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from .const import ADDRESS, SERIAL


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Diagnostics describe the charger without identifying it."""
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    assert diagnostics == snapshot(exclude=props("time"))
    assert ADDRESS not in str(diagnostics)
    assert SERIAL not in str(diagnostics)


async def test_diagnostics_strip_identifiers_from_errors(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    mock_charger: AsyncMock,
) -> None:
    """A transport message that names the charger is not passed on."""
    mock_charger.async_get_status.side_effect = SpinEvError(
        f"could not connect to {ADDRESS.lower()}, {SERIAL}"
    )
    await init_integration.runtime_data.async_refresh()

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    event = diagnostics["recent_events"][-1]
    assert event["event"] == "poll_failed"
    assert event["error"] == f"could not connect to {REDACTED}, {REDACTED}"


async def test_diagnostics_strip_identifiers_from_status_text(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Free text sent by the charger is not passed on with its identifiers."""
    init_integration.runtime_data.events.append(
        {"event": "connector_status", "status": "Faulted", "info": f"unit {SERIAL}"}
    )

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    assert diagnostics["recent_events"][-1]["info"] == f"unit {REDACTED}"
    assert diagnostics["recent_events"][-1]["status"] == "Faulted"
