"""The Spin EV Charger integration."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .card import async_register_card
from .const import CONF_TRANSPORT, DOMAIN, PLATFORMS, TRANSPORT_BLE, TRANSPORT_OCPP
from .coordinator import SpinEvConfigEntry, SpinEvCoordinator
from .hub import OcppHubError, async_get_hub

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Offer the dashboard card wherever a dashboard can be shown."""
    if "frontend" in hass.config.components:
        await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SpinEvConfigEntry) -> bool:
    """Set up a charger from a config entry."""
    if entry.data[CONF_TRANSPORT] == TRANSPORT_OCPP:
        hub = async_get_hub(hass)
        try:
            await hub.async_acquire()
        except OcppHubError as err:
            raise ConfigEntryNotReady(str(err)) from err
        entry.async_on_unload(hub.async_release)

    coordinator = SpinEvCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SpinEvConfigEntry) -> bool:
    """Unload a config entry and hand the charger back."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_release()
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: SpinEvConfigEntry) -> bool:
    """Bring an entry from an older version up to date."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        # Every entry made before OCPP support used Bluetooth.
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_TRANSPORT: TRANSPORT_BLE},
            minor_version=2,
        )
    return True
