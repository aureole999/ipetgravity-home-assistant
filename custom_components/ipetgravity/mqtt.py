"""Device-scoped PetGravity MQTT telemetry and acknowledged commands."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_GATEWAY_MAC,
    CONF_LOW_WATER_HYSTERESIS,
    CONF_LOW_WATER_THRESHOLD,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USERNAME,
    CONF_WATER_DEVICE_MAC,
    CONF_WEIGHT_AS_VOLUME,
    DEFAULT_LOW_WATER_HYSTERESIS,
    DEFAULT_LOW_WATER_THRESHOLD,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)
BROKER = "47.96.40.6"
PORT = 1883
MAX_AGE = 15 * 60
COMMAND_TIMEOUT = 20
WARNING_KEYS = (
    "cleanTankNotInstalled",
    "wasteTankNotInstalled",
    "scaleTankNotInstalled",
    "scaleHeatingError",
    "scaleWeightSensorError",
    "tiltFunctionError",
    "cleanWaterLow",
    "wasteTankFull",
    "lowBattery",
)


def number(value: Any) -> int | float | None:
    """Reject booleans, NaN and infinity from device numeric fields."""
    try:
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


def nested(data: dict[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


@dataclass
class PetGravityTelemetry:
    """The two snapshots have independent vendor timestamps."""

    running: dict[str, Any] = field(default_factory=dict)
    setting: dict[str, Any] = field(default_factory=dict)
    warnings: dict[str, Any] | None = None
    state_time: float | None = None
    warning_time: float | None = None
    software_version: str | int | None = None


class PetGravityMqttHub(DataUpdateCoordinator[PetGravityTelemetry]):
    """Own one MQTT session for one previously authenticated fountain."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, LOGGER, name=f"{DOMAIN} MQTT", config_entry=entry)
        self.data = PetGravityTelemetry()
        self.entry = entry
        self.gateway = entry.data[CONF_GATEWAY_MAC]
        self.water = entry.data[CONF_WATER_DEVICE_MAC]
        if not all(
            isinstance(mac, str)
            and len(mac) == 12
            and all(c in "0123456789abcdefABCDEF" for c in mac)
            for mac in (self.gateway, self.water)
        ):
            raise ValueError("Invalid PetGravity MAC address")
        self.topics = (
            f"v1/{self.gateway}/D/{self.water}",
            f"v1/{self.gateway}/G",
            f"v1/gateway/notify/{self.gateway}",
        )
        self.connected = False
        self._client: mqtt.Client | None = None
        self._closed = False
        self._unsubscribe = None
        self._last_query = 0.0
        self._pending: dict[str, tuple[int, asyncio.Future]] = {}
        self._command_lock = asyncio.Lock()
        self._low_bowl: bool | None = None
        self.device_online: bool | None = None

    async def async_start(self) -> None:
        """Start Paho's worker without blocking Home Assistant's event loop."""
        username = self.entry.options.get(CONF_MQTT_USERNAME, "")
        password = self.entry.options.get(CONF_MQTT_PASSWORD, "")
        if not username or not password:
            raise HomeAssistantError(
                "Configure the MQTT username and password in integration options"
            )
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha-petgravity-{uuid4().hex[:16]}",
            protocol=mqtt.MQTTv5,
        )
        self._client = client
        client.username_pw_set(username, password)
        client.reconnect_delay_set(min_delay=5, max_delay=120)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(BROKER, PORT, keepalive=30)
        await self.hass.async_add_executor_job(client.loop_start)
        self._unsubscribe = async_track_time_interval(
            self.hass, self._async_tick, dt.timedelta(seconds=15)
        )

    async def _async_update_data(self) -> PetGravityTelemetry:
        """A manual HA update requests a new snapshot; replies arrive by push."""
        self.async_refresh_device()
        return self.data

    async def async_stop(self) -> None:
        """Stop the session and timers, including during an HA shutdown."""
        if self._closed:
            return
        self._closed = True
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        self.connected = False
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(HomeAssistantError("PetGravity MQTT disconnected"))
        self._pending.clear()
        if self._client:
            self._client.disconnect()
            await self.hass.async_add_executor_job(self._client.loop_stop)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if self._closed:
            return
        success = reason_code == 0
        if success:
            for topic in self.topics:
                client.subscribe(topic, qos=0)
        self.hass.loop.call_soon_threadsafe(self._connection_changed, success)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if not self._closed:
            self.hass.loop.call_soon_threadsafe(self._connection_changed, False)

    def _on_message(self, client, userdata, message) -> None:
        if (
            self._closed
            or message.topic not in self.topics
            or len(message.payload) > 131072
        ):
            return
        try:
            payload = json.loads(message.payload)
        except ValueError, UnicodeError, RecursionError:
            return
        if isinstance(payload, dict):
            self.hass.loop.call_soon_threadsafe(
                self.async_handle_message, message.topic, payload, bool(message.retain)
            )

    @callback
    def _connection_changed(self, connected: bool) -> None:
        if self._closed:
            return
        self.connected = connected
        self.async_set_updated_data(self.data)
        if connected:
            self.async_refresh_device()
        else:
            for _, future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(
                        HomeAssistantError("PetGravity MQTT disconnected")
                    )

    @callback
    def async_refresh_device(self) -> None:
        """Use the app's online query and existing-device connect/state request."""
        if not self.connected or self._client is None:
            return
        self._last_query = time.monotonic()
        try:
            self._publish(1)
            self._publish(2, device=True)
        except HomeAssistantError:
            self.connected = False
            self.async_set_updated_data(self.data)

    def _publish(
        self, command: int, *, device: bool = False, data=None, request_id=None
    ):
        if self._client is None:
            raise HomeAssistantError("PetGravity MQTT is disabled")
        payload = {
            "commandId": command,
            "gatewayMac": self.gateway,
            "requestId": request_id or uuid4().hex,
        }
        if device:
            payload["deviceMac"] = self.water
        if data is not None:
            payload["data"] = data
        result = self._client.publish(
            f"v1/{self.gateway}/S", json.dumps(payload), qos=0, retain=False
        )
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HomeAssistantError("Could not send the PetGravity command")

    @callback
    def async_handle_message(
        self, topic: str, payload: dict[str, Any], retained=False
    ) -> None:
        """Validate scope and age before accepting telemetry or acknowledgments."""
        if self._closed or topic not in self.topics:
            return
        if str(payload.get("gatewayMac", "")).lower() != self.gateway.lower():
            return
        device_mac = payload.get("deviceMac")
        if device_mac is not None and str(device_mac).lower() != self.water.lower():
            return
        stamp = number(payload.get("timestamp"))
        stamp = stamp / 1000 if stamp is not None else None
        now = time.time()
        fresh = stamp is not None and -300 <= now - stamp <= MAX_AGE
        request_id = payload.get("requestId")
        # Retained or stale packets cannot acknowledge an action from this session.
        pending_item = (
            self._pending.get(request_id) if isinstance(request_id, str) else None
        )
        pending = pending_item[1] if pending_item is not None else None
        if (
            pending is not None
            and not pending.done()
            and not retained
            and fresh
            and payload.get("commandId") == pending_item[0]
        ):
            if payload.get("code") == 200:
                pending.set_result(payload)
            elif payload.get("code") not in (0, None):
                pending.set_exception(
                    HomeAssistantError("PetGravity rejected the device command")
                )
        data = payload.get("data")
        if fresh and payload.get("commandId") == 1 and isinstance(data, list):
            for child in data:
                if (
                    isinstance(child, dict)
                    and str(child.get("mac", "")).lower() == self.water.lower()
                    and isinstance(child.get("online"), bool)
                ):
                    self.device_online = child["online"]
                    self.async_set_updated_data(self.data)
        if (
            fresh
            and topic == self.topics[2]
            and isinstance(data, dict)
            and data.get("online") is False
        ):
            self.device_online = False
            self.async_set_updated_data(self.data)
        if (
            topic != self.topics[0]
            or device_mac is None
            or not fresh
            or payload.get("code") != 200
        ):
            return
        if not isinstance(data, dict):
            return
        command = payload.get("commandId")
        if command == 101 and (
            self.data.state_time is None or stamp >= self.data.state_time
        ):
            running = data.get("running")
            if not isinstance(running, dict):
                return
            self.data.running = deepcopy(running)
            setting = data.get("setting")
            self.data.setting = deepcopy(setting) if isinstance(setting, dict) else {}
            self.data.state_time = stamp
            self.device_online = True
            self.data.software_version = data.get(
                "softVersion", data.get("softVersionCode")
            )
        elif command == 110 and (
            self.data.warning_time is None or stamp >= self.data.warning_time
        ):
            self.data.warnings = deepcopy(data)
            self.data.warning_time = stamp
        else:
            return
        self._evaluate_alerts()
        self.async_set_updated_data(self.data)

    def fresh(self, warning=False) -> bool:
        stamp = self.data.warning_time if warning else self.data.state_time
        return (
            self.connected
            and self.device_online is not False
            and stamp is not None
            and -300 <= time.time() - stamp <= MAX_AGE
        )

    def bowl_volume(self) -> int | float | None:
        if (
            not self.fresh()
            or self.data.running.get("waterBasinIsDetected") is False
            or self.warning("scaleTankNotInstalled") is True
        ):
            return None
        value = number(self.data.running.get("waterVolume"))
        if value is None and self.entry.options.get(CONF_WEIGHT_AS_VOLUME, True):
            value = number(nested(self.data.running, "weight", "current"))
        return value if value is not None and value >= 0 else None

    def warning(self, key: str) -> bool | None:
        if not self.fresh(warning=True) or self.data.warnings is None:
            return None
        # The app adds a warning when its value is -1. A full empty 110 snapshot
        # is the gateway's confirmed no-warning response (observed live).
        value = self.data.warnings.get(key)
        return (
            value == -1
            if type(value) in (int, float)
            else False
            if value is None
            else None
        )

    @property
    def bowl_low(self) -> bool | None:
        return self._low_bowl if self.fresh() else None

    @callback
    def _async_tick(self, now) -> None:
        if self._closed:
            return
        if self.connected and time.monotonic() - self._last_query >= 300:
            self.async_refresh_device()
        self._evaluate_alerts()
        self.async_set_updated_data(self.data)

    def _evaluate_alerts(self) -> None:
        volume = self.bowl_volume() if self.fresh() else None
        present = self.data.running.get("waterBasinIsDetected")
        if self.warning("scaleTankNotInstalled") is True:
            present = False
        threshold = self.entry.options.get(
            CONF_LOW_WATER_THRESHOLD, DEFAULT_LOW_WATER_THRESHOLD
        )
        hysteresis = self.entry.options.get(
            CONF_LOW_WATER_HYSTERESIS, DEFAULT_LOW_WATER_HYSTERESIS
        )
        if volume is None or present is False:
            self._low_bowl = None
        elif volume < threshold:
            self._low_bowl = True
        elif self._low_bowl is not True or volume >= threshold + hysteresis:
            self._low_bowl = False

    async def async_command(self, command: int, data=None) -> None:
        """Never retry a physical action after a lost acknowledgment."""
        if command not in (102, 103) or not self.fresh():
            raise HomeAssistantError("Fresh PetGravity device state is required")
        async with self._command_lock:
            request_id = uuid4().hex
            future = self.hass.loop.create_future()
            self._pending[request_id] = (command, future)
            try:
                self._publish(command, device=True, data=data, request_id=request_id)
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    await future
            except TimeoutError as err:
                raise HomeAssistantError(
                    "No device acknowledgment; check the app before trying again"
                ) from err
            finally:
                self._pending.pop(request_id, None)
            self.async_refresh_device()

    async def async_set_setting(self, section: str, key: str, value: Any) -> None:
        """Preserve the other fields in the selected device setting section."""
        current = self.data.setting.get(section)
        path = key.split(".")
        if not isinstance(current, dict) or nested(current, *path) is None:
            raise HomeAssistantError("This setting is not reported by this firmware")
        updated = deepcopy(current)
        target = updated
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        await self.async_command(103, {section: updated})
