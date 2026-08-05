"""Binary sensors for the Spin EV Charger integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from spinev_ble import ChargerStatus

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTR_ALARMS
from .coordinator import SpinEvConfigEntry
from .entity import SpinEvEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SpinEvBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Spin EV binary sensor."""

    value_fn: Callable[[ChargerStatus], bool | None]


BINARY_SENSORS: tuple[SpinEvBinarySensorEntityDescription, ...] = (
    SpinEvBinarySensorEntityDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda status: status.is_charging if status.state else None,
    ),
    SpinEvBinarySensorEntityDescription(
        key="vehicle_connected",
        translation_key="vehicle_connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda status: status.state.has_vehicle if status.state else None,
    ),
    SpinEvBinarySensorEntityDescription(
        key="session_suspended",
        translation_key="session_suspended",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.state.is_suspended if status.state else None,
    ),
    SpinEvBinarySensorEntityDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda status: status.has_alarms,
    ),
)

LOAD_BALANCING_DESCRIPTION = BinarySensorEntityDescription(
    key="load_balancing",
    translation_key="load_balancing",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpinEvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(
                SpinEvBinarySensor(coordinator, description)
                for description in BINARY_SENSORS
            ),
            SpinEvLoadBalancingBinarySensor(coordinator, LOAD_BALANCING_DESCRIPTION),
        ]
    )


class SpinEvBinarySensor(SpinEvEntity, BinarySensorEntity):
    """A charger condition."""

    entity_description: SpinEvBinarySensorEntityDescription

    @property
    @override
    def available(self) -> bool:
        """Return True while the charger reports this condition."""
        return super().available and self.is_on is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True while the condition holds."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """List the active alarms behind a problem."""
        if self.entity_description.key != "problem":
            return None
        return {ATTR_ALARMS: list(self.coordinator.data.alarms)}


class SpinEvLoadBalancingBinarySensor(SpinEvEntity, BinarySensorEntity):
    """Whether the charger is sharing its supply with the installation.

    While this is on, delivered current can sit below the current limit with
    nothing being wrong: the charger is holding the whole installation under
    what the grid connection carries.
    """

    @property
    @override
    def available(self) -> bool:
        """Return True once the load balancing settings have been read."""
        return super().available and self.coordinator.load_balancing is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True while load balancing is enabled."""
        if (config := self.coordinator.load_balancing) is None:
            return None
        return config.enabled
