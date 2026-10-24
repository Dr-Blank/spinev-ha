"""Base entity for the Spin EV Charger integration."""

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN, MANUFACTURER, MODEL
from .coordinator import SpinEvCoordinator


class SpinEvEntity(CoordinatorEntity[SpinEvCoordinator]):
    """An entity backed by a charger status snapshot."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SpinEvCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description

        entry = coordinator.config_entry
        # The Bluetooth address for a charger first set up over Bluetooth, and
        # the charge point id for one set up over OCPP alone.
        device_key = entry.unique_id
        if TYPE_CHECKING:
            assert device_key is not None
        serial = entry.data[CONF_SERIAL]

        self._attr_unique_id = f"{device_key}_{description.key}"
        self._attr_device_info = DeviceInfo(
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=coordinator.config_entry.title,
            serial_number=serial,
            sw_version=coordinator.data.firmware_version,
        )
        if coordinator.address is not None:
            self._attr_device_info["connections"] = {
                (CONNECTION_BLUETOOTH, coordinator.address)
            }
        else:
            self._attr_device_info["identifiers"] = {(DOMAIN, device_key)}
