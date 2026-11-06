"""Diagnostics for the Spin EV Charger integration."""

from dataclasses import asdict
import re
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import CONF_CHARGE_POINT_ID, CONF_SERIAL
from .coordinator import SpinEvConfigEntry

TO_REDACT = {CONF_ADDRESS, CONF_CHARGE_POINT_ID, CONF_SERIAL}
_FREE_TEXT_FIELDS = {"error", "info"}


def _redacted_events(entry: SpinEvConfigEntry) -> list[dict[str, Any]]:
    """Return the recent events, with identifiers removed from free text.

    Errors can quote a transport's own message, and a charger's status can carry
    text of its own, either of which may name the charger.
    """
    identifiers = {
        str(identifier)
        for identifier in (
            entry.title,
            *(entry.data.get(key) for key in TO_REDACT),
        )
        if identifier
    }
    pattern = re.compile("|".join(map(re.escape, identifiers)), re.IGNORECASE)
    return [
        {
            key: pattern.sub(REDACTED, value)
            if key in _FREE_TEXT_FIELDS and value
            else value
            for key, value in event.items()
        }
        for event in entry.runtime_data.events
    ]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SpinEvConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    status = asdict(coordinator.data)
    status["state"] = status["state"].name if status["state"] else None
    status["alarms"] = list(status["alarms"])

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "status": status,
        "vehicle_connected": coordinator.vehicle_connected,
        "recent_events": _redacted_events(entry),
        "random_delay_s": coordinator.random_delay_s,
        "load_balancing": asdict(coordinator.load_balancing)
        if coordinator.load_balancing
        else None,
    }
