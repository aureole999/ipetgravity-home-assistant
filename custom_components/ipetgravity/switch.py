"""Setting switches, applied only through correlated device acknowledgments."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .mqtt import nested
from .mqtt_entity import PetGravityMqttEntity

SECTIONS = ("autoHeating", "autoWaterReplenish", "sensingWater", "beep", "childLock")


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.mqtt:
        async_add_entities(PetGravitySwitch(entry, section) for section in SECTIONS)


class PetGravitySwitch(PetGravityMqttEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, section):
        super().__init__(entry, f"setting_{section}")
        self.section = section

    @property
    def available(self):
        return super().available and isinstance(
            nested(self.coordinator.data.setting, self.section, "enable"), bool
        )

    @property
    def is_on(self):
        return nested(self.coordinator.data.setting, self.section, "enable")

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_setting(self.section, "enable", True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_setting(self.section, "enable", False)
