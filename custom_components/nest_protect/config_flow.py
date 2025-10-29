"""Config flow for Nest Protect (OAuth2 + restricted fallback)."""

from __future__ import annotations
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .const import DOMAIN
from .pynest.oauth import NestOAuthClient
from .client import NestClient
from .exceptions import PynestException

_LOGGER = logging.getLogger(__name__)


class NestProtectFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nest Protect."""

    VERSION = 1

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._redirect_uri: str = "https://www.google.com"
        self._access_token: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """First step: ask for client credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._client_id = user_input["client_id"].strip()
            self._client_secret = user_input["client_secret"].strip()
            self._redirect_uri = "https://www.google.com"
            return await self.async_step_auth()

        data_schema = vol.Schema(
            {
                vol.Required("client_id"): str,
                vol.Required("client_secret"): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_auth(self, user_input: dict[str, Any] | None = None):
        """Second step: ask for auth code and exchange for tokens."""
        errors: dict[str, str] = {}

        if user_input is not None:
            auth_code = user_input["auth_code"].strip()
            session = self.hass.helpers.aiohttp_client.async_get_clientsession()
            oauth = NestOAuthClient(
                session, self._client_id, self._client_secret, self._redirect_uri
            )

            try:
                tokens = await oauth.exchange_code(auth_code)
                client = NestClient(session)
                await client.authenticate(tokens["access_token"])
                return self.async_create_entry(
                    title="Nest Protect",
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "redirect_uri": self._redirect_uri,
                        "access_token": tokens.get("access_token"),
                        "refresh_token": tokens.get("refresh_token"),
                    },
                )
            except PynestException as err:
                _LOGGER.error("Nest authenticate failed: %s", err)
                errors["base"] = "auth_failed"

        data_schema = vol.Schema({vol.Required("auth_code"): str})

        return self.async_show_form(
            step_id="auth",
            data_schema=data_schema,
            errors=errors,
        )


async def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    """Return the options flow handler."""
    return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Initial step."""
        return self.async_create_entry(title="", data={})
