"""The PetGravity integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PetGravityClient
from .const import CONF_TOKEN
from .coordinator import PetGravityDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


@dataclass
class PetGravityRuntimeData:
    """Runtime data stored on the config entry."""

    client: PetGravityClient
    coordinator: PetGravityDataUpdateCoordinator


type PetGravityConfigEntry = ConfigEntry[PetGravityRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PetGravityConfigEntry) -> bool:
    """Set up PetGravity from a config entry."""

    client = PetGravityClient(async_get_clientsession(hass), entry.data[CONF_TOKEN])
    coordinator = PetGravityDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = PetGravityRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PetGravityConfigEntry) -> bool:
    """Unload a PetGravity config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
