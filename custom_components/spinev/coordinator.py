"""Coordinator for the Spin EV Charger integration."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CHARGING_INTERVAL,
    CONF_CONNECTION_MODE,
    CONF_IDLE_INTERVAL,
    DEFAULT_CHARGING_INTERVAL,
    DEFAULT_CONNECTION_MODE,
    DEFAULT_IDLE_INTERVAL,
    DOMAIN,
    INITIAL_INTERVAL,
    MODE_PERSISTENT,
    REBOOT_SETTLE,
)

_LOGGER = logging.getLogger(__name__)

type SpinEvConfigEntry = ConfigEntry[SpinEvCoordinator]


@dataclass
class ChargerConfig:
    """A snapshot of the charger's editable config."""

    current_limit_a: float
    timezone_hours: int
    timezone_minutes: int
    random_delay_s: int


class SpinEvCoordinator(DataUpdateCoordinator[ChargerStatus]):
    """Poll one charger over Bluetooth.

    The charger accepts a single Bluetooth client at a time, so holding the
    link open keeps the phone app out. Which of the two behaviours applies is
    chosen per config entry.

    The poll interval also adapts to what the charger is doing: short while a
    vehicle is charging so power and alarms stay current, long while idle so
    a per-poll connection leaves the phone app long uncontested stretches.
    Both bounds come from options.
    """

    config_entry: SpinEvConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SpinEvConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=INITIAL_INTERVAL,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self._keep_connected = (
            entry.options.get(CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE)
            == MODE_PERSISTENT
        )
        self._charging_interval = timedelta(
            seconds=entry.options.get(CONF_CHARGING_INTERVAL, DEFAULT_CHARGING_INTERVAL)
        )
        self._idle_interval = timedelta(
            seconds=entry.options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL)
        )
        self._charger: SpinEvCharger | None = None
        #: Last config actually confirmed on the charger.
        self.confirmed: ChargerConfig | None = None
        #: Draft edited by the config number entities; not sent until applied.
        self.pending: ChargerConfig | None = None
        #: How the charger shares its supply. Read only, and read on the same
        #: ticks as the config, since it takes seven registers to fetch.
        self.load_balancing: LoadBalancingConfig | None = None
        self._sync_config_next = True

    @override
    async def _async_setup(self) -> None:
        """Clear any link left over from a previous run."""
        await close_stale_connections_by_address(self.address)
        if self._async_ble_device() is None:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"address": self.address},
            )

    @override
    async def _async_update_data(self) -> ChargerStatus:
        """Read a full status snapshot.

        Neither the timezone, the start delay nor the load balancing settings
        are part of the status registers, and together they cost nine extra
        round trips, so they are only read on the ticks that ask for it: the
        first poll, a Refresh, and after a config is applied. Re-reading the
        editable ones every tick would also overwrite an edit the user has not
        applied yet.
        """
        charger = await self._async_charger()
        try:
            await charger.async_connect()
            status = await charger.async_get_status()
            if self._sync_config_next:
                await self._async_sync_config(charger, status)
                self._sync_config_next = False
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
        self.update_interval = (
            self._charging_interval if session_open else self._idle_interval
        )
        return status

    async def _async_sync_config(
        self, charger: SpinEvCharger, status: ChargerStatus
    ) -> None:
        """Reset the config draft and load balancing to what the charger says."""
        hours, minutes = await charger.async_get_timezone()
        delay = await charger.async_get_random_delay()
        current_limit_a = status.current_limit_a or 0.0
        self.confirmed = ChargerConfig(current_limit_a, hours, minutes, delay)
        self.pending = ChargerConfig(current_limit_a, hours, minutes, delay)

        # Not every model answers on the load balancing registers, and the rest
        # of the integration works without them, so a failure here only drops
        # those entities rather than failing the poll.
        try:
            self.load_balancing = await charger.async_get_load_balancing()
        except SpinEvError as err:
            _LOGGER.debug("Charger %s has no load balancing: %s", self.address, err)
            self.load_balancing = None

    async def async_refresh_now(self) -> None:
        """Re-read the charger on demand, discarding any unapplied config edits."""
        self._sync_config_next = True
        await self.async_refresh()

    async def async_apply_config(self) -> None:
        """Send only the changed parts of the pending config, then confirm it."""
        pending, confirmed = self.pending, self.confirmed
        if pending is None or confirmed is None:
            return

        current_limit_changed = pending.current_limit_a != confirmed.current_limit_a
        timezone_changed = (
            pending.timezone_hours != confirmed.timezone_hours
            or pending.timezone_minutes != confirmed.timezone_minutes
        )
        random_delay_changed = pending.random_delay_s != confirmed.random_delay_s
        # Only these two need the commit that restarts the charger. A current
        # limit takes effect without one, and committing it would end the very
        # session the new limit was meant to apply to.
        needs_commit = timezone_changed or random_delay_changed
        if not current_limit_changed and not needs_commit:
            return

        async def action(charger: SpinEvCharger) -> None:
            if current_limit_changed:
                # Left at allow_while_charging=False on purpose: the charger's
                # own app only ever changes this between sessions, and what a
                # mid-session write does to a live charge is unestablished.
                await charger.async_set_current_limit(
                    pending.current_limit_a, commit=False
                )
            if timezone_changed:
                await charger.async_set_timezone(
                    pending.timezone_hours, pending.timezone_minutes, commit=False
                )
            if random_delay_changed:
                await charger.async_set_random_delay(
                    pending.random_delay_s, commit=False
                )
            if needs_commit:
                await charger.async_commit()

        self._sync_config_next = True
        await self.async_execute(action, reboots=needs_commit)

    async def async_execute(
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

        self._sync_config_next = True
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
                translation_placeholders={"address": self.address},
            )

        self._charger = SpinEvCharger(ble_device, client_class=HaBleakClientWrapper)
        return self._charger

    def _async_ble_device(self) -> BLEDevice | None:
        """Look the charger up in the Bluetooth manager."""
        return bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
