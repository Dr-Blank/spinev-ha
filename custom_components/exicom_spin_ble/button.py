"""Buttons for the Spin EV Charger integration."""

from typing import override

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SpinEvConfigEntry
from .entity import SpinEvEntity

PARALLEL_UPDATES = 1

SYNC_CLOCK_DESCRIPTION = ButtonEntityDescription(
    key="sync_clock",
    translation_key="sync_clock",
    entity_category=EntityCategory.CONFIG,
)

RESTART_DESCRIPTION = ButtonEntityDescription(
    key="restart",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpinEvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SpinEvSyncClockButton(coordinator, SYNC_CLOCK_DESCRIPTION),
            SpinEvRestartButton(coordinator, RESTART_DESCRIPTION),
        ]
    )


class SpinEvSyncClockButton(SpinEvEntity, ButtonEntity):
    """Set the charger's clock to Home Assistant's current time.

    Applying a clock change restarts the charger, which ends any session in
    progress.
    """

    @override
    async def async_press(self) -> None:
        """Sync the charger's clock to now, then wait out the restart."""
        await self.coordinator.async_sync_clock()


class SpinEvRestartButton(SpinEvEntity, ButtonEntity):
    """Restart the charger, which clears a fault without cutting its power."""

    @override
    async def async_press(self) -> None:
        """Restart the charger, interrupting any session in progress."""
        await self.coordinator.async_reboot()
