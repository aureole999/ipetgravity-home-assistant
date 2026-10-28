"""Explicit dispensing, pour-only and safe state refresh buttons."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .mqtt_entity import PetGravityMqttEntity


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.mqtt:
        async_add_entities(
            [
                PetGravityButton(entry, "refresh_device"),
                PetGravityButton(entry, "dispense_once"),
                PetGravityButton(entry, "pour_only"),
            ]
        )


class PetGravityButton(PetGravityMqttEntity, ButtonEntity):
    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        if key == "refresh_device":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif key == "pour_only":
            self._attr_icon = "mdi:cup-off"

    @property
    def available(self):
        if self.key == "pour_only":
            return (
                self.coordinator.pour_only_supported
                and self.coordinator.self_clean_active is not True
            )
        return (
            self.coordinator.connected
            if self.key == "refresh_device"
            else super().available
        )

    async def async_press(self):
        if self.key == "refresh_device":
            self.coordinator.async_refresh_device()
        elif self.key == "pour_only":
            await self.coordinator.async_command(102, {"type": 5})
        else:
            await self.coordinator.async_command(102)
