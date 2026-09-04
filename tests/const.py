"""Shared constants for the Spin EV Charger tests."""

from spinev_ble import ChargerState, ChargerStatus, LoadBalancingConfig

from homeassistant.const import CONF_ADDRESS

from custom_components.spinev.const import (
    CONF_CONNECTION_MODE,
    CONF_SERIAL,
    DEFAULT_CONNECTION_MODE,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
SERIAL = "123456789012"
ADVERTISED_NAME = f" {SERIAL}_EEFF"

ENTRY_DATA = {CONF_ADDRESS: ADDRESS, CONF_SERIAL: SERIAL}
ENTRY_OPTIONS = {CONF_CONNECTION_MODE: DEFAULT_CONNECTION_MODE}

STATUS = ChargerStatus(
    state=ChargerState.CHARGING,
    state_value=4,
    power_w=7360.0,
    voltage_v=230.0,
    current_a=32.0,
    current_limit_a=32.0,
    session_energy_kwh=12.5,
    session_seconds=3600,
    lifetime_energy_kwh=1234.5,
    lifetime_seconds=360000,
    firmware_version="35.24.4.32",
    alarms=(),
)

IDLE_STATUS = ChargerStatus(
    state=ChargerState.IDLE,
    state_value=2,
    power_w=0.0,
    voltage_v=230.0,
    current_a=0.0,
    current_limit_a=32.0,
    session_energy_kwh=0.0,
    session_seconds=0,
    lifetime_energy_kwh=1234.5,
    lifetime_seconds=360000,
    firmware_version="35.24.4.32",
    alarms=(),
)

LOAD_BALANCING = LoadBalancingConfig(
    enabled=True,
    grid_current_limit_a=63.0,
    safe_current_offset_a=5.0,
    reduce_current_offset_a=2.0,
    max_grid_power_w=14000.0,
    source=1,
    priority=0,
)

RANDOM_DELAY = 0
