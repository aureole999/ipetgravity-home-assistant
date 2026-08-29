"""Config flow for the PetGravity integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import (
    PetGravityAuthError,
    PetGravityClient,
    PetGravityConnectionError,
    PetGravityError,
    PetGravityScreen,
    decode_user_id_from_token,
)
from .const import (
    CONF_GATEWAY_MAC,
    CONF_SCREEN_ID,
    CONF_SCREEN_NAME,
    CONF_TOKEN,
    CONF_WATER_DEVICE_MAC,
    CONF_WATER_DEVICE_NAME,
    DOMAIN,
)


class PetGravityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a PetGravity config flow."""

    VERSION = 1

    _reauth_entry: ConfigEntry | None = None
    _token: str
    _screens: list[PetGravityScreen]

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""

        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            errors, screens = await _validate_token(self.hass, token)
            if not errors:
                self._token = token
                self._screens = screens
                if len(screens) == 1:
                    return await self._async_create_entry_for_screen(screens[0])
                return await self.async_step_screen()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_screen(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Let the user choose a screen when the account has multiple homes."""

        if user_input is not None:
            screen = next(
                screen
                for screen in self._screens
                if str(screen.screen_id) == user_input[CONF_SCREEN_ID]
            )
            return await self._async_create_entry_for_screen(screen)

        return self.async_show_form(
            step_id="screen",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCREEN_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(screen.screen_id),
                                    label=f"{screen.name} ({screen.screen_id})",
                                )
                                for screen in self._screens
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Start reauthentication when the token is rejected."""

        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask the user for a replacement token."""

        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            errors, screens = await _validate_token(self.hass, token)
            if not errors:
                entry = self._reauth_entry
                assert entry is not None
                screen_id = entry.data[CONF_SCREEN_ID]
                if not any(screen.screen_id == screen_id for screen in screens):
                    errors["base"] = "screen_not_found"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data={**entry.data, CONF_TOKEN: token},
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Allow the user to update token and selected screen from the UI."""

        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            errors, screens = await _validate_token(self.hass, token)
            if not errors:
                screen = next(
                    (
                        screen
                        for screen in screens
                        if str(screen.screen_id) == str(user_input[CONF_SCREEN_ID])
                    ),
                    None,
                )
                if screen is None:
                    errors["base"] = "screen_not_found"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data=_entry_data(token, screen),
                    )

        token = entry.data[CONF_TOKEN]
        _, screens = await _validate_token(self.hass, token)
        options = [
            selector.SelectOptionDict(value=str(screen.screen_id), label=screen.name)
            for screen in screens
        ] or [
            selector.SelectOptionDict(
                value=str(entry.data[CONF_SCREEN_ID]),
                label=str(entry.data.get(CONF_SCREEN_NAME, entry.title)),
            )
        ]

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN, default=token): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        CONF_SCREEN_ID,
                        default=str(entry.data[CONF_SCREEN_ID]),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_create_entry_for_screen(
        self,
        screen: PetGravityScreen,
    ) -> ConfigFlowResult:
        """Create a config entry for one screen."""

        unique_id = _unique_id(self._token, screen)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        title = screen.water_device.name if screen.water_device else screen.name
        return self.async_create_entry(title=title, data=_entry_data(self._token, screen))


async def _validate_token(
    hass: HomeAssistant,
    token: str,
) -> tuple[dict[str, str], list[PetGravityScreen]]:
    """Validate a PetGravity token by fetching screen data."""

    if not token or token.count(".") != 2:
        return {"base": "invalid_token"}, []

    client = PetGravityClient(async_get_clientsession(hass), token)
    try:
        screens = await client.async_get_screens()
    except PetGravityAuthError:
        return {"base": "invalid_auth"}, []
    except PetGravityConnectionError:
        return {"base": "cannot_connect"}, []
    except PetGravityError:
        return {"base": "unknown"}, []

    screens_with_water = [screen for screen in screens if screen.water_device is not None]
    if not screens_with_water:
        return {"base": "no_water_fountain"}, []

    return {}, screens_with_water


def _entry_data(token: str, screen: PetGravityScreen) -> dict[str, Any]:
    """Build stored config entry data for a screen."""

    water_device = screen.water_device
    assert water_device is not None

    return {
        CONF_TOKEN: token,
        CONF_SCREEN_ID: screen.screen_id,
        CONF_SCREEN_NAME: screen.name,
        CONF_GATEWAY_MAC: screen.gateway_mac or water_device.gateway_mac,
        CONF_WATER_DEVICE_MAC: water_device.mac,
        CONF_WATER_DEVICE_NAME: water_device.name,
    }


def _unique_id(token: str, screen: PetGravityScreen) -> str:
    """Return a stable unique id for one account/screen pair."""

    user_id = decode_user_id_from_token(token)
    account = str(user_id) if user_id is not None else "unknown"
    return f"{account}:{screen.screen_id}"
