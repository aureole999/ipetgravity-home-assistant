"""Conservative, bounded edits to parameters reported by the device."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import (
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.exceptions import ServiceValidationError

from .mqtt import nested, number
from .mqtt_entity import PetGravityMqttEntity

# key, section, field, minimum, maximum, unit. No parameter is sent unless the
# firmware reported that section and field in a fresh state snapshot.
PARAMETERS = (
    ("heating_target", "autoHeating", "target", 15, 40, UnitOfTemperature.CELSIUS),
    (
        "refill_threshold",
        "autoWaterReplenish",
        "threshold",
        1,
        300,
        UnitOfVolume.MILLILITERS,
    ),
    ("refill_volume", "autoWaterReplenish", "volume", 1, 200, UnitOfVolume.MILLILITERS),
    (
        "refill_cooldown",
        "autoWaterReplenish",
        "coldMinutes",
        1,
        120,
        UnitOfTime.MINUTES,
    ),
    (
        "sensing_threshold",
        "sensingWater",
        "maxThreshold",
        1,
        300,
        UnitOfVolume.MILLILITERS,
    ),
    ("sensing_volume", "sensingWater", "volume", 1, 200, UnitOfVolume.MILLILITERS),
    ("sensing_cooldown", "sensingWater", "coldMinutes", 1, 120, UnitOfTime.MINUTES),
    ("remote_volume", "remoteDischarge", "volume", 1, 200, UnitOfVolume.MILLILITERS),
    (
        "timer_interval",
        "timedWaterDischarge",
        "interval.interval",
        1,
        1440,
        UnitOfTime.MINUTES,
    ),
    (
        "timer_volume",
        "timedWaterDischarge",
        "interval.volume",
        1,
        200,
        UnitOfVolume.MILLILITERS,
    ),
    (
        "saving_interval",
        "timedWaterDischarge",
        "water_saving.time",
        1,
        1440,
        UnitOfTime.MINUTES,
    ),
    (
        "saving_volume",
        "timedWaterDischarge",
        "water_saving.volume",
        1,
        200,
        UnitOfVolume.MILLILITERS,
    ),
    ("external_refill_time", "exPump", "replTime", 1, 300, UnitOfTime.SECONDS),
    ("external_drain_time", "exPump", "drainageTime", 1, 300, UnitOfTime.SECONDS),
)


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.mqtt:
        async_add_entities(
            PetGravityNumber(entry, parameter) for parameter in PARAMETERS
        )


class PetGravityNumber(PetGravityMqttEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, entry, parameter):
        key, self.section, self.field, minimum, maximum, unit = parameter
        super().__init__(entry, f"config_{key}")
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_unit_of_measurement = unit

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        return number(
            nested(self.coordinator.data.setting, self.section, *self.field.split("."))
        )

    async def async_set_native_value(self, value):
        if (
            number(value) is None
            or not self.native_min_value <= value <= self.native_max_value
            or value != int(value)
        ):
            raise ServiceValidationError("Value is outside the supported integer range")
        await self.coordinator.async_set_setting(self.section, self.field, int(value))
