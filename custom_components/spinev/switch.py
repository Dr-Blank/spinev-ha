"""Switches for the Spin EV Charger integration."""

from typing import Any, override

from spinev_ble import ChargerState

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import SpinEvConfigEntry
from .entity import SpinEvEntity

PARALLEL_UPDATES = 1

CHARGING_DESCRIPTION = SwitchEntityDescription(
    key="charging",
    translation_key="charging",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpinEvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger switches."""
    coordinator = entry.runtime_data
    async_add_entities([SpinEvChargingSwitch(coordinator, CHARGING_DESCRIPTION)])


class SpinEvChargingSwitch(SpinEvEntity, SwitchEntity):
    """Start and stop charging."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True while a session is open.

        A session that either end has suspended counts as on: the vehicle
        pausing is an ordinary part of a charge and resumes without a command,
        so reporting it as off would make the switch flap mid-session.
        """
        state = self.coordinator.data.state
        if state is None:
            return None
        return state.is_charging or state.is_suspended

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start charging.

        The charger's own control pilot circuit already refuses to energise
        without a vehicle presenting a valid signal, so this cannot itself
        make power flow with nothing plugged in. It is rejected here anyway,
        since sending a start command that can only silently do nothing is
        more confusing than refusing it up front.
        """
        state = self.coordinator.data.state
        if state is ChargerState.BOOTING:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="charger_booting",
            )
        if state is None or not state.has_vehicle:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_vehicle_connected",
            )
        await self.coordinator.async_start_charging()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop charging."""
        await self.coordinator.async_stop_charging()
