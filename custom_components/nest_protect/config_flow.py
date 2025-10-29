"""Adds config flow for Nest Protect."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import voluptuous as vol

from .const import CONF_ACCOUNT_TYPE, DOMAIN as NEST_PROTECT_DOMAIN, LOGGER
from .oauth import async_ensure_oauth_implementation
from .pynest.client import NestClient
from .pynest.const import NEST_ENVIRONMENTS
from .pynest.enums import Environment
from .pynest.exceptions import BadCredentialsException, PynestException


class ConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=NEST_PROTECT_DOMAIN):
    """Config flow for Nest Protect."""

    VERSION = 4

    DOMAIN = NEST_PROTECT_DOMAIN

    _config_entry: ConfigEntry | None = None
    _default_account_type: Environment = Environment.PRODUCTION

    @property
    def logger(self):
        """Return the logger to use for the flow."""

        return LOGGER

    async def _async_register_implementation(self) -> None:
        """Ensure the selected implementation is registered and set."""

        implementation = await async_ensure_oauth_implementation(
            self.hass, self._default_account_type
        )
        self.flow_impl = implementation

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""

        self._config_entry = None

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_ACCOUNT_TYPE, default=self._default_account_type
                        ): vol.In(
                            {key: env.name for key, env in NEST_ENVIRONMENTS.items()}
                        )
                    }
                ),
            )

        self._default_account_type = user_input[CONF_ACCOUNT_TYPE]
        await self._async_register_implementation()

        return await self.async_step_auth()

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle re-authentication of an existing entry."""

        entry_id = self.context.get("entry_id")
        self._config_entry = (
            self.hass.config_entries.async_get_entry(entry_id)
            if entry_id
            else None
        )

        if self._config_entry is None:
            return self.async_abort(reason="unknown")

        self._default_account_type = self._config_entry.data[CONF_ACCOUNT_TYPE]
        await self._async_register_implementation()

        return await self.async_step_auth()

    async def async_oauth_create_entry(self, data: dict) -> FlowResult:
        """Finalize the OAuth flow and create/update the config entry."""

        session = async_create_clientsession(self.hass)
        environment = NEST_ENVIRONMENTS[self._default_account_type]
        client = NestClient(session=session, environment=environment)

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
            CONF_ACCOUNT_TYPE: self._default_account_type,
            "auth_implementation": data["auth_implementation"],
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
