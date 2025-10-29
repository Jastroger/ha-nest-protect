"""Config flow for Nest Protect (OAuth + Device Access)."""

from __future__ import annotations
import uuid
from typing import Any

import voluptuous as vol
import aiohttp
from homeassistant.data_entry_flow import FlowResult
from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import DOMAIN as NEST_PROTECT_DOMAIN, LOGGER
from .oauth import NestOAuth2Implementation
from .pynest.client import NestClient
from .pynest.exceptions import BadCredentialsException, PynestException
from .device_access import build_partner_auth_url
from .sdm_client import exchange_code_for_tokens, sdm_list_devices


class ConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=NEST_PROTECT_DOMAIN):
    """Config flow for Nest Protect integration."""

    VERSION = 7
    DOMAIN = NEST_PROTECT_DOMAIN

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._implementation_domain: str | None = None
        self._use_device_access: bool = False
        self._device_access_project_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._use_device_access = user_input.get("use_device_access", True)
            return await (self.async_step_device_access() if self._use_device_access else self.async_step_credentials())

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("use_device_access", default=True): bool}),
        )

    async def async_step_device_access(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
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
                redirect_uri = "https://www.google.com"
                auth_url = build_partner_auth_url(project_id, client_id, redirect_uri)
                return self.async_show_form(
                    step_id="device_access_code",
                    data_schema=vol.Schema({vol.Required("auth_code"): str}),
                    description_placeholders={"auth_url": auth_url},
                )

        schema = vol.Schema(
            {
                vol.Required("device_access_project_id"): str,
                vol.Required("client_id"): str,
                vol.Required("client_secret"): str,
            }
        )
        return self.async_show_form(step_id="device_access", data_schema=schema, errors=errors)

    async def async_step_device_access_code(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if not user_input:
            return self.async_abort(reason="user_cancelled")

        code = user_input.get("auth_code", "").strip()
        session = async_create_clientsession(self.hass)
        try:
            tokens = await exchange_code_for_tokens(session, self._client_id, self._client_secret, code, "https://www.google.com")
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            devices_resp = await sdm_list_devices(session, access_token, f"enterprises/{self._device_access_project_id}")
        except Exception as err:
            LOGGER.exception("Device Access flow failed: %s", err)
            return self.async_show_form(step_id="device_access_code", errors={"base": "auth_failed"})

        entry_data = {
            "device_access": True,
            "device_access_project_id": self._device_access_project_id,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "sdm_devices": devices_resp,
        }

        await self.async_set_unique_id(self._device_access_project_id)
        title = f"Nest Protect (Device Access {self._device_access_project_id})"
        return self.async_create_entry(title=title, data=entry_data)

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            cid = user_input.get("client_id", "").strip()
            csecret = user_input.get("client_secret", "").strip()
            if not cid:
                errors["client_id"] = "required"
            if not csecret:
                errors["client_secret"] = "required"
            if not errors:
                self._client_id = cid
                self._client_secret = csecret
                self._implementation_domain = f"{self.DOMAIN}_{uuid.uuid4().hex}"
                impl = NestOAuth2Implementation(self.hass, self._implementation_domain, self._client_id, self._client_secret)
                config_entry_oauth2_flow.async_register_implementation(self.hass, self.DOMAIN, impl)
                self.flow_impl = impl
                return await self.async_step_auth()

        schema = vol.Schema({
            vol.Required("client_id"): str,
            vol.Required("client_secret"): str,
        })
        return self.async_show_form(step_id="credentials", data_schema=schema, errors=errors)

    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        try:
            return await super().async_step_auth(user_input)
        except config_entry_oauth2_flow.OAuthError as err:
            LOGGER.exception("OAuth error: %s", err)
            raise

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        session = async_create_clientsession(self.hass)
        client = NestClient(session=session)
        try:
            nest = await client.authenticate(data["token"]["access_token"])
            first_data = await client.get_first_data(nest.access_token, nest.userid)
        except (BadCredentialsException, PynestException) as err:
            LOGGER.warning("Nest authenticate failed: %s", err)
            entry_data = {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "auth_implementation": self.flow_impl.domain,
                "token": data.get("token"),
                "restricted": True,
                "restricted_reason": str(err),
            }
            return self.async_create_entry(title="Nest Protect (restricted)", data=entry_data)

        email = nest.email or nest.userid
        await self.async_set_unique_id(nest.user)
        entry_data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "auth_implementation": self.flow_impl.domain,
            "token": data["token"],
            "restricted": False,
        }
        return self.async_create_entry(title=f"Nest Protect ({email})", data=entry_data)
