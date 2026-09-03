"""Snapshot tests for every entity the Spin EV Charger integration creates."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.spinev import PLATFORMS


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.usefixtures(
    "mock_charger", "mock_ble_device", "entity_registry_enabled_by_default"
)
async def test_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    platform: Platform,
) -> None:
    """Each platform registers the entities it is expected to."""
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.spinev.PLATFORMS", [platform]):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await snapshot_platform(
            hass, entity_registry, snapshot, mock_config_entry.entry_id
        )
