"""Dashboard card shipped with the Spin EV Charger integration."""

from pathlib import Path
from typing import Final

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

CARD_FILENAME: Final = "spinev-charger-card.js"
CARD_PATH: Final = Path(__file__).parent / "frontend" / CARD_FILENAME
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILENAME}"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and load it on every dashboard.

    The integration version is part of the URL, so browsers holding a cached
    copy fetch the card again after an update.
    """
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
