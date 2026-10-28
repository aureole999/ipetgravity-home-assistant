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
    session.post.return_value = context
    return session


async def test_sms_wire_format():
    session = response_session({"code": 200})
    client = PetGravityClient(session, TOKEN)
    await client.async_send_login_code("13800000000")
    args, kwargs = session.post.call_args
    assert args[0].endswith("/user/getLoginSmsCode")
    assert kwargs["data"] == {"phone": "13800000000"}
    assert kwargs["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert "token" not in kwargs["headers"]
    assert kwargs["allow_redirects"] is False
    session = response_session({"code": 200, "data": {"token": TOKEN}})
    client = PetGravityClient(session)
    assert await client.async_login_with_sms("13800000000", "012345") == TOKEN
    assert client.token == TOKEN
    assert session.post.call_args.kwargs["data"] == {
        "phone": "13800000000",
        "code": "012345",
    }


@pytest.mark.parametrize(
    "method,params,path,data",
    [
        (
            "async_get_device_statistics",
            (3,),
            "/device/water/todayWaterDeviceData",
            {"deviceId": 3},
        ),
        (
            "async_get_device_events",
            ("AA", dt.date(2026, 10, 28)),
            "/device/getDeviceEventList",
            {"mac": "AA", "time": "2026-10-28"},
        ),
        ("async_get_pet_targets", (1,), "/pet/getPetTargetInfo", {"screenId": 1}),
        (
            "async_get_drinking_history",
            (1, dt.date(2026, 10, 22), dt.date(2026, 10, 28)),
            "/device/water/targetTimeDrinkData",
            {
                "targetScreenId": 1,
                "startTime": "2026-10-22",
                "endTime": "2026-10-28",
                "type": 1,
            },
        ),
    ],
)
async def test_data_wire_format(method, params, path, data):
    session = response_session({"code": 200, "data": []})
    client = PetGravityClient(session, TOKEN + "\r\n")
    await getattr(client, method)(*params)
    args, kwargs = session.post.call_args
    assert args[0] == "https://app.ipetgravity.com" + path
    assert kwargs["data"] == data
    assert kwargs["headers"]["token"] == TOKEN


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
    session.post.side_effect = ClientConnectionError("private details")
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


@pytest.mark.parametrize("data", [None, [], {}, {"screens": [None]}])
async def test_malformed_device_lists(data):
    with pytest.raises(PetGravityError, match="Unexpected PetGravity"):
        await PetGravityClient(
            response_session({"code": 200, "data": data}), TOKEN
        ).async_get_screens()
