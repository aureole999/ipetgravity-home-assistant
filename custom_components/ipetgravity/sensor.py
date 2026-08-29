"""Sensor platform for the PetGravity integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
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
    CONF_GATEWAY_MAC,
    CONF_SCREEN_ID,
    CONF_SCREEN_NAME,
    CONF_WATER_DEVICE_MAC,
    CONF_WATER_DEVICE_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL_WATER_FOUNTAIN,
)
from .coordinator import PetGravityDailyData, PetGravityDataUpdateCoordinator

UNIT_MILLILITERS = "mL"


@dataclass(frozen=True, kw_only=True)
class PetGravitySensorEntityDescription(SensorEntityDescription):
    """Describes a PetGravity sensor."""

    value_fn: Callable[[PetGravityDailyData], int | dt.datetime | None]


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


class PetGravitySensor(CoordinatorEntity[PetGravityDataUpdateCoordinator], SensorEntity):
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
    def native_value(self) -> int | dt.datetime | None:
        """Return the native sensor value."""

        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


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

    event = data.latest_event
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
