"""The PetGravity integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import PetGravityClient
from .const import CONF_MQTT_ENABLED, CONF_MQTT_PASSWORD, CONF_MQTT_USERNAME, CONF_TOKEN
from .coordinator import PetGravityDataUpdateCoordinator
from .mqtt import PetGravityMqttHub
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SELECT,
]


@dataclass
class PetGravityRuntimeData:
    """Runtime data stored on the config entry."""

    client: PetGravityClient
    coordinator: PetGravityDataUpdateCoordinator
    mqtt: PetGravityMqttHub | None = None


type PetGravityConfigEntry = ConfigEntry[PetGravityRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Expose read-only actions even when an entry is temporarily unloaded."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PetGravityConfigEntry) -> bool:
    """Set up PetGravity from a config entry."""

    client = PetGravityClient(async_get_clientsession(hass), entry.data[CONF_TOKEN])
    coordinator = PetGravityDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hub = (
        PetGravityMqttHub(hass, entry)
        if entry.options.get(CONF_MQTT_ENABLED, True)
        and entry.options.get(CONF_MQTT_USERNAME)
        and entry.options.get(CONF_MQTT_PASSWORD)
        else None
    )
    entry.runtime_data = PetGravityRuntimeData(
        client=client, coordinator=coordinator, mqtt=hub
    )
    try:
        if hub:
            await hub.async_start()

            async def async_stop(event):
                await hub.async_stop()

            entry.async_on_unload(
                hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop)
            )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        if hub:
            await hub.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PetGravityConfigEntry) -> bool:
    """Unload a PetGravity config entry."""

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and entry.runtime_data.mqtt:
        await entry.runtime_data.mqtt.async_stop()
    return unloaded
