"""Sensor platform for the PetGravity integration."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import PetGravityConfigEntry
from .const import (
    CONF_SCREEN_ID,
    CONF_SCREEN_NAME,
    CONF_WATER_DEVICE_MAC,
    CONF_WATER_DEVICE_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL_WATER_FOUNTAIN,
)
from .coordinator import PetGravityDailyData, PetGravityDataUpdateCoordinator
from .mqtt import nested, number
from .mqtt_entity import PetGravityMqttEntity

UNIT_MILLILITERS = "mL"


@dataclass(frozen=True, kw_only=True)
class PetGravitySensorEntityDescription(SensorEntityDescription):
    """Describes a PetGravity sensor."""

    value_fn: Callable[[PetGravityDailyData], int | float | str | dt.datetime | None]
    source: str | None = None


SENSOR_DESCRIPTIONS: tuple[PetGravitySensorEntityDescription, ...] = (
    PetGravitySensorEntityDescription(
        key="today_drink_milliliters",
        translation_key="today_drink_milliliters",
        native_unit_of_measurement=UNIT_MILLILITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.drink_milliliters,
    ),
    PetGravitySensorEntityDescription(
        key="today_drink_count",
        translation_key="today_drink_count",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.drink_num,
    ),
    PetGravitySensorEntityDescription(
        key="last_drink_milliliters",
        translation_key="last_drink_milliliters",
        native_unit_of_measurement=UNIT_MILLILITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: _latest_int(data, "intake"),
    ),
    PetGravitySensorEntityDescription(
        key="last_drink_duration",
        translation_key="last_drink_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: _latest_int(data, "duration"),
    ),
    PetGravitySensorEntityDescription(
        key="last_drink_time",
        translation_key="last_drink_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _latest_time(data),
    ),
)

# In the app UI the *TimeTotal fields are displayed with 次 (count), not seconds.
DEVICE_TOTALS = (
    ("device_drink_volume", "drinkVolumeTotal", True),
    ("device_drink_count", "drinkTimeTotal", False),
    ("pump_volume", "pumpVolumeTotal", True),
    ("pump_pour_out_volume", "pumpPourOutVolumeTotal", True),
    ("pump_count", "pumpTimeTotal", False),
    ("refill_volume", "replVolumeTotal", True),
    ("refill_count", "replTimeTotal", False),
    ("sensing_volume", "sensVolumeTotal", True),
    ("sensing_count", "sensTimeTotal", False),
)
SENSOR_DESCRIPTIONS += tuple(
    PetGravitySensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=UNIT_MILLILITERS if volume else None,
        device_class=SensorDeviceClass.VOLUME if volume else None,
        icon="mdi:water" if volume else "mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        source="device_statistics",
        value_fn=lambda data, field=field: _device_number(data, field),
    )
    for key, field, volume in DEVICE_TOTALS
)
SENSOR_DESCRIPTIONS += (
    PetGravitySensorEntityDescription(
        key="last_device_event",
        translation_key="last_device_event",
        icon="mdi:history",
        source="device_events",
        value_fn=lambda data: _device_event_text(data),
    ),
    PetGravitySensorEntityDescription(
        key="last_device_event_time",
        translation_key="last_device_event_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        source="device_events",
        value_fn=lambda data: _parse_time(data.latest_device_event),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PetGravityConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PetGravity sensors from a config entry."""

    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        PetGravitySensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )
    if entry.runtime_data.mqtt:
        async_add_entities(
            PetGravityLiveSensor(entry, *description) for description in LIVE_SENSORS
        )


