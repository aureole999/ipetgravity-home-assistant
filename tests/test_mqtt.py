"""MQTT snapshots, lifecycle and acknowledgment tests without network access."""

import asyncio
import json
import time
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ipetgravity.mqtt import PetGravityMqttHub, number

from .conftest import ENTRY_DATA


@pytest.fixture
def live_entry():
    return MockConfigEntry(
        domain="ipetgravity",
        unique_id="42:1",
        data={**ENTRY_DATA, "water_device_id": 3},
        options={
            "mqtt_enabled": True,
            "mqtt_username": "example-user",
            "mqtt_password": "example-pass",
        },
        title="Test fountain",
    )


@pytest.fixture
def hub(hass, live_entry):
    hub = PetGravityMqttHub(hass, live_entry)
    hub.connected = True
    hub._client = MagicMock()
    hub._client.publish.return_value.rc = 0
    return hub


def packet(hub, command=101, data=None, **updates):
    p = {
        "commandId": command,
        "gatewayMac": hub.gateway,
        "deviceMac": hub.water,
        "timestamp": int(time.time() * 1000),
        "code": 200,
        "requestId": "",
        "data": data
        if data is not None
        else {
            "running": {
                "weight": {"current": 81},
                "waterBasinIsDetected": True,
                "batterPowerPercent": 78,
                "heating": {"ntcTemperature": 21},
                "waterTemperature": 99,
                "selfClean": {"status": 0, "times": 0},
                "inDrinkingWater": False,
            },
            "setting": {
                "autoHeating": {"enable": False, "target": 15},
                "childLock": {"enable": False},
                "timedWaterDischarge": {
                    "mode": 1,
                    "interval": {"interval": 240, "volume": 100},
                    "timed": [],
                    "water_saving": {"time": 0, "volume": 80},
                },
            },
        },
    }
    p.update(updates)
    return p


def accept(hub, p):
    hub.async_handle_message(hub.topics[0], p)


def test_bowl_compatibility_hysteresis_and_removal(hub):
    accept(hub, packet(hub))
    assert hub.bowl_volume() == 81 and hub.bowl_low is False
    p = packet(hub)
    for value, expected in [
        (49, True),
        (51, True),
        (69, True),
        (70, False),
        (60, False),
        (0, True),
    ]:
        p["data"]["running"]["weight"]["current"] = value
        accept(hub, p)
        assert hub.bowl_low is expected
    p["data"]["running"]["waterVolume"] = 42
    accept(hub, p)
    assert hub.bowl_volume() == 0
    p["data"]["running"]["waterBasinIsDetected"] = False
    accept(hub, p)
    assert hub.bowl_low is None


def test_warning_states_and_empty_all_clear(hub):
    accept(
        hub,
        packet(hub, 110, {"cleanWaterLow": -1, "wasteTankFull": -1, "lowBattery": 1}),
    )
    assert hub.warning("cleanWaterLow") is True
    assert hub.warning("wasteTankFull") is True
    assert hub.warning("lowBattery") is True
    accept(hub, packet(hub, 110, {}))
    assert hub.warning("cleanWaterLow") is False


@pytest.mark.parametrize(
    "updates",
    [
        {"gatewayMac": "DEADBEEF0000"},
        {"deviceMac": "DEADBEEF0001"},
        {"timestamp": None},
        {"timestamp": float("nan")},
        {"timestamp": int((time.time() + 7200) * 1000)},
        {"timestamp": int((time.time() - 3600) * 1000)},
    ],
)
def test_invalid_or_stale_messages(hub, updates):
    hub.async_handle_message(hub.topics[0], packet(hub, **updates), retained=True)
    assert hub.data.state_time is None and hub.bowl_low is None


def test_out_of_order_and_offline(hub):
    p = packet(hub, timestamp=int((time.time() - 1) * 1000))
    accept(hub, p)
    old = deepcopy(p)
    old["timestamp"] -= 1000
    old["data"]["running"]["weight"]["current"] = 0
    accept(hub, old)
    assert hub.bowl_volume() == 81
    hub.async_handle_message(
        hub.topics[1], packet(hub, 1, [{"mac": hub.water, "online": False}])
    )
    assert not hub.fresh()
    hub._connection_changed(False)
    assert hub.bowl_low is None


async def test_command_preserves_settings_and_matches_ack(hub):
    accept(hub, packet(hub))
    task = asyncio.create_task(hub.async_set_setting("autoHeating", "enable", True))
    await asyncio.sleep(0)
    sent = json.loads(hub._client.publish.call_args.args[1])
    assert sent["data"] == {"autoHeating": {"enable": True, "target": 15}}
    assert sent["commandId"] == 103
    assert hub._client.publish.call_args.kwargs["retain"] is False
    ack = packet(hub, 103, {}, requestId=sent["requestId"])
    hub.async_handle_message(hub.topics[0], ack, retained=True)
    assert not task.done()
    accept(hub, {**ack, "commandId": 102})
    assert not task.done()
    accept(hub, ack)
    await task
    assert hub.data.setting["autoHeating"]["enable"] is False
    writes = [json.loads(c.args[1]) for c in hub._client.publish.call_args_list]
    assert sum(p["commandId"] == 103 for p in writes) == 1


