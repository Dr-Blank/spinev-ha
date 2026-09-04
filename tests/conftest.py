"""Fixtures for the Spin EV Charger tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.backends.device import BLEDevice
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant

from .const import (
    ADDRESS,
    ADVERTISED_NAME,
    ENTRY_DATA,
    ENTRY_OPTIONS,
    LOAD_BALANCING,
    RANDOM_DELAY,
    SERIAL,
    STATUS,
)
from custom_components.spinev.const import DOMAIN

SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
    mock_bluetooth_adapters: None,
) -> None:
    """Load the integration from custom_components against a mocked adapter."""


@pytest.fixture
def ble_device() -> BLEDevice:
    """Return the charger as the Bluetooth manager reports it."""
    return BLEDevice(ADDRESS, ADVERTISED_NAME, {})


@pytest.fixture
def service_info(ble_device: BLEDevice) -> BluetoothServiceInfoBleak:
    """Return a discovery payload for the charger."""
    advertisement = MagicMock(
        local_name=ADVERTISED_NAME,
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        rssi=-60,
        tx_power=-127,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name=ADVERTISED_NAME,
        address=ADDRESS,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        source="local",
        device=ble_device,
        advertisement=advertisement,
        connectable=True,
        time=0,
        tx_power=-127,
    )


@pytest.fixture
def mock_charger() -> Generator[AsyncMock]:
    """Patch SpinEvCharger everywhere it is constructed."""
    charger = AsyncMock()
    charger.is_connected = True
    charger.async_get_status.return_value = STATUS
    charger.async_get_random_delay.return_value = RANDOM_DELAY
    charger.async_get_load_balancing.return_value = LOAD_BALANCING
    charger.async_get_state_value.return_value = 4
    charger.__aenter__.return_value = charger

    with (
        patch(
            "custom_components.spinev.coordinator.SpinEvCharger",
            return_value=charger,
        ),
        patch(
            "custom_components.spinev.config_flow.SpinEvCharger",
            return_value=charger,
        ),
    ):
        yield charger


@pytest.fixture
def mock_ble_device(ble_device: BLEDevice) -> Generator[MagicMock]:
    """Make the Bluetooth manager resolve the charger's address."""
    # Both modules import the bluetooth component itself, so one patch of the
    # lookup covers the coordinator and the config flow alike.
    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ) as mock_lookup,
        patch(
            "custom_components.spinev.coordinator.close_stale_connections_by_address"
        ),
        patch(
            "homeassistant.components.bluetooth.async_address_reachability_diagnostics",
            return_value="No Bluetooth adapter or proxy is in range of it.",
        ),
        patch(
            "homeassistant.components.bluetooth.async_request_active_scan",
            new_callable=AsyncMock,
        ),
    ):
        yield mock_lookup


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the charger."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=SERIAL,
        unique_id=ADDRESS,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_charger: AsyncMock,
    mock_ble_device: MagicMock,
) -> MockConfigEntry:
    """Set the integration up and return its entry."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable the entities that ship disabled, so snapshots cover them."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
    ):
        yield


@pytest.fixture(name="snapshot")
def snapshot_fixture(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialize registry entries without their volatile ids and timestamps."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