LIVE_SENSORS = (
    ("bowl_volume", None, "mL", SensorDeviceClass.VOLUME),
    ("bowl_weight_raw", ("weight", "current"), None, None),
    (
        "water_temperature",
        ("heating", "ntcTemperature"),
        "°C",
        SensorDeviceClass.TEMPERATURE,
    ),
    (
        "ntc_temperature",
        ("heating", "ntcTemperature"),
        "°C",
        SensorDeviceClass.TEMPERATURE,
    ),
    (
        "ambient_temperature",
        ("heating", "envTemperature"),
        "°C",
        SensorDeviceClass.TEMPERATURE,
    ),
    ("heating_power", ("heating", "power"), "W", SensorDeviceClass.POWER),
    ("battery_level", ("batterPowerPercent",), "%", SensorDeviceClass.BATTERY),
    ("charge_status", ("batteryChargeStatus",), None, None),
    ("pump_status", ("waterPumpRunningStatus",), None, None),
    ("external_pump_status", ("exPumpStatus",), None, None),
    ("clean_tank_state", ("cleanWaterContainerState",), None, None),
    ("waste_tank_state", ("dirtyWaterContainerState",), None, None),
    ("self_clean_status", ("selfClean", "status"), None, None),
    ("self_clean_times", ("selfClean", "times"), None, None),
    ("device_last_report", None, None, SensorDeviceClass.TIMESTAMP),
)


class PetGravityLiveSensor(PetGravityMqttEntity, SensorEntity):
    def __init__(self, entry, key, path, unit, device_class):
        super().__init__(entry, key)
        self.key, self.path = key, path
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        if unit is not None or key == "bowl_weight_raw":
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def available(self):
        return (
            self.coordinator.connected
            if self.key == "device_last_report"
            else super().available
        )

    @property
    def native_value(self):
        if self.key == "bowl_volume":
            return self.coordinator.bowl_volume()
        if self.key == "device_last_report":
            stamp = self.coordinator.data.state_time
            return (
                dt.datetime.fromtimestamp(stamp, dt.UTC) if stamp is not None else None
            )
        return number(nested(self.coordinator.data.running, *self.path))


class PetGravitySensor(
    CoordinatorEntity[PetGravityDataUpdateCoordinator], SensorEntity
):
    """PetGravity sensor entity."""

    entity_description: PetGravitySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PetGravityDataUpdateCoordinator,
        entry: PetGravityConfigEntry,
        description: PetGravitySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""

        super().__init__(coordinator)
        self.entity_description = description

        screen_id = entry.data[CONF_SCREEN_ID]
        water_mac = entry.data[CONF_WATER_DEVICE_MAC].lower()
        self._attr_unique_id = f"{screen_id}_{water_mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, water_mac)},
            name=entry.data.get(CONF_WATER_DEVICE_NAME, "PetGravity Water Fountain"),
            manufacturer=MANUFACTURER,
            model=MODEL_WATER_FOUNTAIN,
        )
        self._attr_attribution = "Data provided by PetGravity cloud"
        self._attr_extra_state_attributes = {
            "screen_id": screen_id,
            "screen_name": entry.data.get(CONF_SCREEN_NAME),
        }

    @property
    def native_value(self) -> int | float | str | dt.datetime | None:
        """Return the native sensor value."""

        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Only the extra entities become unavailable if their endpoint fails."""
        if not super().available:
            return False
        source = self.entity_description.source
        return source is None or getattr(self.coordinator.data, source) is not None


def _latest_int(data: PetGravityDailyData, key: str) -> int | None:
    """Return an integer field from the latest drinking event."""

    event = data.latest_event
    if event is None:
        return None
    value: Any = event.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _latest_time(data: PetGravityDailyData) -> dt.datetime | None:
    """Return a timezone-aware datetime for the latest drinking event."""

    return _parse_time(data.latest_event)


def _parse_time(event: dict[str, Any] | None) -> dt.datetime | None:
    """Interpret the vendor's naive timestamp in the configured HA timezone."""
    if event is None:
        return None

    raw_time = event.get("time")
    if not isinstance(raw_time, str):
        return None

    parsed = dt_util.parse_datetime(raw_time)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return dt_util.as_local(parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE))
    return dt_util.as_local(parsed)


def _device_number(data: PetGravityDailyData, field: str) -> int | float | None:
    value = (data.device_statistics or {}).get(field)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _device_event_text(data: PetGravityDailyData) -> str | None:
    value = (data.latest_device_event or {}).get("eventStr")
    return value[:255] if isinstance(value, str) else None
