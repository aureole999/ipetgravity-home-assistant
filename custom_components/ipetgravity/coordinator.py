"""Data coordinator for the PetGravity integration."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PetGravityAuthError, PetGravityClient, PetGravityError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SCENE_ID,
    CONF_WATER_DEVICE_ID,
    CONF_WATER_DEVICE_MAC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PetGravityDailyData:
    """Latest daily drinking data from PetGravity."""

    date: dt.date
    drink_milliliters: int | None
    drink_num: int | None
    hourly: list[dict[str, Any]]
    events: list[dict[str, Any]]
    device_statistics: dict[str, Any] | None = None
    device_events: list[dict[str, Any]] | None = None

    @property
    def latest_event(self) -> dict[str, Any] | None:
        """Return the most recent drinking event."""

        if not self.events:
            return None
        return max(self.events, key=lambda event: event.get("time", ""))

    @property
    def latest_device_event(self) -> dict[str, Any] | None:
        """Return the last operation, not the last drinking session."""
        if not self.device_events:
            return None
        return max(self.device_events, key=lambda event: event.get("time", ""))


class PetGravityDataUpdateCoordinator(DataUpdateCoordinator[PetGravityDailyData]):
    """Coordinator that polls PetGravity cloud data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PetGravityClient,
    ) -> None:
        """Initialize the coordinator."""

        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=dt.timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            config_entry=entry,
        )
        self.client = client
        self.screen_id = entry.data.get(CONF_SCENE_ID)
        self.water_mac = entry.data[CONF_WATER_DEVICE_MAC]
        self.device_id: str | None = entry.data.get(CONF_WATER_DEVICE_ID)
        self._optional_failures: set[str] = set()

    async def _async_setup(self) -> None:
        """Match the V2 IDs by MAC; retain the entity identity in screen_id."""
        if self.screen_id is not None and self.device_id is not None:
            return
        try:
            screens = await self.client.async_get_screens()
        except PetGravityAuthError as err:
            raise ConfigEntryAuthFailed("PetGravity token was rejected") from err
        except PetGravityError as err:
            raise UpdateFailed(str(err)) from err
        for screen in screens:
            water = screen.water_device
            if water is not None and water.mac.lower() == self.water_mac.lower():
                self.device_id = water.device_id
                self.screen_id = screen.screen_id
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_WATER_DEVICE_ID: water.device_id,
                        CONF_SCENE_ID: screen.screen_id,
                    },
                )
                return
        raise UpdateFailed("The configured water fountain was not found")

    async def _async_update_data(self) -> PetGravityDailyData:
        """Fetch latest daily drinking data."""

        target_date = dt_util.now().date()
        assert self.device_id is not None

        try:
            results = await asyncio.gather(
                self.client.async_get_daily_statistics(self.screen_id, target_date),
                self.client.async_get_daily_events(self.screen_id, target_date),
                self.client.async_get_device_statistics(self.device_id),
                self.client.async_get_device_events(self.water_mac, target_date),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, PetGravityAuthError):
                    raise result
            for result in results[:2]:
                if isinstance(result, BaseException):
                    raise result
        except PetGravityAuthError as err:
            raise ConfigEntryAuthFailed(
                "PetGravity token is invalid or expired"
            ) from err
        except PetGravityError as err:
            raise UpdateFailed(str(err)) from err

        stats_response, events_response = results[:2]
        stats = _first_item(stats_response.get("data"))
        events = events_response.get("data")
        device_stats = self._optional_data("device statistics", results[2])
        device_events = self._optional_data("device events", results[3])

        return PetGravityDailyData(
            date=target_date,
            drink_milliliters=_as_int(stats.get("drinkMilliliters")),
            drink_num=_as_int(stats.get("drinkNum")),
            hourly=stats.get("data") if isinstance(stats.get("data"), list) else [],
            events=events if isinstance(events, list) else [],
            device_statistics=device_stats if isinstance(device_stats, dict) else None,
            device_events=device_events if isinstance(device_events, list) else None,
        )

    def _optional_data(self, name: str, response: Any) -> Any:
        """Keep original drinking entities working if an extra endpoint fails."""
        if isinstance(response, PetGravityError):
            if name not in self._optional_failures:
                LOGGER.warning(
                    "PetGravity %s is unavailable; will retry on next update", name
                )
                self._optional_failures.add(name)
            return None
        if isinstance(response, BaseException):
            raise response
        self._optional_failures.discard(name)
        return response.get("data")


def _first_item(value: Any) -> dict[str, Any]:
    """Return the first item from a list payload."""

    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _as_int(value: Any) -> int | None:
    """Return value as int when possible."""

    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None
