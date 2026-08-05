"""Diagnostics for the Spin EV Charger integration."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL
from .coordinator import SpinEvConfigEntry

TO_REDACT = {CONF_ADDRESS, CONF_SERIAL}


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
        "config": {
            "confirmed": asdict(coordinator.confirmed)
            if coordinator.confirmed
            else None,
            "pending": asdict(coordinator.pending) if coordinator.pending else None,
        },
        "load_balancing": asdict(coordinator.load_balancing)
        if coordinator.load_balancing
        else None,
    }
