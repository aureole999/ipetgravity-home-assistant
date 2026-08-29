"""Diagnostics support for the PetGravity integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import PetGravityConfigEntry
from .const import CONF_TOKEN

TO_REDACT = [CONF_TOKEN]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: PetGravityConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinator = entry.runtime_data.coordinator
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "data": asdict(coordinator.data) if coordinator.data is not None else None,
    }
