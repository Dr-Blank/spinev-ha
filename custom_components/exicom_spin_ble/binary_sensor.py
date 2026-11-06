"""Binary sensors for the Spin EV Charger integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from spinev_ble import ChargerStatus, LoadBalancingConfig

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import ATTR_ALARMS
from .coordinator import SpinEvConfigEntry, SpinEvCoordinator
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

VEHICLE_CONNECTED_DESCRIPTION = BinarySensorEntityDescription(
    key="vehicle_connected",
    translation_key="vehicle_connected",
    device_class=BinarySensorDeviceClass.PLUG,
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
    entities: list[BinarySensorEntity] = [
        SpinEvBinarySensor(coordinator, description) for description in BINARY_SENSORS
    ]
    entities.append(
        SpinEvVehicleConnectedBinarySensor(coordinator, VEHICLE_CONNECTED_DESCRIPTION)
    )
    if (config := coordinator.load_balancing) is not None:
        entities.append(
            SpinEvLoadBalancingBinarySensor(
                coordinator, LOAD_BALANCING_DESCRIPTION, config
            )
        )
    async_add_entities(entities)


class SpinEvBinarySensor(SpinEvEntity, BinarySensorEntity):
    """A charger condition."""

    entity_description: SpinEvBinarySensorEntityDescription

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


class SpinEvVehicleConnectedBinarySensor(
    SpinEvEntity, BinarySensorEntity, RestoreEntity
):
    """Whether a vehicle is plugged in, on or off and never unknown.

    A restart during a fault leaves no reading of the plug, so the last state
    is restored. With no state to restore either, it reads off.
    """

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the last state if no reading has shown the plug yet."""
        await super().async_added_to_hass()
        if (
            self.coordinator.vehicle_connected is None
            and (last_state := await self.async_get_last_state()) is not None
            and last_state.state in (STATE_ON, STATE_OFF)
        ):
            self.coordinator.vehicle_connected = last_state.state == STATE_ON

    @property
    @override
    def is_on(self) -> bool:
        """Return True while a vehicle is plugged in."""
        return bool(self.coordinator.vehicle_connected)


class SpinEvLoadBalancingBinarySensor(SpinEvEntity, BinarySensorEntity):
    """Whether the charger is sharing its supply with the installation.

    While this is on, delivered current can sit below the current limit with
    nothing being wrong: the charger is holding the whole installation under
    what the grid connection carries. The setting is read once per config
    entry, so it is resolved here rather than on every state write.
    """

    def __init__(
        self,
        coordinator: SpinEvCoordinator,
        description: BinarySensorEntityDescription,
        config: LoadBalancingConfig,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description)
        self._attr_is_on = config.enabled
