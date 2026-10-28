"""Diagnostics support for the PetGravity integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import PetGravityConfigEntry
from .const import CONF_GATEWAY_MAC, CONF_TOKEN, CONF_WATER_DEVICE_MAC

TO_REDACT = [
    CONF_TOKEN,
    "phone",
    "mqtt_username",
    "mqtt_password",
    "code",
    CONF_GATEWAY_MAC,
    CONF_WATER_DEVICE_MAC,
    "deviceMac",
    "gatewayMac",
    "rfid",
    "petId",
    "screenId",
    "screen_id",
]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: PetGravityConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinator = entry.runtime_data.coordinator
    mqtt = entry.runtime_data.mqtt
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT)
        if coordinator.data is not None
        else None,
        "mqtt": {
            "connected": mqtt.connected,
            "fresh_state": mqtt.fresh(),
            "fresh_warnings": mqtt.fresh(warning=True),
            "data": async_redact_data(asdict(mqtt.data), TO_REDACT),
        }
        if mqtt is not None
        else None,
    }
