"""The OCPP central system shared by every charger reached over OCPP."""

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import datetime
import logging

from ocpp_csms import (
    BootEvent,
    CentralSystem,
    ChargePoint,
    ChargePointEvent,
    ConnectedEvent,
    CsmsError,
    DisconnectedEvent,
)

from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_call_later
from homeassistant.util.hass_dict import HassKey

from .const import (
    CONF_CHARGE_POINT_ID,
    CONF_TRANSPORT,
    DOMAIN,
    OCPP_PORT,
    OCPP_STOP_DELAY,
    TRANSPORT_OCPP,
)
from .util import is_same_charger, mask

_LOGGER = logging.getLogger(__name__)

type EventCallback = Callable[[ChargePointEvent], None]

HUB_KEY: HassKey[SpinEvOcppHub] = HassKey(f"{DOMAIN}_ocpp_hub")

#: Interface the central system listens on, every one when None.
OCPP_HOST: str | None = None


class OcppHubError(HomeAssistantError):
    """The central system could not be started."""


@callback
def async_get_hub(hass: HomeAssistant) -> SpinEvOcppHub:
    """Return the shared hub, creating it, unstarted, on first use."""
    if (hub := hass.data.get(HUB_KEY)) is None:
        hub = hass.data[HUB_KEY] = SpinEvOcppHub(hass)
    return hub


