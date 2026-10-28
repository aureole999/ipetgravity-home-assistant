"""Water alerts, installation and live connectivity states."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .mqtt import WARNING_KEYS, nested
from .mqtt_entity import PetGravityMqttEntity


async def async_setup_entry(hass, entry, async_add_entities):
    if not entry.runtime_data.mqtt:
        return
    async_add_entities(
        [
            PetGravityBinarySensor(entry, "mqtt_connected"),
            PetGravityBinarySensor(entry, "device_online"),
            PetGravityBinarySensor(entry, "bowl_low"),
            PetGravityBinarySensor(entry, "bowl_present"),
            PetGravityBinarySensor(entry, "heating_active"),
            PetGravityBinarySensor(entry, "self_clean_active"),
            PetGravityBinarySensor(entry, "drinking_active"),
            *(PetGravityBinarySensor(entry, key) for key in WARNING_KEYS),
        ]
    )


class PetGravityBinarySensor(PetGravityMqttEntity, BinarySensorEntity):
    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        if key in ("mqtt_connected", "device_online"):
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif key in WARNING_KEYS or key == "bowl_low":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif key == "heating_active":
            self._attr_device_class = BinarySensorDeviceClass.HEAT

    @property
    def available(self):
        if self.key == "mqtt_connected":
            return True
        if self.key == "device_online":
            return self.coordinator.connected
        if self.key in WARNING_KEYS:
            return self.coordinator.fresh(warning=True)
        return super().available

    @property
    def is_on(self):
        if self.key == "mqtt_connected":
            return self.coordinator.connected
        if self.key == "device_online":
            return (
                False
                if self.coordinator.device_online is False
                else True
                if self.coordinator.fresh()
                else None
            )
        if self.key == "bowl_low":
            return self.coordinator.bowl_low
        if self.key == "self_clean_active":
            return self.coordinator.self_clean_active
        if self.key == "drinking_active":
            value = self.coordinator.data.running.get("inDrinkingWater")
            return value if isinstance(value, bool) else None
        if self.key == "bowl_present":
            value = self.coordinator.data.running.get("waterBasinIsDetected")
            return value if isinstance(value, bool) else None
        if self.key == "heating_active":
            value = nested(self.coordinator.data.running, "heating", "isWorking")
            return value if isinstance(value, bool) else None
        return self.coordinator.warning(self.key)
