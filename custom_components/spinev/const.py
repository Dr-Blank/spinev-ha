"""Constants for the Spin EV Charger integration."""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "spinev"

MANUFACTURER: Final = "Exicom"
MODEL: Final = "Spin"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONF_CONNECTION_MODE: Final = "connection_mode"
CONF_SERIAL: Final = "serial"
CONF_TRANSPORT: Final = "transport"
CONF_CHARGE_POINT_ID: Final = "charge_point_id"

#: Reach the charger over Bluetooth.
TRANSPORT_BLE: Final = "ble"
#: Reach the charger through the OCPP central system this integration runs.
TRANSPORT_OCPP: Final = "ocpp"

#: TCP port the integration's OCPP central system listens on.
OCPP_PORT: Final = 9321
#: Path the charger is pointed at when it has none of its own.
DEFAULT_OCPP_PATH: Final = "ocpp"
#: How long to wait for a repointed charger to reach the central system. It
#: restarts to apply the change and takes about twenty seconds to connect.
OCPP_CONNECT_TIMEOUT: Final = timedelta(seconds=120)
#: How long the central system keeps running after its last user lets go, so
#: a setup flow handing over to its new entry does not drop the charger.
OCPP_STOP_DELAY: Final = timedelta(seconds=60)

MODE_PERSISTENT: Final = "persistent"
MODE_PER_POLL: Final = "per_poll"

CONNECTION_MODES: Final = [MODE_PER_POLL, MODE_PERSISTENT]

DEFAULT_CONNECTION_MODE: Final = MODE_PER_POLL

#: Poll interval while a vehicle is charging, so power and alarms stay current.
CHARGING_INTERVAL: Final = timedelta(seconds=60)
#: Poll interval while idle. Kept long so a per-poll connection leaves the
#: phone app long stretches of uncontested access to the charger.
IDLE_INTERVAL: Final = timedelta(seconds=300)

#: How long to leave the charger alone after a commit. The charger restarts
#: about eleven seconds after one and drops the Bluetooth link, so a read
#: sooner than this only produces a failure that resolves itself.
REBOOT_SETTLE: Final = timedelta(seconds=45)

#: How long a number waits for the value to settle before it reaches the
#: charger. A Bluetooth write costs a connect and several seconds, and a
#: dragged slider would otherwise queue one per step.
WRITE_DEBOUNCE: Final = timedelta(seconds=3)

ATTR_ALARMS: Final = "alarms"
