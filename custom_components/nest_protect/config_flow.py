"""Adds config flow for Nest Protect."""

from __future__ import annotations

import os
from typing import Any, cast

from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import voluptuous as vol

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_ACCOUNT_TYPE,
    CONF_AUTH_METHOD,
    CONF_COOKIES,
    CONF_ISSUE_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    LOGGER,
)
from .pynest.client import NestClient
from .pynest.const import NEST_ENVIRONMENTS
from .pynest.enums import Environment
from .pynest.exceptions import BadCredentialsException


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Nest Protect."""

    VERSION = 3

    _config_entry: ConfigEntry | None = None
    _default_account_type: Environment = Environment.PRODUCTION
    _auth_method: str = "wizard"

    def _ensure_static_path_registered(self) -> None:
        """Ensure the www folder is registered for the credential helper.

        This is called during config flow to make the helper accessible
        even before the integration is fully set up.
        """
        www_path = os.path.join(os.path.dirname(__file__), "www")
        if os.path.exists(www_path):
            try:
                self.hass.http.register_static_path(
                    "/local/nest_protect",
                    www_path,
                    cache_headers=False
                )
                LOGGER.debug("Registered static path for credential helper at %s", www_path)
            except (ValueError, KeyError) as e:
                # Path is already registered, which is fine
                LOGGER.debug("Static path already registered or error: %s", e)
        else:
            LOGGER.warning("www folder not found at %s", www_path)

    @staticmethod
    def _normalize_issue_token(issue_token: str) -> str:
        """Normalize issue token input for validation."""
        return issue_token.strip()

    @staticmethod
    def _normalize_cookies(cookies: str) -> str:
        """Normalize cookie header input for validation."""
        lines = (line.strip() for line in cookies.splitlines())
        compact = " ".join(line for line in lines if line)
        return " ".join(compact.split())

    @staticmethod
    def _validate_issue_token(issue_token: str) -> bool:
        """Validate issue token format.

        The issue token URL should be from Google OAuth iframerpc endpoint
        with the issueToken action parameter.
        """
        if not issue_token.startswith("https://accounts.google.com/o/oauth2/iframerpc"):
            return False
        if "action=issueToken" not in issue_token:
            return False
        # Verify it looks like a proper URL with query parameters
        if "?" not in issue_token:
            return False
        return True

    @staticmethod
    def _validate_cookies(cookies: str) -> bool:
        """Validate cookies format.

        Cookies should be substantial, contain key-value pairs,
        and include typical Google auth cookie markers.
        """
        if len(cookies) <= 100:
            return False
        # Require at least one key=value pair
        if "=" not in cookies:
            return False
        # Common Google auth cookie names expected in exported cookie headers
        google_auth_markers = ("APISID=", "SAPISID=", "HSID=", "SSID=", "SID=")
        return any(marker in cookies for marker in google_auth_markers)

    async def async_validate_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Validate user credentials."""

        environment = user_input[CONF_ACCOUNT_TYPE]
        session = async_create_clientsession(self.hass)
        client = NestClient(session=session, environment=NEST_ENVIRONMENTS[environment])

        issue_token = None
        cookies = None
        refresh_token = None

        if CONF_ISSUE_TOKEN in user_input:
            issue_token = user_input[CONF_ISSUE_TOKEN]
        if CONF_COOKIES in user_input:
            cookies = user_input[CONF_COOKIES]
        if CONF_REFRESH_TOKEN in user_input:
            refresh_token = user_input[CONF_REFRESH_TOKEN]

        if issue_token and cookies:
            auth = await client.get_access_token_from_cookies(issue_token, cookies)
        elif refresh_token:
            auth = await client.get_access_token_from_refresh_token(refresh_token)
        else:
            raise BadCredentialsException("No authentication data provided.")

        nest = await client.authenticate(auth.access_token)
        data = await client.get_first_data(nest.access_token, nest.userid)

        email = ""
        for bucket in data.updated_buckets:
            key = bucket.object_key
            if key.startswith("user."):
                email = bucket.value["email"]

        # Set unique id to user_id (object.key: user.xxxx)
        await self.async_set_unique_id(nest.user)

        return {
            "email": email,
            "token_payload": {
                CONF_ACCESS_TOKEN: auth.access_token,
                CONF_ACCESS_TOKEN_EXPIRES_AT: auth.expiry_date.isoformat(),
            },
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        # Ensure static path is registered for credential helper
        self._ensure_static_path_registered()
        return await self.async_step_account_type(user_input)

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input and CONF_AUTH_METHOD in user_input:
            self._auth_method = user_input[CONF_AUTH_METHOD]
            if self._auth_method == "wizard":
                return await self.async_step_wizard_login()
            else:
                return await self.async_step_account_link()

        return self.async_show_form(
            step_id="auth_method",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_METHOD, default=self._auth_method): vol.In(
                        {
                            "wizard": "Wizard (recommended)",
                            "manual": "Manual",
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_wizard_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle wizard-assisted login with automated credential extraction."""
        # Ensure static path is registered for the credential helper
        self._ensure_static_path_registered()
        
        if user_input:
            # User has provided credentials (either manually or from wizard)
            return await self.async_step_account_link(user_input)

        # Show the wizard page with instructions and helper script
        return self.async_show_form(
            step_id="wizard_login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ISSUE_TOKEN): str,
                    vol.Required(CONF_COOKIES): str,
                }
            ),
            description_placeholders={
                "nest_url": "https://home.nest.com",
            },
        )

    async def async_step_account_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle account type selection."""
        errors = {}

        if user_input:
            self._default_account_type = user_input[CONF_ACCOUNT_TYPE]
            return await self.async_step_auth_method()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACCOUNT_TYPE, default=self._default_account_type
                    ): vol.In(
                        {key: env.name for key, env in NEST_ENVIRONMENTS.items()}
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_account_link(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input:
            user_input[CONF_ACCOUNT_TYPE] = self._default_account_type
            issue_token = self._normalize_issue_token(
                user_input.get(CONF_ISSUE_TOKEN, "")
            )
            cookies = self._normalize_cookies(user_input.get(CONF_COOKIES, ""))
            # Store normalized values back so downstream validation and API calls
            # use consistent credentials.
            user_input[CONF_ISSUE_TOKEN] = issue_token
            user_input[CONF_COOKIES] = cookies

            # Validate input format before making API calls
            if not self._validate_issue_token(issue_token):
                errors[CONF_ISSUE_TOKEN] = "invalid_issue_token"
            elif not self._validate_cookies(cookies):
                errors[CONF_COOKIES] = "invalid_cookies"

            if not errors:
                try:
                    validation = await self.async_validate_input(user_input)
                    email = validation["email"]
                    token_payload = validation["token_payload"]
                except (TimeoutError, ClientError):
                    errors["base"] = "cannot_connect"
                except BadCredentialsException:
                    errors["base"] = "invalid_auth"
                except Exception as exception:  # pylint: disable=broad-except
                    errors["base"] = "unknown"
                    LOGGER.exception(exception)

            if not errors:
                if self._config_entry:
                    # Update existing entry during reauth
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data={
                            **self._config_entry.data,
                            **user_input,
                            **token_payload,
                        },
                    )

                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(
                            self._config_entry.entry_id
                        )
                    )

                    return self.async_abort(reason="reauth_successful")

                self._abort_if_unique_id_configured()

                entry_data = {**user_input, **token_payload}
                return self.async_create_entry(
                    title=f"Nest Protect ({email})", data=entry_data
                )

        return self.async_show_form(
            step_id="account_link",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ISSUE_TOKEN): str,
                    vol.Required(CONF_COOKIES): str,
                }
            ),
            errors=errors,
            last_step=True,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth."""
        self._config_entry = cast(
            ConfigEntry,
            self.hass.config_entries.async_get_entry(self.context["entry_id"]),
        )

        self._default_account_type = self._config_entry.data[CONF_ACCOUNT_TYPE]

        return await self.async_step_account_link(user_input)
