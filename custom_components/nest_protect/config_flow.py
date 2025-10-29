"""Config flow for Nest Protect (legacy-compatible)."""

from __future__ import annotations
import uuid
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN as NEST_PROTECT_DOMAIN, LOGGER
from .oauth import NestOAuth2Implementation
from .pynest.client import NestClient
from .pynest.exceptions import BadCredentialsException, PynestException


class ConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=NEST_PROTECT_DOMAIN):
    """Config flow for the (legacy) Nest Protect integration."""

    VERSION = 7
    DOMAIN = NEST_PROTECT_DOMAIN

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._implementation_domain: str | None = None
        self.flow_impl = None

    @property
    def logger(self):
        """Return logger for this flow (required)."""
        from .const import LOGGER
        return LOGGER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for client credentials (legacy path)."""

        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = user_input.get("client_id", "").strip()
            client_secret = user_input.get("client_secret", "").strip()

            if not client_id:
                errors["client_id"] = "required"
            if not client_secret:
                errors["client_secret"] = "required"

            if not errors:
                self._client_id = client_id
                self._client_secret = client_secret
                # register oauth2 implementation for the legacy path
                self._implementation_domain = f"{self.DOMAIN}_{uuid.uuid4().hex}"
                impl = NestOAuth2Implementation(
                    self.hass,
                    self._implementation_domain,
                    self._client_id,
                    self._client_secret,
                )
                config_entry_oauth2_flow.async_register_implementation(
                    self.hass, self.DOMAIN, impl
                )
                self.flow_impl = impl
                return await self.async_step_auth()

        # das ist nur für die UI-Beschreibung im ersten Schritt,
        # damit {redirect_uri_example} ersetzt werden kann.
        # Wir versuchen, der UI ein sinnvolles Beispiel zu geben.
        # Wenn du Nabu Casa nutzt, nimm die externe URL aus HA-Einstellungen.
        # Falls du keine hast, basteln wir eine "https://<dein-nabu>.ui.nabu.casa/auth/external/callback"
        try:
            # wenn du 'external_url' aus den HA-Einstellungen holen willst:
            external_url = self.hass.config.external_url
            if external_url:
                example_redirect = f"{external_url.rstrip('/')}/auth/external/callback"
            else:
                example_redirect = "https://<deine-nabu-url>.ui.nabu.casa/auth/external/callback"
        except Exception:
            example_redirect = "https://<deine-nabu-url>.ui.nabu.casa/auth/external/callback"

        schema = vol.Schema(
            {
                vol.Required("client_id", default=""): str,
                vol.Required("client_secret", default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "redirect_uri_example": example_redirect,
            },
        )


    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Start the OAuth2 flow provided by Home Assistant helpers."""
        try:
            return await super().async_step_auth(user_input)
        except config_entry_oauth2_flow.OAuthError as err:
            self.logger.exception("OAuth error during legacy step: %s", err)
            raise

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """
        Called after the Home Assistant OAuth2 flow finishes.

        We try to use the returned Google access token to fetch a Nest JWT
        via the pynest client. If that fails with missing credentials we
        create a restricted config entry (so the integration stays installable).
        """
        session = async_create_clientsession(self.hass)
        client = NestClient(session=session)
        try:
            nest = await client.authenticate(data["token"]["access_token"])
            # optional: fetch initial data (devices)
            try:
                first = await client.get_first_data(nest.access_token, nest.userid)
            except Exception:
                first = None
        except BadCredentialsException:
            return self.async_abort(reason="invalid_auth")
        except PynestException as err:
            # Create a restricted entry instead of aborting - keeps UX nicer
            LOGGER.warning("Nest authenticate failed: %s", err)
            entry_data = {
                "client_id": self._client_id or "",
                "client_secret": self._client_secret or "",
                "auth_implementation": self.flow_impl.domain if self.flow_impl else None,
                "token": data.get("token"),
                "restricted": True,
                "restricted_reason": str(err),
            }
            return self.async_create_entry(title="Nest Protect (restricted)", data=entry_data)
        except Exception as err:
            LOGGER.exception("Unexpected error completing OAuth: %s", err)
            return self.async_abort(reason="unknown")

        email = getattr(nest, "email", None) or getattr(nest, "userid", "unknown")
        await self.async_set_unique_id(getattr(nest, "user", uuid.uuid4().hex))
        entry_data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "auth_implementation": self.flow_impl.domain if self.flow_impl else None,
            "token": data["token"],
            "restricted": False,
        }
        return self.async_create_entry(title=f"Nest Protect ({email})", data=entry_data)
