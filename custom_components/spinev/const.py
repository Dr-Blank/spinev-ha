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
