"""PetGravity cloud API client."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import datetime as dt
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import MANUFACTURER

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://app.ipetgravity.com"
REQUEST_TIMEOUT = 20


class PetGravityError(Exception):
    """Base error for PetGravity API failures."""


class PetGravityAuthError(PetGravityError):
    """Raised when the PetGravity token is invalid or expired."""


class PetGravityConnectionError(PetGravityError):
    """Raised when the PetGravity API cannot be reached."""


@dataclass(frozen=True)
class PetGravityWaterDevice:
    """A PetGravity water fountain behind a gateway."""

    device_id: int
    mac: str
    name: str
    gateway_mac: str


@dataclass(frozen=True)
class PetGravityScreen:
    """A PetGravity home/screen with devices."""

    screen_id: int
    name: str
    gateway_device_id: int | None
    gateway_mac: str | None
    water_device: PetGravityWaterDevice | None


def decode_user_id_from_token(token: str) -> int | None:
    """Decode the user id from the JWT payload without verifying the signature."""

    parts = token.split(".")
    if len(parts) < 2:
        return None

    payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None

    user_id = decoded.get("userId")
    return user_id if isinstance(user_id, int) else None


class PetGravityClient:
    """Small async client for the captured PetGravity cloud API."""

    def __init__(self, session: ClientSession, token: str) -> None:
        """Initialize the client."""

        self._session = session
        self._token = token.strip()

    @property
    def token(self) -> str:
        """Return the token used by this client."""

        return self._token

    async def async_get_screens(self) -> list[PetGravityScreen]:
        """Return configured PetGravity screens and their water devices."""

        response = await self._async_request(
            "/device/getScreen",
            data={},
            content_type="application/x-www-form-urlencoded",
        )
        screens: list[PetGravityScreen] = []

        for screen in response.get("data", {}).get("screens", []):
            gateway_device_id: int | None = None
            gateway_mac: str | None = None
            water_device: PetGravityWaterDevice | None = None

            for device in screen.get("devices", []):
                if device.get("deviceType") == 1:
                    gateway_device_id = _as_int(device.get("deviceId"))
                    gateway_mac = _as_str(device.get("deviceMac"))

                for child in device.get("children", []):
                    if child.get("deviceType") == 2:
                        child_mac = _as_str(child.get("deviceMac"))
                        child_id = _as_int(child.get("deviceId"))
                        child_name = _as_str(child.get("deviceName")) or "PetGravity Water Fountain"
                        child_gateway_mac = _as_str(child.get("fatherMac")) or gateway_mac
                        if child_mac and child_id is not None and child_gateway_mac:
                            water_device = PetGravityWaterDevice(
                                device_id=child_id,
                                mac=child_mac,
                                name=child_name,
                                gateway_mac=child_gateway_mac,
                            )

            screen_id = _as_int(screen.get("id"))
            if screen_id is None:
                continue

            screens.append(
                PetGravityScreen(
                    screen_id=screen_id,
                    name=_as_str(screen.get("name")) or MANUFACTURER,
                    gateway_device_id=gateway_device_id,
                    gateway_mac=gateway_mac,
                    water_device=water_device,
                )
            )

        return screens

    async def async_get_daily_statistics(
        self,
        screen_id: int,
        target_date: dt.date,
    ) -> dict[str, Any]:
        """Return daily chart/statistics for one screen."""

        return await self._async_request(
            "/device/water/drinkWaterDataStatistics",
            json_data={
                "endTime": "",
                "screenId": screen_id,
                "startTime": target_date.isoformat(),
                "type": "DAY",
                "rfid": "",
            },
            content_type="application/json",
        )

    async def async_get_daily_events(
        self,
        screen_id: int,
        target_date: dt.date,
    ) -> dict[str, Any]:
        """Return individual drinking events for one screen and day."""

        return await self._async_request(
            "/device/water/targetDayDrinkData",
            data={
                "time": target_date.isoformat(),
                "targetScreenId": screen_id,
            },
            content_type="application/x-www-form-urlencoded",
        )

    async def _async_request(
        self,
        path: str,
        *,
        content_type: str,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the PetGravity API and return decoded JSON."""

        headers = {
            "User-Agent": "Dart/3.9 (dart:io)",
            "buildnumber": "1",
            "os": "ios",
            "content-type": content_type,
            "device-model": "iPhone18,1",
            "token": self._token,
            "language": "zh",
            "os-version": "26.6",
            "app-package": "com.petgravity.app",
            "app-version": "1.1.2",
        }

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    f"{BASE_URL}{path}",
                    headers=headers,
                    data=data,
                    json=json_data,
                ) as response:
                    if response.status in (401, 403):
                        raise PetGravityAuthError("PetGravity token was rejected")
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except PetGravityAuthError:
            raise
        except (TimeoutError, ClientResponseError, ClientError, json.JSONDecodeError) as err:
            raise PetGravityConnectionError(f"PetGravity API request failed: {err}") from err

        code = payload.get("code")
        if code == 200:
            return payload

        if code in (401, 403):
            raise PetGravityAuthError(payload.get("msg") or "PetGravity token was rejected")

        _LOGGER.debug("Unexpected PetGravity API response for %s: %s", path, payload)
        raise PetGravityError(payload.get("msg") or f"Unexpected PetGravity API code: {code}")


def _as_int(value: Any) -> int | None:
    """Return value as int when possible."""

    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _as_str(value: Any) -> str | None:
    """Return stripped string values."""

    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
