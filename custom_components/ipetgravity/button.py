"""Explicit one-shot dispensing and safe state refresh buttons."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .mqtt_entity import PetGravityMqttEntity


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.mqtt:
        async_add_entities(
            [
                PetGravityButton(entry, "refresh_device"),
                PetGravityButton(entry, "dispense_once"),
            ]
        )


class PetGravityButton(PetGravityMqttEntity, ButtonEntity):
    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        if key == "refresh_device":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        return (
            self.coordinator.connected
            if self.key == "refresh_device"
            else super().available
        )

    async def async_press(self):
        if self.key == "refresh_device":
            self.coordinator.async_refresh_device()
        else:
            await self.coordinator.async_command(102)
