"""Config flow for Nest Protect (extended with Device Access / SDM support)."""

from __future__ import annotations

import uuid
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.data_entry_flow import FlowResult
from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN as NEST_PROTECT_DOMAIN, LOGGER
from .oauth import NestOAuth2Implementation
from .pynest.client import NestClient
from .pynest.exceptions import BadCredentialsException, PynestException
from .device_access import build_partner_auth_url
from .sdm_client import exchange_code_for_tokens, sdm_list_devices

# Steps ids
STEP_USER = "user"
STEP_CREDENTIALS = "credentials"
STEP_AUTH = "auth"
STEP_DEVICE_ACCESS = "device_access"
STEP_DEVICE_ACCESS_CODE = "device_access_code"

class ConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=NEST_PROTECT_DOMAIN):
    """Config flow for Nest Protect."""

    VERSION = 7
    DOMAIN = NEST_PROTECT_DOMAIN

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._implementation_domain: str | None = None
        self._use_device_access: bool = False
        self._device_access_project_id: str | None = None
        self._device_access_enterprise: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """
        Initial step: ask user whether to use Device Access (recommended) or Legacy OAuth.
        """
        if user_input is not None:
            self._use_device_access = user_input.get("use_device_access", False)
            return await (self.async_step_device_access() if self._use_device_access else self.async_step_credentials())

        return self.async_show_form(
            step_id=STEP_USER,
            data_schema=vol.Schema({vol.Required("use_device_access", default=True): bool}),
            description_placeholders={},
        )

    async def async_step_device_access(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """
        Device Access step: collect Device Access project id and client credentials.
        Then build PartnerConnections URL and show it to the user.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            project_id = user_input.get("device_access_project_id", "").strip()
            client_id = user_input.get("client_id", "").strip()
            client_secret = user_input.get("client_secret", "").strip()
            if not project_id:
                errors["device_access_project_id"] = "required"
            if not client_id:
                errors["client_id"] = "required"
            if not client_secret:
                errors["client_secret"] = "required"
            if not errors:
                self._device_access_project_id = project_id
                self._client_id = client_id
                self._client_secret = client_secret
                # build URL and show it
                redirect_uri = "https://www.google.com"
                auth_url = build_partner_auth_url(project_id, client_id, redirect_uri)
                # show the user the URL to open and paste the returned code into the next step
                return self.async_show_form(
                    step_id=STEP_DEVICE_ACCESS_CODE,
                    data_schema=vol.Schema({vol.Required("auth_code"): str}),
                    description_placeholders={"auth_url": auth_url},
                )

        data_schema = vol.Schema(
            {
                vol.Required("device_access_project_id"): str,
                vol.Required("client_id"): str,
                vol.Required("client_secret"): str,
            }
        )

        return self.async_show_form(step_id=STEP_DEVICE_ACCESS, data_schema=data_schema, errors=errors)

    async def async_step_device_access_code(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """
        User pasted the authorization code from PartnerConnections redirect (or https://www.google.com URL).
        Exchange code for tokens and call SDM devices.list to validate.
        """
        assert self._device_access_project_id is not None
        assert self._client_id is not None and self._client_secret is not None

        if user_input is None:
            return self.async_abort(reason="user_cancelled")

        code = user_input.get("auth_code", "").strip()
        if not code:
            return self.async_show_form(step_id=STEP_DEVICE_ACCESS_CODE, errors={"auth_code": "required"})

        session = async_create_clientsession(self.hass)
        try:
            tokens = await exchange_code_for_tokens(session, self._client_id, self._client_secret, code, "https://www.google.com")
        except Exception as err:
            LOGGER.exception("Device Access token exchange failed: %s", err)
            return self.async_show_form(step_id=STEP_DEVICE_ACCESS_CODE, errors={"base": "token_error"})

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        # call SDM to list devices to ensure Device Access is authorized
        try:
            devices_resp = await sdm_list_devices(session, access_token, f"enterprises/{self._device_access_project_id}")
        except Exception as err:
            LOGGER.exception("SDM devices.list failed: %s", err)
            return self.async_show_form(step_id=STEP_DEVICE_ACCESS_CODE, errors={"base": "sdm_error"})

        # store config entry with SDM tokens & project info
        entry_data = {
            "device_access": True,
            "device_access_project_id": self._device_access_project_id,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "sdm_devices": devices_resp,
        }

        title = f"Nest Protect (Device Access: {self._device_access_project_id})"
        await self.async_set_unique_id(self._device_access_project_id)
        return self.async_create_entry(title=title, data=entry_data)

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Legacy path: collect client_id/client_secret for Google OAuth (your current implementation)."""
        errors = {}
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
                    self._implementation_domain = f"{self.DOMAIN}_{uuid.uuid4().hex}"
                implementation = NestOAuth2Implementation(self.hass, self._implementation_domain, self._client_id, self._client_secret)
                config_entry_oauth2_flow.async_register_implementation(self.hass, self.DOMAIN, implementation)
                self.flow_impl = implementation
                return await self.async_step_auth()

        data_schema = vol.Schema(
            {
                vol.Required("client_id", default=""): str,
                vol.Required("client_secret", default=""): str,
            }
        )

        return self.async_show_form(step_id=STEP_CREDENTIALS, data_schema=data_schema, errors=errors)

    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """
        Handle legacy OAuth2 flow; we keep your previous behavior for users who prefer that path.
        """
        try:
            return await super().async_step_auth(user_input)
        except config_entry_oauth2_flow.OAuthError as err:
            LOGGER.exception("OAuthError in legacy flow: %s", err)
            raise

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """
        After legacy OAuth completes, try to exchange tokens to Nest JWT (existing behavior).
        If Nest JWT fails, create restricted entry (as previously discussed).
        """
        session = async_create_clientsession(self.hass)
        client = NestClient(session=session)
        try:
            nest = await client.authenticate(data["token"]["access_token"])
            first_data = await client.get_first_data(nest.access_token, nest.userid)
        except BadCredentialsException:
            return self.async_abort(reason="invalid_auth")
        except PynestException as err:
            LOGGER.warning("Nest authenticate failed: %s", err)
            # create a restricted entry so the integration remains installable
            entry_data = {
                "client_id": self._client_id or "",
                "client_secret": self._client_secret or "",
                "auth_implementation": self.flow_impl.domain,
                "token": data.get("token"),
                "restricted": True,
                "restricted_reason": str(err),
            }
            title = f"Nest Protect (restricted)"
            return self.async_create_entry(title=title, data=entry_data)
        except Exception as err:
            LOGGER.exception("Unexpected error completing OAuth: %s", err)
            return self.async_abort(reason="unknown")

        # normal success path - create config entry with nested tokens
        email = nest.email or nest.userid
        await self.async_set_unique_id(nest.user)
        entry_data = {
            "client_id": self._client_id or "",
            "client_secret": self._client_secret or "",
            "auth_implementation": self.flow_impl.domain,
            "token": data["token"],
            "restricted": False,
        }
        title = f"Nest Protect ({email})"
        return self.async_create_entry(title=title, data=entry_data)
