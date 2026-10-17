"""The Spin EV Charger integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .card import async_register_card
from .const import DOMAIN, PLATFORMS
from .coordinator import SpinEvConfigEntry, SpinEvCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Offer the dashboard card wherever a dashboard can be shown."""
    if "frontend" in hass.config.components:
        await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SpinEvConfigEntry) -> bool:
    """Set up a charger from a config entry."""
    coordinator = SpinEvCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SpinEvConfigEntry) -> bool:
    """Unload a config entry and hand the charger back."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_release()
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: SpinEvConfigEntry) -> None:
    """Reload the entry so a changed connection mode takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
