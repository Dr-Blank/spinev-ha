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

APPLY_CONFIG_DESCRIPTION = ButtonEntityDescription(
    key="apply_config",
    translation_key="apply_config",
    entity_category=EntityCategory.CONFIG,
)

RESTART_DESCRIPTION = ButtonEntityDescription(
    key="restart",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.CONFIG,
)

REFRESH_DESCRIPTION = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
    entity_category=EntityCategory.DIAGNOSTIC,
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
            SpinEvApplyConfigButton(coordinator, APPLY_CONFIG_DESCRIPTION),
            SpinEvRestartButton(coordinator, RESTART_DESCRIPTION),
            SpinEvRefreshButton(coordinator, REFRESH_DESCRIPTION),
        ]
    )


class SpinEvSyncClockButton(SpinEvEntity, ButtonEntity):
    """Set the charger's clock to the current time.

    Applying a clock change restarts the charger, which ends any session in
    progress.
    """

    @override
    async def async_press(self) -> None:
        """Sync the charger's clock to now, then wait out the restart."""
        await self.coordinator.async_execute(
            lambda charger: charger.async_sync_clock(), reboots=True
        )


class SpinEvApplyConfigButton(SpinEvEntity, ButtonEntity):
    """Send whatever the config numbers have been changed to.

    A timezone or start delay change is applied with a commit, which restarts
    the charger and ends any session in progress. A current limit on its own
    is not committed, so it takes effect without a restart.
    """

    @override
    async def async_press(self) -> None:
        """Apply whatever the config numbers currently show."""
        await self.coordinator.async_apply_config()


class SpinEvRestartButton(SpinEvEntity, ButtonEntity):
    """Restart the charger, which clears a fault without cutting its power."""

    @override
    async def async_press(self) -> None:
        """Restart the charger, interrupting any session in progress."""
        await self.coordinator.async_execute(
            lambda charger: charger.async_reboot(), reboots=True
        )


class SpinEvRefreshButton(SpinEvEntity, ButtonEntity):
    """Re-read the charger now instead of waiting for the next poll."""

    @override
    async def async_press(self) -> None:
        """Refresh, discarding any config edits not yet applied."""
        await self.coordinator.async_refresh_now()
