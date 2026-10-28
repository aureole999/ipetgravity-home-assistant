"""UI setup, SMS authentication and token replacement for PetGravity."""

from __future__ import annotations

import re
import time
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    PetGravityAuthError,
    PetGravityClient,
    PetGravityConnectionError,
    PetGravityError,
    PetGravityRateLimitError,
    PetGravityScreen,
    decode_user_id_from_token,
)
from .const import (
    CONF_CODE,
    CONF_GATEWAY_MAC,
    CONF_PHONE,
    CONF_RESEND_CODE,
    CONF_SCREEN_ID,
    CONF_SCREEN_NAME,
    CONF_TOKEN,
    CONF_WATER_DEVICE_ID,
    CONF_WATER_DEVICE_MAC,
    CONF_WATER_DEVICE_NAME,
    DOMAIN,
)
from .options_flow import PetGravityOptionsFlow

SMS_COOLDOWN = 60


class PetGravityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Authenticate with an existing token or an app SMS code."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PetGravityOptionsFlow()

    def __init__(self) -> None:
        """Keep phone numbers and codes out of persistent config entries."""
        self._entry: ConfigEntry | None = None
        self._token = ""
        self._screens: list[PetGravityScreen] = []
        self._phone = ""
        self._last_sms: float | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to log in; accept the previous token form payload too."""
        if user_input and CONF_TOKEN in user_input:
            return await self.async_step_token(user_input)
        return self.async_show_menu(step_id="user", menu_options=["token", "phone"])

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate an existing long-lived app token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            errors, screens = await _validate_token(self.hass, token)
            if not errors:
                return await self._async_finish_login(token, screens)
        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): _password_selector()}),
            errors=errors,
        )

    async def async_step_phone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send a single SMS after the user explicitly submits their number."""
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = re.sub(r"[\s-]", "", user_input[CONF_PHONE])
            phone = phone.removeprefix("+86")
            if not re.fullmatch(r"1[3-9][0-9]{9}", phone):
                errors[CONF_PHONE] = "invalid_phone"
            elif self._sms_cooling_down():
                errors["base"] = "sms_cooldown"
            else:
                # A lost response may still mean an SMS was sent. Never retry
                # automatically; start the cooldown before making the request.
                self._last_sms = time.monotonic()
                try:
                    await PetGravityClient(
                        async_get_clientsession(self.hass)
                    ).async_send_login_code(phone)
                except PetGravityConnectionError:
                    errors["base"] = "cannot_connect"
                except PetGravityRateLimitError:
                    errors["base"] = "sms_cooldown"
                except PetGravityError:
                    errors["base"] = "sms_failed"
                else:
                    self._phone = phone
                    return await self.async_step_sms_code()
        return self.async_show_form(
            step_id="phone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PHONE): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEL)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_sms_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange a six-digit code for the app token without storing the code."""
        if not self._phone:
            return await self.async_step_phone()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = PetGravityClient(async_get_clientsession(self.hass))
            if user_input.get(CONF_RESEND_CODE):
                if self._sms_cooling_down():
                    errors["base"] = "sms_cooldown"
                else:
                    self._last_sms = time.monotonic()
                    try:
                        await client.async_send_login_code(self._phone)
                    except PetGravityConnectionError:
                        errors["base"] = "cannot_connect"
                    except PetGravityRateLimitError:
                        errors["base"] = "sms_cooldown"
                    except PetGravityError:
                        errors["base"] = "sms_failed"
            else:
                code = user_input.get(CONF_CODE, "").strip()
                if not re.fullmatch(r"[0-9]{6}", code):
                    errors[CONF_CODE] = "invalid_code"
                else:
                    try:
                        token = await client.async_login_with_sms(self._phone, code)
                    except PetGravityConnectionError:
                        errors["base"] = "cannot_connect"
                    except PetGravityRateLimitError:
                        errors["base"] = "sms_cooldown"
                    except PetGravityAuthError:
                        errors["base"] = "invalid_code"
                    except PetGravityError:
                        errors["base"] = "login_failed"
                    else:
                        # Keep an issued token in memory if discovery fails so a
                        # transient network failure won't consume the code twice.
                        self._token = token
                        self._phone = ""
                        return await self.async_step_login_complete()
        return self.async_show_form(
            step_id="sms_code",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_CODE): _password_selector(),
                    vol.Optional(CONF_RESEND_CODE, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_login_complete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retry device discovery with the already-issued token if needed."""
        errors, screens = await _validate_token(self.hass, self._token)
        if not errors:
            return await self._async_finish_login(self._token, screens)
        if errors.get("base") in ("invalid_auth", "invalid_token"):
            return await self.async_step_token()
        return self.async_show_form(
            step_id="login_complete", data_schema=vol.Schema({}), errors=errors
        )

    async def _async_finish_login(
        self, token: str, screens: list[PetGravityScreen]
    ) -> ConfigFlowResult:
        """Complete both login methods, preserving an existing home's identity."""
        self._token = token
        self._screens = screens
        if self._entry is not None:
            screen = next(
                (s for s in screens if s.screen_id == self._entry.data[CONF_SCREEN_ID]),
                None,
            )
            if screen is None:
                return self.async_abort(reason="wrong_account")
            if (
                self._entry.unique_id
                and _unique_id(token, screen) != self._entry.unique_id
            ):
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._entry, data={**self._entry.data, **_entry_data(token, screen)}
            )
        if len(screens) == 1:
            return await self._async_create_entry_for_screen(screens[0])
        return await self.async_step_screen()

    async def async_step_screen(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a home when the account has several water fountains."""
        errors: dict[str, str] = {}
        if user_input is not None:
            screen = next(
                (
                    s
                    for s in self._screens
                    if str(s.screen_id) == str(user_input[CONF_SCREEN_ID])
                ),
                None,
            )
            if screen is not None:
                return await self._async_create_entry_for_screen(screen)
            errors["base"] = "screen_not_found"
        return self.async_show_form(
            step_id="screen",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCREEN_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(s.screen_id),
                                    label=f"{s.name} ({s.screen_id})",
                                )
                                for s in self._screens
                            ]
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Offer both methods when the saved token is rejected."""
        self._entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to replace the credentials for the existing home."""
        return self.async_show_menu(
            step_id="reauth_confirm", menu_options=["token", "phone"]
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace credentials; keep the home and entity identities stable."""
        self._entry = self._get_reconfigure_entry()
        return self.async_show_menu(
            step_id="reconfigure", menu_options=["token", "phone"]
        )

    def _sms_cooling_down(self) -> bool:
        return (
            self._last_sms is not None
            and time.monotonic() - self._last_sms < SMS_COOLDOWN
        )

    async def _async_create_entry_for_screen(
        self, screen: PetGravityScreen
    ) -> ConfigFlowResult:
        """Keep the existing account/home unique-ID format for upgrades."""
        await self.async_set_unique_id(_unique_id(self._token, screen))
        self._abort_if_unique_id_configured()
        title = screen.water_device.name if screen.water_device else screen.name
        return self.async_create_entry(
            title=title, data=_entry_data(self._token, screen)
        )


def _password_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


async def _validate_token(
    hass: HomeAssistant, token: str
) -> tuple[dict[str, str], list[PetGravityScreen]]:
    """Validate through the cloud rather than trusting unsigned JWT data."""
    if not token or token.count(".") != 2 or decode_user_id_from_token(token) is None:
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
    screens = [screen for screen in screens if screen.water_device is not None]
    if not screens:
        return {"base": "no_water_fountain"}, []
    return {}, screens


def _entry_data(token: str, screen: PetGravityScreen) -> dict[str, Any]:
    """Store the token and device identifiers, never phone numbers or codes."""
    water_device = screen.water_device
    assert water_device is not None
    return {
        CONF_TOKEN: token,
        CONF_SCREEN_ID: screen.screen_id,
        CONF_SCREEN_NAME: screen.name,
        CONF_GATEWAY_MAC: water_device.gateway_mac,
        CONF_WATER_DEVICE_ID: water_device.device_id,
        CONF_WATER_DEVICE_MAC: water_device.mac,
        CONF_WATER_DEVICE_NAME: water_device.name,
    }


def _unique_id(token: str, screen: PetGravityScreen) -> str:
    user_id = decode_user_id_from_token(token)
    account = str(user_id) if user_id is not None else "unknown"
    return f"{account}:{screen.screen_id}"
