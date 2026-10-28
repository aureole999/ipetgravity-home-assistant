"""Change the timer mode while preserving the reported timer parameters."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .mqtt import nested
from .mqtt_entity import PetGravityMqttEntity

MODES = {1: "interval", 2: "timed", 3: "water_saving"}
PUMP_MODES = {0: "off", 1: "refill", 2: "drain", 3: "refill_and_drain"}


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.mqtt:
        async_add_entities([PetGravityTimerMode(entry), PetGravityPumpMode(entry)])


class PetGravityTimerMode(PetGravityMqttEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(MODES.values())

    def __init__(self, entry):
        super().__init__(entry, "timer_mode")

    @property
    def available(self):
        return super().available and self.current_option is not None

    @property
    def current_option(self):
        return MODES.get(
            nested(self.coordinator.data.setting, "timedWaterDischarge", "mode")
        )

    async def async_select_option(self, option):
        mode = next(k for k, v in MODES.items() if v == option)
        section = self.coordinator.data.setting.get("timedWaterDischarge", {})
        if option not in section:
            raise ValueError("This timer mode is not reported by the firmware")
        await self.coordinator.async_set_setting("timedWaterDischarge", "mode", mode)


class PetGravityPumpMode(PetGravityMqttEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(PUMP_MODES.values())

    def __init__(self, entry):
        super().__init__(entry, "external_pump_mode")

    @property
    def available(self):
        return super().available and self.current_option is not None

    @property
    def current_option(self):
        return PUMP_MODES.get(nested(self.coordinator.data.setting, "exPump", "status"))

    async def async_select_option(self, option):
        value = next(k for k, v in PUMP_MODES.items() if v == option)
        await self.coordinator.async_set_setting("exPump", "status", value)
