"""Config flow for Nest Protect (OAuth2 + restricted fallback)."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries

from .const import DOMAIN, LOGGER
from .oauth import NestOAuthClient
from .pynest.client import NestClient
from .pynest.exceptions import PynestException


class NestProtectFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Nest Protect."""

    VERSION = 1

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._client_secret: str | None = None
        # Wir nutzen https://www.google.com als Redirect-URI, weil du sie schon so in der Google Cloud Console eingetragen hast
        self._redirect_uri: str = "https://www.google.com"

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: ask for OAuth client credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._client_id = user_input["client_id"].strip()
            self._client_secret = user_input["client_secret"].strip()
            return await self.async_step_auth()

        data_schema = vol.Schema(
            {
                vol.Required("client_id"): str,
                vol.Required("client_secret"): str,
            }
        )

        # wir setzen redirect_uri_example, damit HA nicht mehr im Frontend meckert
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "redirect_uri_example": f"{self._redirect_uri}",
            },
        )

    async def async_step_auth(self, user_input: dict[str, Any] | None = None):
        """Step 2: ask for the auth code (from the browser URL) and exchange it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            auth_code = user_input["auth_code"].strip()

            # baue HTTP-Session
            session = self.hass.helpers.aiohttp_client.async_get_clientsession()

            # OAuth-Client (holt access_token / refresh_token)
            oauth = NestOAuthClient(
                session=session,
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=self._redirect_uri,
            )

            try:
                tokens = await oauth.exchange_code(auth_code)

                # Test-Authentifizierung beim NestClient
                client = NestClient(session)
                await client.authenticate(tokens["access_token"])

                # Entry anlegen. Wir speichern, was wir später in __init__.py brauchen.
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
                LOGGER.error("Nest authenticate failed during flow: %s", err)
                errors["base"] = "auth_failed"
            except Exception as err:  # irgendwas komplett Unerwartetes
                LOGGER.exception("Unexpected error during Nest Protect flow: %s", err)
                errors["base"] = "unknown"

        data_schema = vol.Schema(
            {
                vol.Required("auth_code"): str,
            }
        )

        return self.async_show_form(
            step_id="auth",
            data_schema=data_schema,
            errors=errors,
        )


async def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    """Return an options flow handler."""
    return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for Nest Protect (currently empty)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_create_entry(title="", data={})
