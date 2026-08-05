"""Constants for the Spin EV Charger integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "spinev"

MANUFACTURER: Final = "Exicom"
MODEL: Final = "Spin"

CONF_CONNECTION_MODE: Final = "connection_mode"
CONF_SERIAL: Final = "serial"
CONF_CHARGING_INTERVAL: Final = "charging_interval"
CONF_IDLE_INTERVAL: Final = "idle_interval"

MODE_PERSISTENT: Final = "persistent"
MODE_PER_POLL: Final = "per_poll"

CONNECTION_MODES: Final = [MODE_PER_POLL, MODE_PERSISTENT]

DEFAULT_CONNECTION_MODE: Final = MODE_PER_POLL

#: Poll interval while a vehicle is charging, in seconds.
DEFAULT_CHARGING_INTERVAL: Final = 60
#: Poll interval while idle, in seconds. Kept long so a per-poll connection
#: leaves the phone app long stretches of uncontested access.
DEFAULT_IDLE_INTERVAL: Final = 300

MIN_POLL_INTERVAL: Final = 30
MAX_POLL_INTERVAL: Final = 3600

#: Interval for the very first poll, before the charger's state is known.
INITIAL_INTERVAL: Final = timedelta(seconds=DEFAULT_CHARGING_INTERVAL)

#: How long to leave the charger alone after a commit. The charger restarts
#: about eleven seconds after one and drops the Bluetooth link, so a read
#: sooner than this only produces a failure that resolves itself.
REBOOT_SETTLE: Final = timedelta(seconds=45)

ATTR_ALARMS: Final = "alarms"
