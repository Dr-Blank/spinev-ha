"""Tests for the dashboard card the Spin EV Charger integration serves."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.spinev.card import CARD_PATH, CARD_URL
from custom_components.spinev.const import DOMAIN


async def test_card_is_served_and_loaded(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """With a frontend running, every dashboard loads the card."""
    hass.config.components.add("frontend")

    with patch("custom_components.spinev.card.add_extra_js_url") as add_url:
        assert await async_setup_component(hass, DOMAIN, {})

    (url,) = add_url.call_args.args[1:]
    assert url.startswith(f"{CARD_URL}?v=")
    client = await hass_client_no_auth()
    response = await client.get(url)
    assert response.status == 200
    assert await response.text() == CARD_PATH.read_text()


async def test_card_is_skipped_without_a_frontend(hass: HomeAssistant) -> None:
    """A headless instance has no dashboards to load the card into."""
    with patch("custom_components.spinev.card.add_extra_js_url") as add_url:
        assert await async_setup_component(hass, DOMAIN, {})

    add_url.assert_not_called()
