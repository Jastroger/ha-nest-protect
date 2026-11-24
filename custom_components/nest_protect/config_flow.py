"""Adds config flow for Nest Protect."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import urlencode, urlsplit

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .auth_bridge import (
    AuthBridgeSession,
    create_auth_bridge_session,
    get_auth_bridge_store,
    register_auth_bridge_view,
)
from .const import (
    CONF_ACCOUNT_TYPE,
    CONF_AUTH_CODE,
    CONF_COOKIES,
    CONF_ISSUE_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    LOGGER,
)
from .pynest.client import NestClient
from .pynest.const import NEST_ENVIRONMENTS
from .pynest.enums import Environment
from .pynest.exceptions import BadCredentialsException, NestServiceException

DESCRIPTION_PLACEHOLDERS = {
    "nest_url": "https://home.nest.com",
    "issue_token_prefix": "https://accounts.google.com/o/oauth2/iframerpc?action=issueToken",
    "accounts_url": "https://accounts.google.com/",
    # Pinned to a specific release rather than "latest", which may resolve to a
    # pre-release that is incompatible with this version of the integration.
    "extension_download_url": "https://github.com/iMicknl/ha-nest-protect/releases/download/v0.5.0/nest-auth-helper.zip",
}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Nest Protect."""

    VERSION = 3

    _default_account_type: Environment = Environment.PRODUCTION
    _auth_bridge_session: AuthBridgeSession | None = None
    _auth_bridge_error: str = "invalid_auth"

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
        return "?" in issue_token

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

    @staticmethod
    def _normalize_cookies(cookies: str) -> str:
        """Normalize a pasted cookie header.

        Long header values copied from browser developer tools can contain line
        wraps, and some browsers include the header name in the copied text.
        """
        cookies = "".join(line.strip() for line in cookies.splitlines())
        cookies = re.sub(r"^cookie:\s*", "", cookies, flags=re.IGNORECASE)
        return "; ".join(part.strip() for part in cookies.split(";") if part.strip())

    async def async_validate_input(self, user_input: dict[str, Any]) -> list:
        """Validate user credentials."""

        environment = user_input[CONF_ACCOUNT_TYPE]
        session = async_create_clientsession(self.hass)
        client = NestClient(session=session, environment=NEST_ENVIRONMENTS[environment])

        issue_token = user_input.get(CONF_ISSUE_TOKEN)
        cookies = user_input.get(CONF_COOKIES)
        refresh_token = user_input.get(CONF_REFRESH_TOKEN)

        if issue_token and cookies:
            auth = await client.get_access_token_from_cookies(issue_token, cookies)
        elif refresh_token:
            auth = await client.get_access_token_from_refresh_token(refresh_token)

        nest = await client.authenticate(auth.access_token)
        data = await client.get_first_data(nest.access_token, nest.userid)

        if client.refreshed_cookies:
            cookies = client.refreshed_cookies

        email = ""
        for bucket in data.updated_buckets:
            key = bucket.object_key
            if key.startswith("user."):
                email = bucket.value["email"]

        # Set unique id to user_id (object.key: user.xxxx)
        await self.async_set_unique_id(nest.user)

        return [issue_token, cookies, email]

    def _async_create_or_update_entry(
        self, data: dict[str, Any], email: str
    ) -> FlowResult:
        """Create a new entry, or update the entry being reauthenticated/reconfigured."""
        if self.source not in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"Nest Protect ({email})", data=data)

        entry = (
            self._get_reauth_entry()
            if self.source == SOURCE_REAUTH
            else self._get_reconfigure_entry()
        )

        # Entries created before v0.4.0 are keyed by their refresh token instead
        # of the Nest user ID, so the account can't be compared. Adopt the account
        # that was just authenticated, unless another entry already owns it.
        if not entry.unique_id or not entry.unique_id.startswith("user."):
            if self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, self.unique_id
            ):
                return self.async_abort(reason="already_configured")
            return self.async_update_reload_and_abort(
                entry, unique_id=self.unique_id, data_updates=data
            )

        self._abort_if_unique_id_mismatch(reason="wrong_account")
        return self.async_update_reload_and_abort(entry, data_updates=data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
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

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle auth method selection."""
        if user_input:
            if user_input["method"] == "bridge":
                return await self.async_step_auth_bridge()
            if user_input["method"] == "extension":
                return await self.async_step_extension()
            return await self.async_step_account_link()

        return self.async_show_form(
            step_id="auth_method",
            data_schema=vol.Schema(
                {
                    vol.Required("method", default="bridge"): SelectSelector(
                        SelectSelectorConfig(
                            options=["bridge", "extension", "manual"],
                            translation_key="auth_method",
                        )
                    ),
                }
            ),
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )

    async def async_step_auth_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the Auth Bridge installation type."""
        return self.async_show_menu(
            step_id="auth_bridge",
            menu_options=["auth_bridge_addon", "auth_bridge_standalone"],
        )

    async def async_step_auth_bridge_addon(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Open the bridge installed through Home Assistant."""
        return self._start_auth_bridge(
            "/hassio/ingress/nest_protect_auth_bridge/", addon=True
        )

    async def async_step_auth_bridge_standalone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the standalone bridge URL."""
        errors = {}
        if user_input is not None:
            bridge_url = user_input["bridge_url"].strip().rstrip("/")
            try:
                parsed = urlsplit(bridge_url)
                valid = (
                    parsed.scheme in ("http", "https")
                    and bool(parsed.hostname)
                    and parsed.port != 0
                    and parsed.username is None
                    and not parsed.query
                    and not parsed.fragment
                )
            except ValueError:
                valid = False
            if valid:
                return self._start_auth_bridge(f"{bridge_url}/")
            errors["bridge_url"] = "invalid_auth_bridge_url"

        return self.async_show_form(
            step_id="auth_bridge_standalone",
            data_schema=vol.Schema({vol.Required("bridge_url"): str}),
            errors=errors,
        )

    def _start_auth_bridge(self, url: str, *, addon: bool = False) -> FlowResult:
        """Open the bridge with Home Assistant's native external step."""
        register_auth_bridge_view(self.hass)
        session = self._auth_bridge_session = create_auth_bridge_session(
            self.hass, flow_id=self.flow_id
        )
        query = {"session_id": session.session_id, "secret": session.secret}
        if addon:
            query["callback_url"] = (
                f"http://supervisor/core/api/nest_protect/auth_bridge/{session.session_id}"
            )
        return self.async_external_step(
            step_id="auth_bridge_login", url=f"{url}?{urlencode(query)}"
        )

    async def async_step_auth_bridge_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Advance only after the bridge has successfully called back."""
        session = self._auth_bridge_session
        if session is not None and session.result is not None:
            return self.async_external_step_done(next_step_id="auth_bridge_finish")
        assert self.cur_step is not None  # noqa: S101
        return self.cur_step

    async def async_step_auth_bridge_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate the returned credentials using the upstream account flow."""
        session = self._auth_bridge_session
        if session is not None and session.result is not None:
            data = session.result
            session.result = None
            self._auth_bridge_session = None
            get_auth_bridge_store(self.hass).pop(session.session_id, None)
            result = await self.async_step_account_link(data.copy())
            if result["type"] != FlowResultType.FORM:
                return result
            self._auth_bridge_error = result.get("errors", {}).get(
                "base", "invalid_auth"
            )

        if user_input is not None:
            return await self.async_step_auth_method()
        return self.async_show_form(
            step_id="auth_bridge_finish", errors={"base": self._auth_bridge_error}
        )

    async def async_step_extension(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle authentication via Chrome extension code."""
        errors = {}

        if user_input:
            issue_token = ""
            cookies = ""

            try:
                decoded = json.loads(
                    base64.b64decode(user_input[CONF_AUTH_CODE]).decode()
                )
                issue_token = decoded["issue_token"]
                cookies = decoded["cookies"]
            except ValueError, KeyError, json.JSONDecodeError:
                errors[CONF_AUTH_CODE] = "invalid_code"

            if not errors and (
                not self._validate_issue_token(issue_token)
                or not self._validate_cookies(cookies)
            ):
                errors[CONF_AUTH_CODE] = "invalid_code"

            if not errors:
                validation_input = {
                    CONF_ISSUE_TOKEN: issue_token,
                    CONF_COOKIES: cookies,
                    CONF_ACCOUNT_TYPE: self._default_account_type,
                }
                try:
                    [issue_token, cookies, email] = await self.async_validate_input(
                        validation_input
                    )
                except TimeoutError, ClientError, NestServiceException:
                    errors["base"] = "cannot_connect"
                except BadCredentialsException:
                    errors["base"] = "invalid_auth"
                except Exception as exception:  # pylint: disable=broad-except
                    errors["base"] = "unknown"
                    LOGGER.exception(exception)

            if not errors:
                data = {
                    CONF_ISSUE_TOKEN: issue_token,
                    CONF_COOKIES: cookies,
                    CONF_ACCOUNT_TYPE: self._default_account_type,
                }
                return self._async_create_or_update_entry(data, email)

        return self.async_show_form(
            step_id="extension",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_CODE): str,
                }
            ),
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
            errors=errors,
        )

    async def async_step_account_link(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input:
            user_input[CONF_ACCOUNT_TYPE] = self._default_account_type
            issue_token = user_input.get(CONF_ISSUE_TOKEN, "").strip()
            cookies = self._normalize_cookies(user_input.get(CONF_COOKIES, ""))
            # Store stripped values back so downstream validation and API calls
            # use the normalized credentials
            user_input[CONF_ISSUE_TOKEN] = issue_token
            user_input[CONF_COOKIES] = cookies

            # Validate input format before making API calls
            if not self._validate_issue_token(issue_token):
                errors[CONF_ISSUE_TOKEN] = "invalid_issue_token"
            elif not self._validate_cookies(cookies):
                errors[CONF_COOKIES] = "invalid_cookies"

            if not errors:
                try:
                    [issue_token, cookies, email] = await self.async_validate_input(
                        user_input
                    )
                    user_input[CONF_ISSUE_TOKEN] = issue_token
                    user_input[CONF_COOKIES] = cookies
                except TimeoutError, ClientError, NestServiceException:
                    errors["base"] = "cannot_connect"
                except BadCredentialsException:
                    errors["base"] = "invalid_auth"
                except Exception as exception:  # pylint: disable=broad-except
                    errors["base"] = "unknown"
                    LOGGER.exception(exception)

            if not errors:
                return self._async_create_or_update_entry(user_input, email)

        return self.async_show_form(
            step_id="account_link",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ISSUE_TOKEN): str,
                    vol.Required(CONF_COOKIES): str,
                }
            ),
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
            errors=errors,
            last_step=True,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth."""
        self._default_account_type = self._get_reauth_entry().data[CONF_ACCOUNT_TYPE]

        return await self.async_step_auth_method()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle updating the credentials of an existing entry."""
        self._default_account_type = self._get_reconfigure_entry().data[
            CONF_ACCOUNT_TYPE
        ]

        return await self.async_step_auth_method()
