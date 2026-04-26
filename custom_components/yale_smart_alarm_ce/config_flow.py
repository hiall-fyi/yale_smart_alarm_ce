"""Config flow for Yale Smart Alarm CE."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YaleApiClient
from .const import (
    CONF_API_KEY,
    CONF_INSTALL_ID,
    CONF_REGION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    REGION_OPTIONS,
    YALE_API_KEYS,
)
from .error_handler import (
    YaleAuthenticationError,
    YaleConnectionError,
    YaleRateLimitError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigFlowResult



_LOGGER = logging.getLogger(__name__)


class YaleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yale Smart Alarm CE."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> YaleOptionsFlow:
        """Return the options flow handler."""
        return YaleOptionsFlow()

    def __init__(self) -> None:
        """Initialize the YaleConfigFlow."""
        self.api: YaleApiClient | None = None
        self.email: str | None = None
        self.password: str | None = None
        self.region: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    def _resolve_api_key(self) -> str:
        """Resolve the API key for the current region."""
        return YALE_API_KEYS.get(
            self.region or "global", YALE_API_KEYS["global"],
        )

    async def _attempt_authenticate(
        self, context_label: str,
    ) -> tuple[bool | None, dict[str, str]]:
        """Attempt authentication and map errors to form error keys.

        Returns *(result, errors)* where *result* is the return value of
        ``api.authenticate()`` (``True`` = fully authenticated, ``False``
        = MFA required, ``None`` = error occurred).
        """
        errors: dict[str, str] = {}
        try:
            result = await self.api.authenticate()  # type: ignore[union-attr]
        except YaleConnectionError:
            errors["base"] = "cannot_connect"
        except YaleAuthenticationError:
            errors["base"] = "invalid_auth"
        except YaleRateLimitError:
            errors["base"] = "rate_limited"
        except Exception:
            _LOGGER.exception("Unexpected error during %s", context_label)
            errors["base"] = "unknown"
        else:
            return result, errors
        return None, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.email = user_input[CONF_EMAIL]
            self.password = user_input[CONF_PASSWORD]
            self.region = user_input.get(CONF_REGION, "global")

            session = async_get_clientsession(self.hass)
            self.api = YaleApiClient(
                session, self.email, self.password, self._resolve_api_key(),
            )

            result, errors = await self._attempt_authenticate("authentication")
            if result is True:
                await self.async_set_unique_id(self.email)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Yale ({self.email})",
                    data=self._build_entry_data(),
                )
            if result is False:
                return await self.async_step_mfa()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_REGION, default="global"): vol.In(REGION_OPTIONS),
                },
            ),
            errors=errors,
        )

    def _build_entry_data(self) -> dict[str, Any]:
        """Build the config entry data dict.

        NOTE: Password is stored in config entry data because the Yale
        AA Ecosystem API does not support OAuth2 or long-lived refresh
        tokens.  Re-authentication requires the original credentials.
        """
        # Preserve install_id from existing entry during reauth, otherwise
        # generate new.  install_id is a device fingerprint sent with every
        # API request — changing it during reauth would start a new "device
        # session", potentially invalidating the current auth and triggering
        # additional MFA challenges.
        install_id: str
        if self._reauth_entry and CONF_INSTALL_ID in self._reauth_entry.data:
            install_id = self._reauth_entry.data[CONF_INSTALL_ID]
        elif self.api:
            install_id = self.api.install_id
        else:
            install_id = str(uuid.uuid4())
        return {
            CONF_EMAIL: self.email,
            CONF_PASSWORD: self.password,
            CONF_REGION: self.region,
            CONF_API_KEY: self._resolve_api_key(),
            CONF_INSTALL_ID: install_id,
        }

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle MFA verification."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if self.api is None:
                return self.async_abort(reason="unknown")

            code = user_input["code"]
            try:
                result = await self.api.authenticate(verification_code=code)
                if result:
                    # Reauth flow — update existing entry
                    if self._reauth_entry:
                        return self.async_update_reload_and_abort(
                            self._reauth_entry,
                            data=self._build_entry_data(),
                        )
                    # New entry flow
                    await self.async_set_unique_id(self.email)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Yale ({self.email})",
                        data=self._build_entry_data(),
                    )
                errors["base"] = "invalid_code"
            except YaleAuthenticationError:
                errors["base"] = "invalid_code"
            except Exception:
                _LOGGER.exception("Unexpected error during MFA validation")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema(
                {
                    vol.Required("code"): str,
                },
            ),
            errors=errors,
            description_placeholders={"email": self.email or ""},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration (password/region change)."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        self.email = reconfigure_entry.data.get(CONF_EMAIL)

        if user_input is not None:
            self.password = user_input[CONF_PASSWORD]
            self.region = user_input.get(CONF_REGION, "global")

            session = async_get_clientsession(self.hass)
            self.api = YaleApiClient(
                session, self.email or "", self.password, self._resolve_api_key(),
            )

            result, errors = await self._attempt_authenticate("reconfiguration")
            if result is True:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=self._build_entry_data(),
                )
            if result is False:
                # MFA required — store entry ref for MFA completion
                self._reauth_entry = reconfigure_entry
                return await self.async_step_mfa()

        current_region = reconfigure_entry.data.get(CONF_REGION, "global")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_REGION, default=current_region): vol.In(
                        REGION_OPTIONS,
                    ),
                },
            ),
            errors=errors,
            description_placeholders={"email": self.email or ""},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Handle re-authentication when the token has expired."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"],
        )
        if self._reauth_entry is None:
            return self.async_abort(reason="unknown")
        self.email = entry_data.get(CONF_EMAIL)
        self.region = entry_data.get(CONF_REGION, "global")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation (password re-entry)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)
            self.api = YaleApiClient(
                session, self.email or "", self.password, self._resolve_api_key(),
            )

            result, errors = await self._attempt_authenticate("re-authentication")
            if result is True:
                if self._reauth_entry:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data=self._build_entry_data(),
                    )
                return self.async_abort(reason="unknown")
            if result is False:
                return await self.async_step_mfa()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                },
            ),
            errors=errors,
            description_placeholders={"email": self.email or ""},
        )


class YaleOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Yale Smart Alarm CE."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    ),
                },
            ),
        )
