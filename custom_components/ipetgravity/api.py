"""PetGravity cloud API client."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import MANUFACTURER

BASE_URL = "https://app.ipetgravity.com"
REQUEST_TIMEOUT = 20


class PetGravityError(Exception):
    """Base error for PetGravity API failures."""


class PetGravityAuthError(PetGravityError):
    """Raised when the PetGravity token is invalid or expired."""


class PetGravityConnectionError(PetGravityError):
    """Raised when the PetGravity API cannot be reached."""


class PetGravityRateLimitError(PetGravityError):
    """Raised when the server asks the caller to slow down."""


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
    except ValueError:
        return None

    if not isinstance(decoded, dict):
        return None
    user_id = decoded.get("userId")
    return user_id if type(user_id) is int else None


class PetGravityClient:
    """Small async client for the captured PetGravity cloud API."""

    def __init__(self, session: ClientSession, token: str = "") -> None:
        """Initialize the client."""

        self._session = session
        self._token = token.strip()

    @property
    def token(self) -> str:
        """Return the token used by this client."""

        return self._token

    async def async_send_login_code(self, phone: str) -> None:
        """Send one SMS, only after the user submits the phone form."""
        await self._async_request(
            "/user/getLoginSmsCode",
            data={"phone": phone},
            content_type="application/x-www-form-urlencoded",
            authenticated=False,
        )

    async def async_login_with_sms(self, phone: str, code: str) -> str:
        """Exchange a phone number and SMS code for the regular app token."""
        response = await self._async_request(
            "/user/loginWithSms",
            data={"phone": phone, "code": code},
            content_type="application/x-www-form-urlencoded",
            authenticated=False,
        )
        user = response.get("data")
        token = _as_str(user.get("token")) if isinstance(user, dict) else None
        if not token:
            raise PetGravityError("Login response did not contain a token")
        self._token = token
        return token

    async def async_get_screens(self) -> list[PetGravityScreen]:
        """Return configured PetGravity screens and their water devices."""

        response = await self._async_request(
            "/device/getScreen",
            data={},
            content_type="application/x-www-form-urlencoded",
        )
        screens: list[PetGravityScreen] = []

        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("screens"), list):
            raise PetGravityError("Unexpected PetGravity device list")
        for screen in data["screens"]:
            if not isinstance(screen, dict):
                raise PetGravityError("Unexpected PetGravity home data")
            gateway_device_id: int | None = None
            gateway_mac: str | None = None
            water_device: PetGravityWaterDevice | None = None

            for device in screen.get("devices", []):
                if not isinstance(device, dict):
                    raise PetGravityError("Unexpected PetGravity device data")
                if device.get("deviceType") == 1:
                    gateway_device_id = _as_int(device.get("deviceId"))
                    gateway_mac = _as_str(device.get("deviceMac"))

                for child in device.get("children", []):
                    if not isinstance(child, dict):
                        raise PetGravityError("Unexpected PetGravity child device data")
                    if child.get("deviceType") == 2:
                        child_mac = _as_str(child.get("deviceMac"))
                        child_id = _as_int(child.get("deviceId"))
                        child_name = (
                            _as_str(child.get("deviceName"))
                            or "PetGravity Water Fountain"
                        )
                        child_gateway_mac = (
                            _as_str(child.get("fatherMac")) or gateway_mac
                        )
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

    async def async_get_device_statistics(self, device_id: int) -> dict[str, Any]:
        """Return today's per-device drinking, pump and refill totals."""
        return await self._async_request(
            "/device/water/todayWaterDeviceData",
            data={"deviceId": device_id},
            content_type="application/x-www-form-urlencoded",
        )

    async def async_get_device_events(
        self, mac: str, target_date: dt.date
    ) -> dict[str, Any]:
        """Return device operations for one day, separate from drinking events."""
        return await self._async_request(
            "/device/getDeviceEventList",
            data={"mac": mac, "time": target_date.isoformat()},
            content_type="application/x-www-form-urlencoded",
        )

    async def async_get_drinking_history(
        self, screen_id: int, start_date: dt.date, end_date: dt.date
    ) -> dict[str, Any]:
        """Return daily summaries over a date range (app type 1)."""
        return await self._async_request(
            "/device/water/targetTimeDrinkData",
            data={
                "targetScreenId": screen_id,
                "startTime": start_date.isoformat(),
                "endTime": end_date.isoformat(),
                "type": 1,
            },
            content_type="application/x-www-form-urlencoded",
        )

    async def async_get_pet_targets(self, screen_id: int) -> dict[str, Any]:
        """Return the home's pets and their drinking targets."""
        return await self._async_request(
            "/pet/getPetTargetInfo",
            data={"screenId": screen_id},
            content_type="application/x-www-form-urlencoded",
        )

    async def _async_request(
        self,
        path: str,
        *,
        content_type: str,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Call the PetGravity API and return decoded JSON."""

        headers = {
            "User-Agent": "Dart/3.9 (dart:io)",
            "buildnumber": "1",
            "os": "ios",
            "content-type": content_type,
            "device-model": "iPhone18,1",
            "language": "zh",
            "os-version": "26.6",
            "app-package": "com.petgravity.app",
            "app-version": "1.1.2",
        }
        if authenticated:
            headers["token"] = self._token

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    f"{BASE_URL}{path}",
                    headers=headers,
                    data=data,
                    json=json_data,
                    allow_redirects=False,
                ) as response:
                    if response.status == 429:
                        raise PetGravityRateLimitError(
                            "PetGravity request rate exceeded"
                        )
                    if response.status in (401, 403):
                        raise PetGravityAuthError("PetGravity token was rejected")
                    if 300 <= response.status < 400:
                        raise PetGravityConnectionError("Unexpected API redirect")
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except PetGravityAuthError:
            raise
        except (
            TimeoutError,
            ClientResponseError,
            ClientError,
            json.JSONDecodeError,
        ) as err:
            raise PetGravityConnectionError("PetGravity API request failed") from err

        if not isinstance(payload, dict):
            raise PetGravityError("Unexpected PetGravity response format")
        code = payload.get("code")
        if code in (200, "200"):
            return payload

        if code in (401, 403, "401", "403"):
            raise PetGravityAuthError("PetGravity authentication was rejected")
        if code in (429, "429"):
            raise PetGravityRateLimitError("PetGravity request rate exceeded")

        # Server messages may echo a phone number, SMS code or token.
        raise PetGravityError("PetGravity rejected the request")


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
