"""Numbers for the Spin EV Charger integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from spinev_ble import DEFAULT_MAX_CURRENT_A, MIN_CURRENT_A

# Not re-exported from the package root, unlike the current limit bounds.
from spinev_ble.const import MAX_RANDOM_DELAY_S

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfElectricCurrent, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ChargerConfig, SpinEvConfigEntry
from .entity import SpinEvEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SpinEvNumberEntityDescription(NumberEntityDescription):
    """Describes a Spin EV number.

    These edit the coordinator's pending config draft directly, with no BLE
    write: sending each intermediate value while a slider is being dragged
    would be wasteful, so nothing goes to the charger until "Apply config" is
    pressed.
    """

    value_fn: Callable[[ChargerConfig], float]
    set_fn: Callable[[ChargerConfig, float], None]


def _set_current_limit(config: ChargerConfig, value: float) -> None:
    config.current_limit_a = value


def _set_timezone_hours(config: ChargerConfig, value: float) -> None:
    config.timezone_hours = int(value)


def _set_timezone_minutes(config: ChargerConfig, value: float) -> None:
    config.timezone_minutes = int(value)


def _set_random_delay(config: ChargerConfig, value: float) -> None:
    config.random_delay_s = int(value)


NUMBERS: tuple[SpinEvNumberEntityDescription, ...] = (
    SpinEvNumberEntityDescription(
        key="current_limit",
        translation_key="current_limit",
        native_min_value=MIN_CURRENT_A,
        native_max_value=DEFAULT_MAX_CURRENT_A,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda config: config.current_limit_a,
        set_fn=_set_current_limit,
    ),
    SpinEvNumberEntityDescription(
        key="timezone_hours",
        translation_key="timezone_hours",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda config: config.timezone_hours,
        set_fn=_set_timezone_hours,
    ),
    SpinEvNumberEntityDescription(
        key="timezone_minutes",
        translation_key="timezone_minutes",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda config: config.timezone_minutes,
        set_fn=_set_timezone_minutes,
    ),
    SpinEvNumberEntityDescription(
        key="random_delay",
        translation_key="random_delay",
        device_class=NumberDeviceClass.DURATION,
        native_min_value=0,
        native_max_value=MAX_RANDOM_DELAY_S,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda config: config.random_delay_s,
        set_fn=_set_random_delay,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpinEvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        SpinEvNumber(coordinator, description) for description in NUMBERS
    )


class SpinEvNumber(SpinEvEntity, NumberEntity):
    """An editable draft of a charger config value, applied separately."""

    entity_description: SpinEvNumberEntityDescription

    @property
    @override
    def available(self) -> bool:
        """Return True once the pending config draft has been seeded."""
        return super().available and self.coordinator.pending is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return the draft value, not necessarily what the charger has."""
        if self.coordinator.pending is None:
            return None
        return self.entity_description.value_fn(self.coordinator.pending)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Update the draft. Does not touch the charger; "Apply config" does."""
        if self.coordinator.pending is None:
            return
        self.entity_description.set_fn(self.coordinator.pending, value)
        self.async_write_ha_state()
