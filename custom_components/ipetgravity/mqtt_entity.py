"""Common identity and availability for the fountain's MQTT entities."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_SCREEN_ID,
    CONF_WATER_DEVICE_MAC,
    CONF_WATER_DEVICE_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL_WATER_FOUNTAIN,
)
from .mqtt import PetGravityMqttHub


class PetGravityMqttEntity(CoordinatorEntity[PetGravityMqttHub]):
    _attr_has_entity_name = True

    def __init__(self, entry, key):
        super().__init__(entry.runtime_data.mqtt)
        self._attr_translation_key = key
        water = entry.data[CONF_WATER_DEVICE_MAC].lower()
        self._attr_unique_id = f"{entry.data[CONF_SCREEN_ID]}_{water}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, water)},
            name=entry.data[CONF_WATER_DEVICE_NAME],
            manufacturer=MANUFACTURER,
            model=MODEL_WATER_FOUNTAIN,
        )

    @property
    def available(self):
        return self.coordinator.fresh()
