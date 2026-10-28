"""Synthetic fixtures only: no real token, phone or device identifier."""

import base64
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ipetgravity.api import (
    PetGravityClient,
    PetGravityScreen,
    PetGravityWaterDevice,
)

TOKEN = (
    "header."
    + base64.urlsafe_b64encode(b'{"userId":42}').decode().rstrip("=")
    + ".test"
)
NEW_TOKEN = TOKEN + "new"
SCREEN = PetGravityScreen(
    1,
    "Test home",
    2,
    "AABBCCDDEE00",
    PetGravityWaterDevice(3, "AABBCCDDEE01", "Test fountain", "AABBCCDDEE00"),
)
ENTRY_DATA = {
    "token": TOKEN,
    "screen_id": 1,
    "screen_name": "Test home",
    "gateway_mac": "AABBCCDDEE00",
    "water_device_mac": "AABBCCDDEE01",
    "water_device_name": "Test fountain",
}


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow loading this integration through HA's real config flow manager."""


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain="ipetgravity",
        unique_id="42:1",
        data=ENTRY_DATA,
        title="Test fountain",
        options={"mqtt_enabled": False},
    )


@pytest.fixture
def client():
    """Replace only API calls; run HA's integration and flow code unchanged."""
    client = MagicMock()
    results = {
        "async_get_screens": [SCREEN],
        "async_send_login_code": None,
        "async_login_with_sms": NEW_TOKEN,
        "async_get_daily_statistics": {
            "code": 200,
            "data": [{"drinkMilliliters": 14, "drinkNum": 2, "data": []}],
        },
        "async_get_daily_events": {
            "code": 200,
            "data": [{"intake": 10, "duration": 30, "time": "2026-10-28 10:00:00"}],
        },
        "async_get_device_statistics": {
            "code": 200,
            "data": {"pumpVolumeTotal": 416, "pumpTimeTotal": 4, "replVolumeTotal": 0},
        },
        "async_get_device_events": {
            "code": 200,
            "data": [{"eventStr": "倾倒出水105ml", "time": "2026-10-28 14:05:21"}],
        },
        "async_get_drinking_history": {
            "code": 200,
            "data": [{"intake": 14, "bout": 2, "time": "2026-10-28"}],
        },
        "async_get_pet_targets": {"code": 200, "data": []},
    }
    with ExitStack() as stack:
        for name, result in results.items():
            method = AsyncMock(return_value=result)
            setattr(client, name, method)
            stack.enter_context(patch.object(PetGravityClient, name, method))
        yield client


@pytest.fixture
def no_setup():
    with patch("custom_components.ipetgravity.async_setup_entry", return_value=True):
        yield
