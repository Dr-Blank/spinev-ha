"""Sensors for the Spin EV Charger integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from spinev_ble import ChargerState, ChargerStatus, LoadBalancingConfig

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import SpinEvConfigEntry
from .entity import SpinEvEntity

PARALLEL_UPDATES = 0

STATE_OPTIONS = [state.name.lower() for state in ChargerState]


@dataclass(frozen=True, kw_only=True)
class SpinEvSensorEntityDescription(SensorEntityDescription):
    """Describes a Spin EV sensor."""

    value_fn: Callable[[ChargerStatus], StateType]


@dataclass(frozen=True, kw_only=True)
class SpinEvLoadBalancingSensorEntityDescription(SensorEntityDescription):
    """Describes a Spin EV load balancing sensor.

    These describe the supply feeding the charger rather than the charger
    itself, and the charger only acts on them while load balancing is enabled.
    """

    value_fn: Callable[[LoadBalancingConfig], StateType]


SENSORS: tuple[SpinEvSensorEntityDescription, ...] = (
    SpinEvSensorEntityDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        value_fn=lambda status: status.state.name.lower() if status.state else None,
    ),
    SpinEvSensorEntityDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.power_w,
    ),
    SpinEvSensorEntityDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.voltage_v,
    ),
    SpinEvSensorEntityDescription(
        key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.current_a,
    ),
    SpinEvSensorEntityDescription(
        key="current_limit",
        translation_key="current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.current_limit_a,
    ),
    SpinEvSensorEntityDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda status: status.session_energy_kwh,
    ),
    SpinEvSensorEntityDescription(
        key="session_duration",
        translation_key="session_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda status: status.session_seconds,
    ),
    SpinEvSensorEntityDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda status: status.lifetime_energy_kwh,
    ),
    SpinEvSensorEntityDescription(
        key="lifetime_duration",
        translation_key="lifetime_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.lifetime_seconds,
    ),
)

LOAD_BALANCING_SENSORS: tuple[SpinEvLoadBalancingSensorEntityDescription, ...] = (
    SpinEvLoadBalancingSensorEntityDescription(
        key="grid_current_limit",
        translation_key="grid_current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda config: config.grid_current_limit_a,
    ),
    SpinEvLoadBalancingSensorEntityDescription(
        key="safe_current_offset",
        translation_key="safe_current_offset",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda config: config.safe_current_offset_a,
    ),
    SpinEvLoadBalancingSensorEntityDescription(
        key="reduce_current_offset",
        translation_key="reduce_current_offset",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda config: config.reduce_current_offset_a,
    ),
    SpinEvLoadBalancingSensorEntityDescription(
        key="max_grid_power",
        translation_key="max_grid_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda config: config.max_grid_power_w,
    ),
    # Source and priority are small enums whose meanings the protocol does not
    # spell out, so the raw number is all that can honestly be shown.
    SpinEvLoadBalancingSensorEntityDescription(
        key="load_balancing_source",
        translation_key="load_balancing_source",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda config: config.source,
    ),
    SpinEvLoadBalancingSensorEntityDescription(
        key="load_balancing_priority",
        translation_key="load_balancing_priority",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda config: config.priority,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpinEvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(SpinEvSensor(coordinator, description) for description in SENSORS),
            *(
                SpinEvLoadBalancingSensor(coordinator, description)
                for description in LOAD_BALANCING_SENSORS
            ),
        ]
    )


class SpinEvSensor(SpinEvEntity, SensorEntity):
    """A value read from the charger."""

    entity_description: SpinEvSensorEntityDescription

    @property
    @override
    def available(self) -> bool:
        """Return True while the charger reports this value."""
        return super().available and self.native_value is not None

    @property
    @override
    def native_value(self) -> StateType:
        """Return the value reported by the charger."""
        return self.entity_description.value_fn(self.coordinator.data)


class SpinEvLoadBalancingSensor(SpinEvEntity, SensorEntity):
    """A load balancing setting read from the charger."""

    entity_description: SpinEvLoadBalancingSensorEntityDescription

    @property
    @override
    def available(self) -> bool:
        """Return True once the load balancing settings have been read."""
        return super().available and self.coordinator.load_balancing is not None

    @property
    @override
    def native_value(self) -> StateType:
        """Return the setting as the charger last reported it."""
        if (config := self.coordinator.load_balancing) is None:
            return None
        return self.entity_description.value_fn(config)
