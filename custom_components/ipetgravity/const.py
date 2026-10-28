"""Constants for the PetGravity integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "ipetgravity"

CONF_TOKEN = "token"
CONF_SCREEN_ID = "screen_id"
CONF_SCREEN_NAME = "screen_name"
CONF_GATEWAY_MAC = "gateway_mac"
CONF_WATER_DEVICE_MAC = "water_device_mac"
CONF_WATER_DEVICE_NAME = "water_device_name"
CONF_WATER_DEVICE_ID = "water_device_id"
CONF_PHONE = "phone"
CONF_CODE = "code"
CONF_RESEND_CODE = "resend_code"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 60

UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

MANUFACTURER = "PetGravity"
MODEL_GATEWAY = "Bluetooth Wi-Fi Gateway"
MODEL_WATER_FOUNTAIN = "Smart Pet Water Fountain 2S"

CONF_MQTT_ENABLED = "mqtt_enabled"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_LOW_WATER_THRESHOLD = "low_water_threshold"
CONF_LOW_WATER_HYSTERESIS = "low_water_hysteresis"
CONF_WEIGHT_AS_VOLUME = "weight_as_volume"
DEFAULT_LOW_WATER_THRESHOLD = 50
DEFAULT_LOW_WATER_HYSTERESIS = 20
