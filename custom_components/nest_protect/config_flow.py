"""Adds config flow for Nest Protect."""

from __future__ import annotations

import uuid
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
import voluptuous as vol

from .const import DOMAIN as NEST_PROTECT_DOMAIN, LOGGER
from .oauth import NestOAuth2Implementation
from .pynest.client import NestClient
from .pynest.const import DEFAULT_NEST_ENVIRONMENT
from .pynest.exceptions import BadCredentialsException, PynestException


class ConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=NEST_PROTECT_DOMAIN
):
    """Config flow for Nest Protect."""

    VERSION = 5

    DOMAIN = NEST_PROTECT_DOMAIN

    _config_entry: ConfigEntry | None = None

    def __init__(self) -> None:
        """Initialize the config flow."""

        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._implementation_domain: str | None = None

    @property
    def logger(self):
        """Return the logger to use for the flow."""

        return LOGGER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step with guidance."""

        self._config_entry = None

        if user_input is not None:
            return await self.async_step_credentials()

        description_placeholders: dict[str, Any] = {}

        try:
            external_url = get_url(
                self.hass,
                prefer_external=True,
                allow_internal=False,
                allow_ip=False,
                allow_cloud=False,
            )
        except NoURLAvailableError:
            external_url = None

        if external_url and "my.home-assistant.io" in external_url:
            external_url = None

        if external_url:
            redirect_uri_example = f"{external_url.rstrip('/')}/auth/external/callback"
        else:
            redirect_uri_example = "https://myha.duckdns.org:8123/auth/external/callback"

        description_placeholders["redirect_uri_example"] = redirect_uri_example

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders=description_placeholders,
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the OAuth client credentials."""

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
                if not self._implementation_domain:
                    self._implementation_domain = (
                        f"{self.DOMAIN}_{uuid.uuid4().hex}"
                    )

                implementation = NestOAuth2Implementation(
                    self.hass,
                    self._implementation_domain,
                    self._client_id,
                    self._client_secret,
                )
                config_entry_oauth2_flow.async_register_implementation(
                    self.hass, self.DOMAIN, implementation
                )
                self.flow_impl = implementation

                return await self.async_step_auth()

        defaults = {}
        if self._client_id:
            defaults["client_id"] = self._client_id
        if self._client_secret:
            defaults["client_secret"] = self._client_secret

        data_schema = vol.Schema(
            {
                vol.Required(
                    "client_id", default=defaults.get("client_id", vol.UNDEFINED)
                ): str,
                vol.Required(
                    "client_secret",
                    default=defaults.get("client_secret", vol.UNDEFINED),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle re-authentication of an existing entry."""

        entry_id = self.context.get("entry_id")
        self._config_entry = (
            self.hass.config_entries.async_get_entry(entry_id)
            if entry_id
            else None
        )

        if self._config_entry is None:
            return self.async_abort(reason="unknown")

        self._client_id = self._config_entry.data.get("client_id")
        self._client_secret = self._config_entry.data.get("client_secret")
        self._implementation_domain = self._config_entry.data.get(
            "auth_implementation"
        )

        return await self.async_step_credentials(user_input)

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the OAuth authorization step and log common errors."""

        try:
            return await super().async_step_auth(user_input)
        except config_entry_oauth2_flow.OAuthError as err:
            error_reason = err.error or "oauth_error"
            if error_reason == "redirect_uri_mismatch":
                LOGGER.warning(
                    "Google OAuth Fehler redirect_uri_mismatch. Prüfe, ob die externe URL "
                    "von Home Assistant exakt mit der autorisierten Weiterleitungs-URI in der "
                    "Google Cloud Console übereinstimmt, inklusive /auth/external/callback."
                )
            else:
                LOGGER.warning(
                    "Google OAuth Fehler %s. Beschreibung: %s", error_reason, err.description
                )
            raise

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Finalize the OAuth flow and create/update the config entry."""

        session = async_create_clientsession(self.hass)
        client = NestClient(session=session, environment=DEFAULT_NEST_ENVIRONMENT)

        try:
            nest = await client.authenticate(data["token"]["access_token"])
            first_data = await client.get_first_data(nest.access_token, nest.userid)
        except BadCredentialsException:
            return self.async_abort(reason="invalid_auth")
        except ClientError:
            return self.async_abort(reason="cannot_connect")
        except PynestException as err:
            LOGGER.exception("Unexpected error while completing OAuth: %s", err)
            return self.async_abort(reason="unknown")

        email = nest.email
        if not email:
            for bucket in first_data.updated_buckets:
                if bucket.object_key.startswith("user."):
                    email = bucket.value.get("email")
                    if email:
                        break

        await self.async_set_unique_id(nest.user)

        entry_data = {
            "client_id": self._client_id or "",
            "client_secret": self._client_secret or "",
            "auth_implementation": self.flow_impl.domain,
            "token": data["token"],
        }

        title_email = email or nest.userid
        title = f"Nest Protect ({title_email})"

        if self._config_entry:
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=entry_data, title=title
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self._config_entry.entry_id)
            )
            return self.async_abort(reason="reauth_successful")

        self._abort_if_unique_id_configured(updates=entry_data)

        return self.async_create_entry(title=title, data=entry_data)
