"""Data coordinator for the PetGravity integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import datetime as dt
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PetGravityAuthError, PetGravityClient, PetGravityError
from .const import CONF_SCAN_INTERVAL, CONF_SCREEN_ID, DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PetGravityDailyData:
    """Latest daily drinking data from PetGravity."""

    date: dt.date
    drink_milliliters: int | None
    drink_num: int | None
    hourly: list[dict[str, Any]]
    events: list[dict[str, Any]]

    @property
    def latest_event(self) -> dict[str, Any] | None:
        """Return the most recent drinking event."""

        if not self.events:
            return None
        return max(self.events, key=lambda event: event.get("time", ""))


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
        self.screen_id = int(entry.data[CONF_SCREEN_ID])

    async def _async_update_data(self) -> PetGravityDailyData:
        """Fetch latest daily drinking data."""

        target_date = dt_util.now().date()

        try:
            stats_response, events_response = await asyncio.gather(
                self.client.async_get_daily_statistics(self.screen_id, target_date),
                self.client.async_get_daily_events(self.screen_id, target_date),
            )
        except PetGravityAuthError as err:
            raise ConfigEntryAuthFailed("PetGravity token is invalid or expired") from err
        except PetGravityError as err:
            raise UpdateFailed(str(err)) from err

        stats = _first_item(stats_response.get("data"))
        events = events_response.get("data")

        return PetGravityDailyData(
            date=target_date,
            drink_milliliters=_as_int(stats.get("drinkMilliliters")),
            drink_num=_as_int(stats.get("drinkNum")),
            hourly=stats.get("data") if isinstance(stats.get("data"), list) else [],
            events=events if isinstance(events, list) else [],
        )


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