async def test_timeout_never_repeats_physical_action(hub):
    accept(hub, packet(hub))
    with patch("custom_components.ipetgravity.mqtt.COMMAND_TIMEOUT", 0.001):
        with pytest.raises(HomeAssistantError, match="acknowledgment"):
            await hub.async_command(102)
    assert hub._client.publish.call_count == 1 and not hub._pending


async def test_rejected_command_and_offline(hub):
    with pytest.raises(HomeAssistantError, match="Fresh"):
        await hub.async_command(102)
    accept(hub, packet(hub))
    task = asyncio.create_task(hub.async_command(102))
    await asyncio.sleep(0)
    sent = json.loads(hub._client.publish.call_args.args[1])
    accept(hub, packet(hub, 102, {}, code=500, requestId=sent["requestId"]))
    with pytest.raises(HomeAssistantError, match="rejected"):
        await task


async def test_nested_setting_preserves_other_modes(hub):
    accept(hub, packet(hub))
    with patch.object(hub, "async_command", new_callable=AsyncMock) as send:
        await hub.async_set_setting("timedWaterDischarge", "interval.volume", 90)
        data = send.call_args.args[1]["timedWaterDischarge"]
        assert data["interval"] == {"interval": 240, "volume": 90}
        assert data["water_saving"] == {"time": 0, "volume": 80} and data["mode"] == 1


async def test_real_ha_entities_and_options(hass, live_entry, client, caplog):
    async def fake_start(hub):
        hub.connected = True
        hub._client = MagicMock()
        hub._client.publish.return_value.rc = 0

    live_entry.add_to_hass(hass)
    with patch.object(PetGravityMqttHub, "async_start", fake_start):
        assert await hass.config_entries.async_setup(live_entry.entry_id)
    await hass.async_block_till_done()
    hub = live_entry.runtime_data.mqtt
    accept(hub, packet(hub))
    accept(hub, packet(hub, 110, {}))
    await hass.async_block_till_done()

    def state(domain, key):
        entity_id = er.async_get(hass).async_get_entity_id(
            domain, "ipetgravity", f"1_aabbccddee01_{key}"
        )
        return hass.states.get(entity_id)

    assert state("sensor", "bowl_volume").state == "81"
    assert state("sensor", "bowl_volume").attributes["unit_of_measurement"] == "mL"
    assert state("sensor", "bowl_volume").attributes["device_class"] == "volume_storage"
    assert state("sensor", "bowl_volume").attributes["state_class"] == "measurement"
    assert not any(
        record.name == "homeassistant.components.sensor"
        and "which is impossible considering device class" in record.getMessage()
        for record in caplog.records
    )
    assert state("sensor", "water_temperature").state == "21"
    assert state("sensor", "self_clean_times").state == "0"
    assert state("binary_sensor", "self_clean_active").state == "off"
    assert state("binary_sensor", "drinking_active").state == "off"
    assert state("binary_sensor", "cleanWaterLow").state == "off"
    assert state("binary_sensor", "bowl_low").state == "off"
    assert state("number", "config_heating_target").state == "15"
    assert state("switch", "setting_autoHeating").state == "off"
    assert state("select", "timer_mode").state == "interval"
    result = await hass.config_entries.options.async_init(live_entry.entry_id)
    assert result["step_id"] == "init"
    with patch.object(hub, "async_command", new_callable=AsyncMock) as send:
        await hass.services.async_call(
            "ipetgravity",
            "set_dispensing_schedule",
            {
                "config_entry_id": live_entry.entry_id,
                "schedule": [
                    {"time": "20:00", "volume": 80},
                    {"time": "08:00", "volume": 60},
                ],
            },
            blocking=True,
        )
        sent = send.call_args.args[1]["timedWaterDischarge"]
        assert sent["mode"] == 2
        assert sent["timed"] == [
            {"time": "08:00", "volume": 60},
            {"time": "20:00", "volume": 80},
        ]
        assert sent["interval"] == {"interval": 240, "volume": 100}
    with patch.object(hub, "async_set_setting", new_callable=AsyncMock) as send:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": state("switch", "setting_childLock").entity_id},
            blocking=True,
        )
        send.assert_awaited_once_with("childLock", "enable", True)
        send.reset_mock()
        await hass.services.async_call(
            "number",
            "set_value",
            {
                "entity_id": state("number", "config_heating_target").entity_id,
                "value": 25,
            },
            blocking=True,
        )
        send.assert_awaited_once_with("autoHeating", "target", 25)
        send.reset_mock()
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": state("select", "timer_mode").entity_id, "option": "timed"},
            blocking=True,
        )
        send.assert_awaited_once_with("timedWaterDischarge", "mode", 2)
    assert await hass.config_entries.async_unload(live_entry.entry_id)
    assert hub._closed


