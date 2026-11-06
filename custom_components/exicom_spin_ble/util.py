"""Helpers shared across the Spin EV Charger integration."""

from collections.abc import Mapping
import re
from typing import Any

from .const import CONF_CHARGE_POINT_ID, CONF_SERIAL

SERIAL_PATTERN = r"\d{12}"


def mask(identifier: str | None) -> str:
    """Return an identifier shortened for logs.

    Charge point ids and serials identify a charger and its owner, so logs
    carry only enough of one to tell chargers apart.
    """
    if not identifier:
        return "-"
    return f"…{identifier[-4:]}"


def is_same_charger(data: Mapping[str, Any], charge_point_id: str) -> bool:
    """Return True if the entry with ``data`` is the charger with this charge point id.

    A charger's default charge point id ends with the serial it advertises
    over Bluetooth, which ties an OCPP connection to a Bluetooth entry.
    """
    if data.get(CONF_CHARGE_POINT_ID) == charge_point_id:
        return True
    serial: str | None = data.get(CONF_SERIAL)
    if serial is None or not re.fullmatch(SERIAL_PATTERN, serial):
        return False
    return charge_point_id.endswith(serial)
