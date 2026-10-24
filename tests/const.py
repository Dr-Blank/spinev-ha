"""Shared constants for the Spin EV Charger tests."""

from spinev_ble import ChargerState, ChargerStatus, LoadBalancingConfig, OcppConfig

from homeassistant.const import CONF_ADDRESS

from custom_components.spinev.const import (
    CONF_CHARGE_POINT_ID,
    CONF_CONNECTION_MODE,
    CONF_SERIAL,
    CONF_TRANSPORT,
    DEFAULT_CONNECTION_MODE,
    TRANSPORT_BLE,
    TRANSPORT_OCPP,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
SERIAL = "123456789012"
ADVERTISED_NAME = f" {SERIAL}_EEFF"

#: Charge point id the charger uses by default, which ends with its serial.
CHARGE_POINT_ID = f"XY2{SERIAL}"
#: Address Home Assistant detects as its own.
HA_HOST = "192.0.2.10"

ENTRY_DATA = {CONF_ADDRESS: ADDRESS, CONF_SERIAL: SERIAL, CONF_TRANSPORT: TRANSPORT_BLE}
#: A charger set up before OCPP support, not yet migrated.
PRE_OCPP_ENTRY_DATA = {CONF_ADDRESS: ADDRESS, CONF_SERIAL: SERIAL}
#: A charger set up over Bluetooth, then moved to OCPP.
OCPP_ENTRY_DATA = {
    CONF_ADDRESS: ADDRESS,
    CONF_SERIAL: SERIAL,
    CONF_TRANSPORT: TRANSPORT_OCPP,
    CONF_CHARGE_POINT_ID: CHARGE_POINT_ID,
}
#: A charger set up over OCPP alone.
OCPP_ONLY_ENTRY_DATA = {
    CONF_SERIAL: CHARGE_POINT_ID,
    CONF_TRANSPORT: TRANSPORT_OCPP,
    CONF_CHARGE_POINT_ID: CHARGE_POINT_ID,
}

#: Where the charger connects before it is moved to Home Assistant.
CLOUD_OCPP_CONFIG = OcppConfig(
    host="dns:ocpp.example.com", port=443, path="ocpp", charge_point_id=CHARGE_POINT_ID
)
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