async def test_lifecycle_scoped_topics_unique_client(hub):
    with patch("custom_components.ipetgravity.mqtt.mqtt.Client") as factory:
        factory.return_value.publish.return_value.rc = 0
        await hub.async_start()
        factory.return_value.username_pw_set.assert_called_once_with(
            "example-user", "example-pass"
        )
        hub._on_connect(factory.return_value, None, None, 0, None)
        await asyncio.sleep(0)
        topics = [c.args[0] for c in factory.return_value.subscribe.call_args_list]
        assert topics == list(hub.topics)
        assert all("#" not in s and "+" not in s for s in topics)
        assert factory.call_args.kwargs["client_id"].startswith("ha-petgravity-")
        await hub.async_stop()
        assert hub._closed


def test_invalid_numeric_values():
    for n in [True, float("nan"), float("inf"), 10**1000, "81", None]:
        assert number(n) is None
    assert number(0) == 0


def test_legacy_volume_is_not_used(hub):
    p = packet(hub)
    p["data"]["running"] = {"waterVolume": 40}
    accept(hub, p)
    assert hub.bowl_volume() is None
    assert hub.bowl_low is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (-1, True),
        (1, True),
        (0, False),
        (2, False),
        (None, False),
        (True, None),
        ("1", None),
    ],
)
def test_new_app_warning_semantics(hub, value, expected):
    accept(hub, packet(hub, 110, {"cleanWaterLow": value}))
    assert hub.warning("cleanWaterLow") is expected


@pytest.mark.parametrize("value", [None, -1, True, "81", float("nan")])
def test_invalid_new_volume_never_uses_legacy_value(hub, value):
    p = packet(hub)
    p["data"]["running"]["weight"]["current"] = value
    p["data"]["running"]["waterVolume"] = 42
    accept(hub, p)
    assert hub.bowl_volume() is None and hub.bowl_low is None


@pytest.mark.parametrize("command", [102, 103])
async def test_self_clean_blocks_controls_without_publishing(hub, command):
    p = packet(hub)
    p["data"]["running"]["selfClean"]["status"] = 1
    accept(hub, p)
    assert hub.self_clean_active is True
    with pytest.raises(HomeAssistantError, match="self-cleaning"):
        await hub.async_command(command)
    hub._client.publish.assert_not_called()


def test_missing_self_clean_status_is_unknown(hub):
    p = packet(hub)
    p["data"]["running"].pop("selfClean")
    accept(hub, p)
    assert hub.self_clean_active is None


async def test_ack_disconnect_and_shutdown_cleanup(hub):
    accept(hub, packet(hub))
    task = asyncio.create_task(hub.async_command(102))
    await asyncio.sleep(0)
    await hub.async_stop()
    with pytest.raises(HomeAssistantError, match="disconnected"):
        await task
    assert not hub._pending
    assert hub._closed
    # Late worker callbacks cannot resurrect a stopped session.
    hub._connection_changed(True)
    accept(hub, packet(hub))
    assert not hub.connected


async def test_failed_platform_setup_stops_mqtt(hass, live_entry, client):
    async def fake_start(hub):
        hub.connected = True
        hub._client = MagicMock()

    live_entry.add_to_hass(hass)
    with (
        patch.object(PetGravityMqttHub, "async_start", fake_start),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=RuntimeError("test platform failure"),
        ),
    ):
        assert not await hass.config_entries.async_setup(live_entry.entry_id)
    assert live_entry.runtime_data.mqtt._closed


async def test_mqtt_credentials_required_in_options(hass, live_entry, client):
    live_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(live_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "mqtt_enabled": True,
            "mqtt_username": "",
            "mqtt_password": "",
            "low_water_threshold": 50,
            "low_water_hysteresis": 20,
        },
    )
    assert result["errors"] == {"base": "mqtt_credentials_required"}


async def test_missing_mqtt_credentials_keep_http_working(hass, client):
    entry = MockConfigEntry(
        domain="ipetgravity",
        unique_id="42:1",
        data=ENTRY_DATA,
        options={"mqtt_enabled": True},
    )
    entry.add_to_hass(hass)
    with patch.object(
        PetGravityMqttHub, "async_start", new_callable=AsyncMock
    ) as start:
        assert await hass.config_entries.async_setup(entry.entry_id)
        start.assert_not_called()
    assert entry.runtime_data.mqtt is None
