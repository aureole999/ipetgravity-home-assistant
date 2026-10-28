"""On-demand, read-only PetGravity actions with response data."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import PetGravityAuthError, PetGravityError
from .const import CONF_SCREEN_ID, CONF_WATER_DEVICE_MAC, DOMAIN


def async_setup_services(hass: HomeAssistant) -> None:
    """Register actions once; unloaded entries receive a clear error."""

    async def async_handle(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise ServiceValidationError("Select a loaded PetGravity integration entry")
        client = entry.runtime_data.client
        screen_id = entry.data[CONF_SCREEN_ID]
        try:
            if call.service == "get_drinking_history":
                start = call.data["start_date"]
                end = call.data["end_date"]
                if not 0 <= (end - start).days <= 30:
                    raise ServiceValidationError("Choose a date range of 1 to 31 days")
                response = await client.async_get_drinking_history(
                    screen_id, start, end
                )
            elif call.service == "get_device_events":
                response = await client.async_get_device_events(
                    entry.data[CONF_WATER_DEVICE_MAC], call.data["date"]
                )
            else:
                response = await client.async_get_pet_targets(screen_id)
        except PetGravityAuthError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError("PetGravity login expired; sign in again") from err
        except PetGravityError as err:
            raise HomeAssistantError("Could not retrieve PetGravity data") from err
        return {"data": response.get("data")}

    for name, fields in (
        (
            "get_drinking_history",
            {vol.Required("start_date"): cv.date, vol.Required("end_date"): cv.date},
        ),
        ("get_device_events", {vol.Required("date"): cv.date}),
        ("get_pet_targets", {}),
    ):
        if hass.services.has_service(DOMAIN, name):
            continue
        hass.services.async_register(
            DOMAIN,
            name,
            async_handle,
            schema=vol.Schema({vol.Required("config_entry_id"): cv.string, **fields}),
            supports_response=SupportsResponse.ONLY,
        )
