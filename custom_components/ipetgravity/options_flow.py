"""MQTT and optional low-water state settings; delivery belongs to automations."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_LOW_WATER_HYSTERESIS,
    CONF_LOW_WATER_THRESHOLD,
    CONF_MQTT_ENABLED,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USERNAME,
    DEFAULT_LOW_WATER_HYSTERESIS,
    DEFAULT_LOW_WATER_THRESHOLD,
)


class PetGravityOptionsFlow(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input[CONF_MQTT_USERNAME] = user_input.get(
                CONF_MQTT_USERNAME, ""
            ).strip()
            if user_input.get(CONF_MQTT_ENABLED) and not (
                user_input.get(CONF_MQTT_USERNAME)
                and user_input.get(CONF_MQTT_PASSWORD)
            ):
                errors["base"] = "mqtt_credentials_required"
            else:
                return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MQTT_ENABLED, default=options.get(CONF_MQTT_ENABLED, True)
                    ): bool,
                    vol.Optional(
                        CONF_MQTT_USERNAME, default=options.get(CONF_MQTT_USERNAME, "")
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MQTT_PASSWORD, default=options.get(CONF_MQTT_PASSWORD, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required(
                        CONF_LOW_WATER_THRESHOLD,
                        default=options.get(
                            CONF_LOW_WATER_THRESHOLD, DEFAULT_LOW_WATER_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=1, max=500)),
                    vol.Required(
                        CONF_LOW_WATER_HYSTERESIS,
                        default=options.get(
                            CONF_LOW_WATER_HYSTERESIS, DEFAULT_LOW_WATER_HYSTERESIS
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                }
            ),
            errors=errors,
        )
