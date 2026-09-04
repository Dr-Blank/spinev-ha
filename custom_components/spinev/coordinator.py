"""Coordinator for the Spin EV Charger integration."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import override

from bleak.backends.device import BLEDevice
from bleak_retry_connector import close_stale_connections_by_address
from habluetooth import HaBleakClientWrapper
from spinev_ble import (
    ChargerStatus,
    LoadBalancingConfig,
    SpinEvBusyError,
    SpinEvCharger,
    SpinEvCommandRejectedError,
    SpinEvError,
)

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CHARGING_INTERVAL,
    CONF_CONNECTION_MODE,
    DEFAULT_CONNECTION_MODE,
    DOMAIN,
    IDLE_INTERVAL,
    MODE_PERSISTENT,
    REBOOT_SETTLE,
)

_LOGGER = logging.getLogger(__name__)

type SpinEvConfigEntry = ConfigEntry[SpinEvCoordinator]


class SpinEvCoordinator(DataUpdateCoordinator[ChargerStatus]):
    """Poll one charger over Bluetooth.

    The charger accepts a single Bluetooth client at a time, so holding the
    link open keeps the phone app out. Which of the two behaviours applies is
    chosen per config entry.

    The poll interval also adapts to what the charger is doing: short while a
    vehicle is charging so power and alarms stay current, long while idle so
    a per-poll connection leaves the phone app long uncontested stretches.
    """

    config_entry: SpinEvConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SpinEvConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=CHARGING_INTERVAL,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self._keep_connected = (
            entry.options.get(CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE)
            == MODE_PERSISTENT
        )
        self._charger: SpinEvCharger | None = None
        #: The charger takes one Bluetooth client at a time, and a debounced
        #: write runs outside the platform's own serialization.
        self._link = asyncio.Lock()
        #: Start delay as the charger last reported it. Only this integration
        #: and the phone app change it, so it is read once rather than polled.
        self.random_delay_s: int | None = None
        #: How the charger shares its supply. Read only, and read once for the
        #: same reason, since it takes seven registers to fetch.
        self.load_balancing: LoadBalancingConfig | None = None

    @override
    async def _async_setup(self) -> None:
        """Clear any stale link, then read the settings that are not polled."""
        await close_stale_connections_by_address(self.address)
        if self._async_ble_device() is None:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={
                    "address": self.address,
                    "reason": bluetooth.async_address_reachability_diagnostics(
                        self.hass, self.address, BluetoothReachabilityIntent.CONNECTION
                    ),
                },
            )

        charger = await self._async_charger()
        try:
            await charger.async_connect()
            self.random_delay_s = await charger.async_get_random_delay()
            await self._async_read_load_balancing(charger)
        except SpinEvError as err:
            await self.async_release()
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_read",
                translation_placeholders={"error": str(err)},
            ) from err
        finally:
            if not self._keep_connected:
                await self.async_release()

    @override
    async def _async_update_data(self) -> ChargerStatus:
        """Read a full status snapshot."""
        async with self._link:
            charger = await self._async_charger()
            try:
                await charger.async_connect()
                status = await charger.async_get_status()
            except SpinEvError as err:
                await self.async_release()
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_read",
                    translation_placeholders={"error": str(err)},
                ) from err
            finally:
                if not self._keep_connected:
                    await self.async_release()

        # A suspended session can resume without a command, so it is polled at
        # the charging rate rather than the idle one.
        session_open = status.state is not None and (
            status.state.is_charging or status.state.is_suspended
        )
        self.update_interval = CHARGING_INTERVAL if session_open else IDLE_INTERVAL
        return status

    async def _async_read_load_balancing(self, charger: SpinEvCharger) -> None:
        """Read the load balancing settings, tolerating models without them."""
        # Not every model answers on these registers, and the rest of the
        # integration works without them, so a failure here only drops those
        # entities rather than failing setup.
        try:
            self.load_balancing = await charger.async_get_load_balancing()
        except SpinEvError as err:
            _LOGGER.debug("Charger %s has no load balancing: %s", self.address, err)
            self.load_balancing = None

    async def async_start_charging(self) -> None:
        """Start a charging session."""
        await self._async_execute(lambda charger: charger.async_start_charging())

    async def async_stop_charging(self) -> None:
        """Stop the charging session."""
        await self._async_execute(lambda charger: charger.async_stop_charging())

    async def async_set_current_limit(self, amps: float) -> None:
        """Set the charging current limit.

        Not committed: a current limit takes effect without one, and the commit
        would restart the charger and end the very session it applies to.
        """
        await self._async_execute(
            lambda charger: charger.async_set_current_limit(amps, commit=False)
        )

    async def async_set_random_delay(self, seconds: int) -> None:
        """Set the delay before charging starts, restarting the charger."""
        await self._async_execute(
            lambda charger: charger.async_set_random_delay(seconds), reboots=True
        )
        self.random_delay_s = seconds
        self.async_update_listeners()

    async def async_sync_clock(self) -> None:
        """Set the charger's clock to Home Assistant's time zone, then restart."""
        await self._async_execute(
            lambda charger: charger.async_sync_clock(dt_util.now()), reboots=True
        )

    async def async_reboot(self) -> None:
        """Restart the charger, which clears a fault without cutting its power."""
        await self._async_execute(lambda charger: charger.async_reboot(), reboots=True)

    async def _async_execute(
        self,
        action: Callable[[SpinEvCharger], Awaitable[None]],
        *,
        reboots: bool = False,
    ) -> None:
        """Run a write action against the charger, then refresh.

        Shares the same connect and release policy as a poll, so a write does
        not leave a per-poll connection open past its turn.

        ``reboots`` marks an action that ends in a commit. The charger restarts
        a few seconds later and drops the link, so the link is released even in
        persistent mode and the refresh is deferred until it is back.
        """
        async with self._link:
            charger = await self._async_charger()
            try:
                await charger.async_connect()
                await action(charger)
            except SpinEvBusyError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="charger_busy"
                ) from err
            except SpinEvCommandRejectedError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="command_rejected"
                ) from err
            except SpinEvError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="cannot_write",
                    translation_placeholders={"error": str(err)},
                ) from err
            finally:
                if reboots or not self._keep_connected:
                    await self.async_release()

        if not reboots:
            await self.async_request_refresh()
            return

        self.config_entry.async_create_background_task(
            self.hass, self._async_refresh_after_reboot(), f"{DOMAIN} reboot refresh"
        )

    async def _async_refresh_after_reboot(self) -> None:
        """Wait out the restart a commit triggers, then re-read the charger."""
        await asyncio.sleep(REBOOT_SETTLE.total_seconds())
        await self.async_refresh()

    async def async_release(self) -> None:
        """Drop the link so another client can reach the charger."""
        charger, self._charger = self._charger, None
        if charger is not None:
            await charger.async_disconnect()

    async def _async_charger(self) -> SpinEvCharger:
        """Return a client, rebuilding it against a fresh device if needed."""
        if self._charger is not None:
            if self._charger.is_connected:
                return self._charger
            await self.async_release()

        ble_device = self._async_ble_device()
        if ble_device is None:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={
                    "address": self.address,
                    "reason": bluetooth.async_address_reachability_diagnostics(
                        self.hass, self.address, BluetoothReachabilityIntent.CONNECTION
                    ),
                },
            )

        self._charger = SpinEvCharger(ble_device, client_class=HaBleakClientWrapper)
        return self._charger

    def _async_ble_device(self) -> BLEDevice | None:
        """Look the charger up in the Bluetooth manager."""
        return bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
