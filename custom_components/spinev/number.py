"""Numbers for the Spin EV Charger integration."""

from abc import abstractmethod
from collections.abc import Coroutine
import logging
from typing import Any, override

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
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import WRITE_DEBOUNCE
from .coordinator import SpinEvConfigEntry
from .entity import SpinEvEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

CURRENT_LIMIT_DESCRIPTION = NumberEntityDescription(
    key="current_limit",
    translation_key="current_limit",
    native_min_value=MIN_CURRENT_A,
    native_max_value=DEFAULT_MAX_CURRENT_A,
    native_step=1,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    mode=NumberMode.SLIDER,
    entity_category=EntityCategory.CONFIG,
)

RANDOM_DELAY_DESCRIPTION = NumberEntityDescription(
    key="random_delay",
    translation_key="random_delay",
    device_class=NumberDeviceClass.DURATION,
    native_min_value=0,
    native_max_value=MAX_RANDOM_DELAY_S,
    native_step=1,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpinEvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SpinEvCurrentLimitNumber(coordinator, CURRENT_LIMIT_DESCRIPTION),
            SpinEvRandomDelayNumber(coordinator, RANDOM_DELAY_DESCRIPTION),
        ]
    )


class SpinEvNumber(SpinEvEntity, NumberEntity):
    """A charger setting that reaches the charger once the value settles.

    Every write costs a connect and several seconds of Bluetooth, so a value
    the user is still moving is shown straight away and sent behind them.
    """

    _debouncer: Debouncer[Coroutine[Any, Any, None]]
    _pending_value: float | None = None

    @override
    async def async_added_to_hass(self) -> None:
        """Start the write debouncer."""
        self._debouncer = Debouncer(
            hass=self.hass,
            logger=_LOGGER,
            cooldown=WRITE_DEBOUNCE.total_seconds(),
            immediate=False,
            function=self._async_write_pending,
        )
        await super().async_added_to_hass()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Drop a write that has not left yet, since the link goes with it."""
        self._debouncer.async_shutdown()
        await super().async_will_remove_from_hass()

    @property
    @override
    def native_value(self) -> float | None:
        """Return the value on its way to the charger, else the reported one."""
        if self._pending_value is not None:
            return self._pending_value
        return self._reported_value

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Hold the value, and write it once the user stops changing it."""
        self._pending_value = value
        self.async_write_ha_state()
        await self._debouncer.async_call()

    async def _async_write_pending(self) -> None:
        """Send the held value to the charger."""
        value = self._pending_value
        assert value is not None
        try:
            await self._async_write(value)
        finally:
            # The debouncer swallows the error, so a write that failed has to
            # stop showing its value or the charger looks like it took it.
            # A value changed again mid-write belongs to the write behind this
            # one and stays.
            if self._pending_value == value:
                self._pending_value = None
            self.async_write_ha_state()

    @property
    @abstractmethod
    def _reported_value(self) -> float | None:
        """Return the value the charger last reported."""

    @abstractmethod
    async def _async_write(self, value: float) -> None:
        """Send a settled value to the charger."""


class SpinEvCurrentLimitNumber(SpinEvNumber):
    """How much current the charger will deliver.

    The charger refuses this change during a session, telling the user to stop
    charging first, so it is normally set between sessions and takes effect on
    the next one.
    """

    @property
    @override
    def _reported_value(self) -> float | None:
        """Return the limit the charger last reported."""
        return self.coordinator.data.current_limit_a

    @override
    async def _async_write(self, value: float) -> None:
        """Send the new limit to the charger."""
        await self.coordinator.async_set_current_limit(value)


class SpinEvRandomDelayNumber(SpinEvNumber):
    """How long the charger waits before starting a session.

    Applying this restarts the charger, which ends any session in progress, so
    the debounce also keeps a corrected value from costing two restarts.
    """

    @property
    @override
    def _reported_value(self) -> float | None:
        """Return the delay the charger last reported."""
        # Float so the value does not change shape when a pending write clears.
        delay = self.coordinator.random_delay_s
        return None if delay is None else float(delay)

    @override
    async def _async_write(self, value: float) -> None:
        """Send the new delay to the charger, restarting it."""
        await self.coordinator.async_set_random_delay(int(value))
