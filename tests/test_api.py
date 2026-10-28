"""Check exact wire formats and keep credentials out of API errors."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientConnectionError

from custom_components.ipetgravity.api import (
    PetGravityAuthError,
    PetGravityClient,
    PetGravityConnectionError,
    PetGravityError,
    PetGravityRateLimitError,
    decode_user_id_from_token,
)

from .conftest import TOKEN


def response_session(payload=None, status=200):
    response = MagicMock(status=status)
    response.json = AsyncMock(return_value=payload)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.request.return_value = context
    return session


async def test_sms_wire_format():
    session = response_session({"code": 200})
    client = PetGravityClient(session, TOKEN)
    await client.async_send_login_code("13800000000")
    args, kwargs = session.request.call_args
    assert args == ("POST", "https://app.ipetgravity.com/user/getLoginSmsCode")
    assert kwargs["data"] == {"phone": "13800000000"}
    assert kwargs["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert "token" not in kwargs["headers"]
    assert kwargs["allow_redirects"] is False
    session = response_session({"code": 200, "data": {"token": TOKEN}})
    client = PetGravityClient(session)
    assert await client.async_login_with_sms("13800000000", "012345") == TOKEN
    assert client.token == TOKEN
    assert session.request.call_args.kwargs["data"] == {
        "phone": "13800000000",
        "code": "012345",
    }


@pytest.mark.parametrize(
    "method,params,verb,path,body_key,data",
    [
        (
            "async_get_device_statistics",
            (3,),
            "GET",
            "/device/water/todayWaterDeviceDataV2",
            "params",
            {"deviceId": "3"},
        ),
        (
            "async_get_device_events",
            ("AA", dt.date(2026, 10, 28)),
            "POST",
            "/device/getDeviceEventListV2",
            "json",
            {"mac": "AA", "time": "2026-10-28"},
        ),
        (
            "async_get_pet_targets",
            (1,),
            "POST",
            "/pet/getPetTargetInfo",
            "data",
            {"sceneId": "1"},
        ),
        (
            "async_get_daily_events",
            (1, dt.date(2026, 10, 28)),
            "GET",
            "/device/water/targetDayDrinkDataV2",
            "params",
            {"sceneId": "1", "time": "2026-10-28"},
        ),
        (
            "async_get_daily_statistics",
            (1, dt.date(2026, 10, 28)),
            "POST",
            "/device/water/drinkWaterDataStatistics",
            "json",
            {
                "sceneId": "1",
                "startTime": "2026-10-28",
                "endTime": "",
                "type": "DAY",
                "rfid": "",
            },
        ),
    ],
)
async def test_data_wire_format(method, params, verb, path, body_key, data):
    session = response_session({"code": 200, "data": []})
    client = PetGravityClient(session, TOKEN + "\r\n")
    await getattr(client, method)(*params)
    args, kwargs = session.request.call_args
    assert args == (verb, "https://app.ipetgravity.com" + path)
    assert kwargs[body_key] == data
    assert kwargs["headers"]["token"] == TOKEN
    if verb == "GET":
        assert kwargs["data"] is None and kwargs["json"] is None


@pytest.mark.parametrize(
    "payload,status,error",
    [
        ({"code": 401}, 200, PetGravityAuthError),
        ({"code": "403"}, 200, PetGravityAuthError),
        ({}, 401, PetGravityAuthError),
        ({}, 429, PetGravityRateLimitError),
        ({"code": 429}, 200, PetGravityRateLimitError),
        ({"code": 500, "msg": "SECRET"}, 200, PetGravityError),
        ([], 200, PetGravityError),
        ({}, 302, PetGravityConnectionError),
    ],
)
async def test_errors_do_not_expose_server_payload(payload, status, error, caplog):
    session = response_session(payload, status)
    with pytest.raises(error) as raised:
        await PetGravityClient(session, TOKEN).async_get_pet_targets(1)
    assert "SECRET" not in str(raised.value) + caplog.text


async def test_transport_error():
    session = MagicMock()
    session.request.side_effect = ClientConnectionError("private details")
    with pytest.raises(PetGravityConnectionError, match="API request failed"):
        await PetGravityClient(session, TOKEN).async_get_screens()


async def test_missing_login_token():
    with pytest.raises(PetGravityError, match="contain a token"):
        await PetGravityClient(
            response_session({"code": 200, "data": {}})
        ).async_login_with_sms("13800000000", "012345")


def test_jwt_shapes():
    assert decode_user_id_from_token(TOKEN) == 42
    for token in ("bad", "a.W10.b", "a.b.c", "a.@@@@.b"):
        assert decode_user_id_from_token(token) is None


@pytest.mark.parametrize(
    "scene,gateway,water",
    [
        ("991234567890123457", "991234567890123458", "991234567890123459"),
        ("SceneOpaqueId001", "GatewayOpaque002", "FountainOpaque03"),
    ],
)
async def test_v2_discovery_preserves_opaque_ids_and_does_not_call_old_api(
    scene, gateway, water
):
    session = response_session(
        {
            "code": 200,
            "data": {
                "screens": [
                    {
                        "sceneId": scene,
                        "sceneName": "Test home",
                        "devices": [
                            {
                                "deviceId": gateway,
                                "deviceType": 0,
                                "deviceMac": "AABBCCDDEE00",
                                "children": [
                                    {
                                        "deviceId": water,
                                        "deviceType": 1,
                                        "deviceMac": "AABBCCDDEE01",
                                        "deviceName": "Test fountain",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        }
    )
    screens = await PetGravityClient(session, TOKEN).async_get_screens()
    assert screens[0].screen_id == scene
    assert screens[0].gateway_device_id == gateway
    assert screens[0].water_device.device_id == water
    assert screens[0].water_device.gateway_mac == "AABBCCDDEE00"
    assert session.request.call_args.args == (
        "GET",
        "https://app.ipetgravity.com/device/getScreenV2",
    )
    session.request.assert_called_once()


async def test_history_uses_new_statistics_per_day():
    session = response_session(
        {"code": 200, "data": [{"drinkMilliliters": 14, "drinkNum": 2}]}
    )
    result = await PetGravityClient(session, TOKEN).async_get_drinking_history(
        1, dt.date(2026, 10, 27), dt.date(2026, 10, 28)
    )
    assert result["data"] == [
        {"time": "2026-10-27", "intake": 14, "bout": 2},
        {"time": "2026-10-28", "intake": 14, "bout": 2},
    ]
    assert session.request.call_count == 2
    for call, day in zip(
        session.request.call_args_list, ["2026-10-27", "2026-10-28"], strict=True
    ):
        assert call.args == (
            "POST",
            "https://app.ipetgravity.com/device/water/drinkWaterDataStatistics",
        )
        assert call.kwargs["json"]["sceneId"] == "1"
        assert call.kwargs["json"]["startTime"] == day


@pytest.mark.parametrize("data", [None, [], {}, {"screens": [None]}])
async def test_malformed_device_lists(data):
    with pytest.raises(PetGravityError, match="Unexpected PetGravity"):
        await PetGravityClient(
            response_session({"code": 200, "data": data}), TOKEN
        ).async_get_screens()
