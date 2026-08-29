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
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 60

UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

MANUFACTURER = "PetGravity"
MODEL_GATEWAY = "Bluetooth Wi-Fi Gateway"
MODEL_WATER_FOUNTAIN = "Smart Pet Water Fountain 2S"