class SpinEvOcppHub:
    """Run one OCPP central system for every charger that needs it.

    Config entries and setup flows each hold the hub while they use it. The
    central system starts with the first holder and stops a little after the
    last one lets go, unless an entry is still waiting for its charger to
    connect.

    A charger that connects without belonging to an entry, or to a flow
    waiting for it, starts a discovery flow.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the hub."""
        self.hass = hass
        self._central_system: CentralSystem | None = None
        self._users = 0
        self._lock = asyncio.Lock()
        self._stop_later: CALLBACK_TYPE | None = None
        self._unsub_ha_stop: CALLBACK_TYPE | None = None
        self._listeners: dict[str, list[EventCallback]] = {}
        #: Charge point ids that a flow is waiting for, so their connection
        #: is not also offered as a discovery.
        self._expected: Counter[str] = Counter()

    @property
    def port(self) -> int:
        """TCP port the central system listens on."""
        if self._central_system is None:
            return OCPP_PORT
        return self._central_system.port

    async def async_acquire(self) -> None:
        """Hold the hub, starting the central system if it is not running.

        :raises OcppHubError: if the central system cannot listen on its port.
        """
        async with self._lock:
            if self._stop_later is not None:
                self._stop_later()
                self._stop_later = None
            if self._central_system is None:
                central_system = CentralSystem(host=OCPP_HOST, port=OCPP_PORT)
                try:
                    await central_system.async_start()
                except CsmsError as err:
                    _LOGGER.debug("OCPP central system failed to start: %s", err)
                    raise OcppHubError(
                        translation_domain=DOMAIN,
                        translation_key="ocpp_port_in_use",
                        translation_placeholders={
                            "port": str(OCPP_PORT),
                            "error": str(err),
                        },
                    ) from err
                central_system.add_listener(self._handle_event)
                self._central_system = central_system
                self._unsub_ha_stop = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STOP, self._async_handle_ha_stop
                )
                _LOGGER.debug(
                    "OCPP central system listening on port %s", central_system.port
                )
            self._users += 1
            _LOGGER.debug("OCPP central system held by %s users", self._users)

    @callback
    def async_release(self) -> None:
        """Let go of the hub, stopping it later if nobody else holds it."""
        self._users -= 1
        _LOGGER.debug("OCPP central system held by %s users", self._users)
        if self._users == 0 and self._stop_later is None:
            _LOGGER.debug(
                "OCPP central system unused, stopping in %s unless held again",
                OCPP_STOP_DELAY,
            )
            self._async_stop_later()

    @callback
    def _async_stop_later(self) -> None:
        self._stop_later = async_call_later(
            self.hass, OCPP_STOP_DELAY, self._async_stop_if_unused
        )

    async def _async_stop_if_unused(self, _now: datetime) -> None:
        async with self._lock:
            self._stop_later = None
            if self._users:
                return
            # An entry retrying setup lets go between attempts, and its retries
            # grow further apart than the stop delay, so stopping would turn
            # its charger away every time it reconnects.
            if any(
                entry.state is ConfigEntryState.SETUP_RETRY
                for entry in self._ocpp_entries()
            ):
                _LOGGER.debug(
                    "OCPP central system kept for an entry waiting for its charger"
                )
                self._async_stop_later()
                return
            await self._async_stop()

    async def _async_handle_ha_stop(self, _event: Event) -> None:
        self._unsub_ha_stop = None
        async with self._lock:
            await self._async_stop()

    async def _async_stop(self) -> None:
        if self._stop_later is not None:
            self._stop_later()
            self._stop_later = None
        central_system, self._central_system = self._central_system, None
        if self._unsub_ha_stop is not None:
            self._unsub_ha_stop()
            self._unsub_ha_stop = None
        if central_system is not None:
            _LOGGER.debug("Stopping the OCPP central system")
            await central_system.async_stop()

    @callback
    def charge_point(self, charge_point_id: str) -> ChargePoint | None:
        """Return the charger if it is connected right now."""
        if self._central_system is None:
            return None
        charge_point = self._central_system.charge_points.get(charge_point_id)
        if charge_point is None or not charge_point.connected:
            return None
        return charge_point

    @callback
    def connected_ids(self) -> list[str]:
        """Return the ids of every charger connected right now."""
        if self._central_system is None:
            return []
        return [
            charge_point_id
            for charge_point_id, charge_point in self._central_system.charge_points.items()
            if charge_point.connected
        ]

    @callback
    def add_listener(
        self, charge_point_id: str, listener: EventCallback
    ) -> CALLBACK_TYPE:
        """Call ``listener`` with every event from one charger."""
        listeners = self._listeners.setdefault(charge_point_id, [])
        listeners.append(listener)

        @callback
        def remove() -> None:
            listeners.remove(listener)
            if not listeners:
                del self._listeners[charge_point_id]

        return remove

    async def async_wait_connected(self, charge_point_id: str, timeout: float) -> bool:
        """Wait for a charger to connect, returning False if it does not in time."""
        if self.charge_point(charge_point_id) is not None:
            return True
        connected = asyncio.Event()

        @callback
        def on_event(event: ChargePointEvent) -> None:
            if isinstance(event, ConnectedEvent):
                connected.set()

        remove = self.add_listener(charge_point_id, on_event)
        self._expected[charge_point_id] += 1
        _LOGGER.debug(
            "Waiting up to %ss for charger %s to connect",
            timeout,
            mask(charge_point_id),
        )
        try:
            async with asyncio.timeout(timeout):
                await connected.wait()
        except TimeoutError:
            _LOGGER.debug("Charger %s did not connect in time", mask(charge_point_id))
            return False
        finally:
            remove()
            self._expected[charge_point_id] -= 1
            if not self._expected[charge_point_id]:
                del self._expected[charge_point_id]
        return True

    @callback
    def _handle_event(self, event: ChargePointEvent) -> None:
        charge_point_id = event.charge_point_id
        self._log_event(event)
        for listener in list(self._listeners.get(charge_point_id, ())):
            listener(event)
        if not isinstance(event, ConnectedEvent):
            return
        for entry in self._ocpp_entries(charge_point_id):
            if entry.state is ConfigEntryState.SETUP_RETRY:
                _LOGGER.debug(
                    "Charger %s connected, setting up its entry",
                    mask(charge_point_id),
                )
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
        if charge_point_id not in self._expected and not self._is_configured(
            charge_point_id
        ):
            _LOGGER.debug(
                "Charger %s belongs to no entry, offering it for setup",
                mask(charge_point_id),
            )
            discovery_flow.async_create_flow(
                self.hass,
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_CHARGE_POINT_ID: charge_point_id},
            )

    @staticmethod
    def _log_event(event: ChargePointEvent) -> None:
        """Log the events that matter for following a charger's connection."""
        charger = mask(event.charge_point_id)
        if isinstance(event, ConnectedEvent):
            _LOGGER.debug("Charger %s connected over OCPP", charger)
        elif isinstance(event, DisconnectedEvent):
            _LOGGER.debug("Charger %s disconnected from OCPP", charger)
        elif isinstance(event, BootEvent):
            # Vendor, model and firmware only: the rest identifies the unit.
            _LOGGER.debug(
                "Charger %s booted: %s %s, firmware %s",
                charger,
                event.info.vendor,
                event.info.model,
                event.info.firmware_version,
            )
        else:
            _LOGGER.debug("Charger %s sent %s", charger, type(event).__name__)

    @callback
    def _ocpp_entries(self, charge_point_id: str | None = None) -> list[ConfigEntry]:
        """Return the entries reaching their charger over OCPP.

        Only the one charger's entries when ``charge_point_id`` is given.
        """
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_TRANSPORT) == TRANSPORT_OCPP
            and (
                charge_point_id is None
                or entry.data.get(CONF_CHARGE_POINT_ID) == charge_point_id
            )
        ]

    @callback
    def _is_configured(self, charge_point_id: str) -> bool:
        return any(
            is_same_charger(entry.data, charge_point_id)
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )
