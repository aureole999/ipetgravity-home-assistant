"""Test both login paths, errors and existing-entry identity protection."""

import base64
from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ipetgravity.api import (
    PetGravityAuthError,
    PetGravityConnectionError,
)

from .conftest import ENTRY_DATA, NEW_TOKEN, TOKEN

pytestmark = pytest.mark.usefixtures("no_setup")


async def start(hass, method):
    result = await hass.config_entries.flow.async_init(
        "ipetgravity", context={"source": "user"}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": method}
    )


async def test_token_login(hass, client):
    result = await start(hass, "token")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": f" {TOKEN}\r\n"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["token"] == TOKEN
    assert result["data"]["water_device_id"] == 3
    assert result["result"].unique_id == "42:1"
    client.async_send_login_code.assert_not_called()


async def test_sms_login_saves_only_token(hass, client):
    result = await start(hass, "phone")
    client.async_send_login_code.assert_not_called()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "+86 138-0000-0000"}
    )
    assert result["step_id"] == "sms_code"
    client.async_send_login_code.assert_awaited_once_with("13800000000")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "012345"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["token"] == NEW_TOKEN
    assert "phone" not in result["data"] and "code" not in result["data"]
    client.async_login_with_sms.assert_awaited_once_with("13800000000", "012345")


async def test_invalid_phone_and_cooldown(hass, client):
    result = await start(hass, "phone")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "123"}
    )
    assert result["errors"] == {"phone": "invalid_phone"}
    client.async_send_login_code.assert_not_called()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "13800000000"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"resend_code": True}
    )
    assert result["errors"] == {"base": "sms_cooldown"}
    client.async_send_login_code.assert_awaited_once()
    with patch("custom_components.ipetgravity.config_flow.SMS_COOLDOWN", 0):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"resend_code": True}
        )
    assert not result["errors"]
    assert client.async_send_login_code.await_count == 2


async def test_bad_code_then_retry(hass, client):
    result = await start(hass, "phone")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "13800000000"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "12"}
    )
    assert result["errors"] == {"code": "invalid_code"}
    client.async_login_with_sms.assert_not_called()
    client.async_login_with_sms.side_effect = PetGravityAuthError()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"}
    )
    assert result["errors"] == {"base": "invalid_code"}
    client.async_login_with_sms.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "012345"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    client.async_send_login_code.assert_awaited_once()


async def test_discovery_retry_does_not_reuse_sms(hass, client):
    result = await start(hass, "phone")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "13800000000"}
    )
    client.async_get_screens.side_effect = PetGravityConnectionError()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "012345"}
    )
    assert result["step_id"] == "login_complete"
    assert result["errors"] == {"base": "cannot_connect"}
    client.async_get_screens.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    client.async_login_with_sms.assert_awaited_once()


@pytest.mark.parametrize("source", [SOURCE_REAUTH, SOURCE_RECONFIGURE])
async def test_replace_token_preserves_entry(hass, entry, client, source):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "ipetgravity",
        context={"source": source, "entry_id": entry.entry_id},
        data=ENTRY_DATA if source == SOURCE_REAUTH else None,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "token"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": NEW_TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == (
        "reauth_successful" if source == SOURCE_REAUTH else "reconfigure_successful"
    )
    assert entry.data["token"] == NEW_TOKEN
    assert entry.unique_id == "42:1"


async def test_wrong_account_cannot_replace_entry(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "ipetgravity",
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "token"}
    )
    client.async_get_screens.return_value = []
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": NEW_TOKEN}
    )
    assert result["errors"]["base"] == "no_water_fountain"
    assert entry.data["token"] == TOKEN


@pytest.mark.parametrize("token", ["bad", "a.W10.b", "a.@@@@.b", "a.b.c"])
async def test_malformed_token(hass, client, token):
    result = await start(hass, "token")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": token}
    )
    assert result["errors"] == {"base": "invalid_token"}
    client.async_get_screens.assert_not_called()


async def test_duplicate(hass, entry, client):
    entry.add_to_hass(hass)
    result = await start(hass, "token")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": TOKEN}
    )
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("source", [SOURCE_REAUTH, SOURCE_RECONFIGURE])
async def test_v2_relogin_preserves_original_entity_ids(hass, entry, client, source):
    from .conftest import SCREEN

    entry.add_to_hass(hass)
    client.async_get_screens.return_value = [
        replace(SCREEN, screen_id="SceneOpaqueId001")
    ]
    result = await hass.config_entries.flow.async_init(
        "ipetgravity",
        context={"source": source, "entry_id": entry.entry_id},
        data=ENTRY_DATA if source == SOURCE_REAUTH else None,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "token"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": NEW_TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["screen_id"] == 1 and entry.unique_id == "42:1"
    assert entry.data["scene_id"] == "SceneOpaqueId001"


async def test_v2_discovery_does_not_duplicate_old_entry(hass, entry, client):
    from .conftest import SCREEN

    entry.add_to_hass(hass)
    client.async_get_screens.return_value = [
        replace(SCREEN, screen_id="SceneOpaqueId001")
    ]
    result = await start(hass, "token")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": TOKEN}
    )
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("source", [SOURCE_REAUTH, SOURCE_RECONFIGURE])
async def test_sms_reauthentication(hass, entry, client, source):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "ipetgravity",
        context={"source": source, "entry_id": entry.entry_id},
        data=ENTRY_DATA if source == SOURCE_REAUTH else None,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "phone"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "13800000000"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "012345"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["token"] == NEW_TOKEN
    assert entry.unique_id == "42:1"
    assert "phone" not in entry.data and "code" not in entry.data


async def test_different_user_rejected_even_with_same_home(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "ipetgravity",
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "token"}
    )
    token = (
        "header."
        + base64.urlsafe_b64encode(b'{"userId":43}').decode().rstrip("=")
        + ".test"
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": token}
    )
    assert result["reason"] == "wrong_account"
    assert entry.data["token"] == TOKEN


async def test_sms_network_failure_does_not_retry_automatically(hass, client):
    result = await start(hass, "phone")
    client.async_send_login_code.side_effect = PetGravityConnectionError()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "13800000000"}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "13800000000"}
    )
    assert result["errors"] == {"base": "sms_cooldown"}
    client.async_send_login_code.assert_awaited_once()
