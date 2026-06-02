"""Adds config flow for Nest Protect."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlencode

from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .auth_bridge import (
    AuthBridgeSession,
    cleanup_expired_auth_bridge_sessions,
    create_auth_bridge_session,
    is_auth_bridge_session_expired,
    is_valid_cookie_header,
    is_valid_issue_token,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_ACCOUNT_TYPE,
    CONF_AUTH_BRIDGE_SESSION,
    CONF_COOKIES,
    CONF_ISSUE_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_WIZARD_OUTPUT,
    DOMAIN,
    LOGGER,
)
from .pynest.client import NestClient
from .pynest.const import NEST_ENVIRONMENTS
from .pynest.enums import BucketType, Environment
from .pynest.exceptions import BadCredentialsException


class NoNestProtectDevicesFound(Exception):
    """Raised when authentication works but no supported devices are returned."""


class UnexpectedNestResponse(Exception):
    """Raised when Nest returns a response that cannot be used."""


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Nest Protect."""

    VERSION = 3
    _ISSUE_TOKEN_URL_PREFIX = "https://accounts.google.com/o/oauth2/iframerpc"
    _AUTH_BRIDGE_INGRESS_PATH = "/hassio/ingress/nest_protect_auth_bridge/"
    _SUPERVISOR_CORE_URL = "http://supervisor/core/api"

    _config_entry: ConfigEntry | None = None
    _default_account_type: Environment = Environment.PRODUCTION
    _auth_bridge_session: AuthBridgeSession | None = None

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
        return is_valid_issue_token(issue_token)

    @staticmethod
    def _validate_cookies(cookies: str) -> bool:
        """Validate cookies format.

        Cookies should be substantial, contain key-value pairs,
        and include typical Google auth cookie markers.
        """
        return is_valid_cookie_header(cookies)

    @staticmethod
    def _split_issue_token_and_cookies(
        issue_token: str, cookies: str
    ) -> tuple[str, str]:
        """Split combined issue token input when pasted with cookies.

        This method attempts to intelligently parse the input to extract
        both the issue token URL and cookies, even when pasted together.
        """
        # If cookies field already has content, don't try to split
        if cookies.strip():
            return issue_token, cookies

        lines = [line.strip() for line in issue_token.splitlines() if line.strip()]
        if len(lines) <= 1:
            return issue_token, cookies

        url_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.startswith(ConfigFlow._ISSUE_TOKEN_URL_PREFIX)
            ),
            None,
        )
        if url_index is None:
            return issue_token, cookies

        # Extract remaining lines as cookies
        remaining_lines = [
            line for index, line in enumerate(lines) if index != url_index
        ]
        if remaining_lines:
            cookies = "\n".join(remaining_lines)

        return lines[url_index], cookies

    @staticmethod
    def _parse_wizard_output(wizard_output: str) -> tuple[str, str]:
        """Parse copy-paste output produced by the external auth wizard."""
        issue_token = ""
        cookies = ""
        lines = [line.strip() for line in wizard_output.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            lower = line.lower()
            if line.startswith(ConfigFlow._ISSUE_TOKEN_URL_PREFIX):
                issue_token = line
                continue
            if lower.startswith("issue_token="):
                issue_token = line.split("=", 1)[-1].strip()
                continue
            if lower.startswith("issue_token:"):
                issue_token = line.split(":", 1)[-1].strip()
                continue
            if lower.startswith(("issue token url:", "issue token url=")):
                issue_token = line.split(":", 1)[-1].split("=", 1)[-1].strip()
                continue
            if lower in ("issue token url:", "issue token url") and index + 1 < len(lines):
                issue_token = lines[index + 1]
                continue
            if lower.startswith(("cookies=", "cookies:", "cookie header:", "cookie header=")):
                separator = "=" if "=" in line else ":"
                cookies = line.split(separator, 1)[-1].strip()
                continue
            if lower in ("cookie header:", "cookie header") and index + 1 < len(lines):
                cookies = lines[index + 1]
                continue

        if issue_token and not cookies:
            remaining = [line for line in lines if line != issue_token]
            cookie_lines = [
                line
                for line in remaining
                if "=" in line and not line.startswith(ConfigFlow._ISSUE_TOKEN_URL_PREFIX)
            ]
            if cookie_lines:
                cookies = "\n".join(cookie_lines)

        return issue_token, cookies

    def _normalize_and_validate_credentials(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Normalize and validate issue token and cookies.

        Returns a dict of field-specific error messages.
        """
        wizard_output_raw = user_input.get(CONF_WIZARD_OUTPUT, "")
        issue_token_raw = user_input.get(CONF_ISSUE_TOKEN, "")
        cookies_raw = user_input.get(CONF_COOKIES, "")

        if wizard_output_raw:
            wizard_issue_token, wizard_cookies = self._parse_wizard_output(
                wizard_output_raw
            )
            issue_token_raw = issue_token_raw or wizard_issue_token
            cookies_raw = cookies_raw or wizard_cookies

        issue_token_raw, cookies_raw = self._split_issue_token_and_cookies(
            issue_token_raw,
            cookies_raw,
        )
        issue_token = self._normalize_issue_token(issue_token_raw)
        cookies = self._normalize_cookies(cookies_raw)

        user_input[CONF_ISSUE_TOKEN] = issue_token
        user_input[CONF_COOKIES] = cookies
        user_input.pop(CONF_WIZARD_OUTPUT, None)

        errors: dict[str, str] = {}

        # Validate issue token first
        if not issue_token:
            errors[CONF_WIZARD_OUTPUT if wizard_output_raw else CONF_ISSUE_TOKEN] = (
                "missing_issue_token"
            )
        elif not self._validate_issue_token(issue_token):
            errors[CONF_WIZARD_OUTPUT if wizard_output_raw else CONF_ISSUE_TOKEN] = (
                "invalid_issue_token"
            )

        # Then validate cookies
        # Note: Cookies field is optional in the UI (users can paste both values
        # in the issue_token field), but after auto-splitting, cookies are still
        # required for authentication.
        if not cookies:
            errors[CONF_WIZARD_OUTPUT if wizard_output_raw else CONF_COOKIES] = (
                "missing_cookie_header"
            )
        elif not self._validate_cookies(cookies):
            errors[CONF_WIZARD_OUTPUT if wizard_output_raw else CONF_COOKIES] = (
                "incomplete_cookie_header"
            )

        return errors

    def _build_auth_bridge_callback_url(self, session_id: str) -> str:
        """Build callback URL reachable by add-ons through Supervisor/Core API."""
        return f"{self._SUPERVISOR_CORE_URL}/nest_protect/auth_bridge/{session_id}"

    def _build_auth_bridge_launch_url(self, session: AuthBridgeSession) -> str:
        """Build a single launch URL for the add-on ingress page."""
        callback_url = self._build_auth_bridge_callback_url(session.session_id)
        launch_data = {
            "session_id": session.session_id,
            "secret": session.secret,
            "callback_url": callback_url,
        }
        base_url = (
            (self.hass.config.internal_url or self.hass.config.external_url or "")
            .rstrip("/")
        )
        ingress_url = (
            f"{base_url}{self._AUTH_BRIDGE_INGRESS_PATH}"
            if base_url
            else self._AUTH_BRIDGE_INGRESS_PATH
        )
        return ingress_url + "?" + urlencode(launch_data, safe=":/")

    async def async_validate_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Validate user credentials."""

        environment = user_input.get(CONF_ACCOUNT_TYPE, Environment.PRODUCTION)
        session = async_get_clientsession(self.hass)
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

        if not hasattr(data, "updated_buckets"):
            raise UnexpectedNestResponse("Nest response did not include buckets.")

        email = ""
        has_supported_device = False
        for bucket in data.updated_buckets:
            key = bucket.object_key
            if key.startswith("user."):
                email = bucket.value.get("email", "")
            if bucket.type in (BucketType.TOPAZ, BucketType.KRYPTONITE):
                has_supported_device = True

        if not has_supported_device:
            raise NoNestProtectDevicesFound(
                "Authentication succeeded but no Nest Protect devices were found."
            )

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
        return await self.async_step_auth_bridge_start(user_input)

    async def async_step_auth_bridge_start(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start the auth bridge flow."""
        if user_input is not None:
            self._auth_bridge_session = create_auth_bridge_session(self.hass)
            return await self.async_step_auth_bridge_wait()

        return self.async_show_form(
            step_id="auth_bridge_start",
            data_schema=vol.Schema({}),
            description_placeholders={
                "session_id": "",
            },
        )

    async def async_step_auth_bridge_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for the auth bridge callback."""
        cleanup_expired_auth_bridge_sessions(self.hass)
        if self._auth_bridge_session and is_auth_bridge_session_expired(
            self._auth_bridge_session
        ):
            self._auth_bridge_session = None

        if not self._auth_bridge_session:
            self._auth_bridge_session = create_auth_bridge_session(self.hass)

        session = self._auth_bridge_session

        if user_input is not None and user_input.get("fallback"):
            return await self.async_step_wizard_login()

        if session.result:
            user_input = {
                CONF_ISSUE_TOKEN: session.result.get(CONF_ISSUE_TOKEN, ""),
                CONF_COOKIES: session.result.get(CONF_COOKIES, ""),
            }
            return await self.async_step_account_link(user_input)

        launch_url = self._build_auth_bridge_launch_url(session)

        return self.async_show_form(
            step_id="auth_bridge_wait",
            data_schema=vol.Schema({vol.Optional("fallback", default=False): bool}),
            description_placeholders={
                CONF_AUTH_BRIDGE_SESSION: session.session_id,
                "auth_bridge_launch_url": launch_url,
            },
        )

    async def async_step_wizard_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle wizard-assisted login with automated credential extraction."""
        if user_input:
            errors = self._normalize_and_validate_credentials(user_input)
            if errors:
                return self.async_show_form(
                    step_id="wizard_login",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_WIZARD_OUTPUT, default=""): str,
                            vol.Optional(CONF_ISSUE_TOKEN, default=""): str,
                            vol.Optional(CONF_COOKIES, default=""): str,
                        }
                    ),
                    errors=errors,
                    description_placeholders={
                        "nest_url": "https://home.nest.com",
                    },
                )

            return await self.async_step_account_link(user_input)

        # Show the wizard page with instructions and helper script
        return self.async_show_form(
            step_id="wizard_login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WIZARD_OUTPUT, default=""): str,
                    vol.Optional(CONF_ISSUE_TOKEN, default=""): str,
                    vol.Optional(CONF_COOKIES, default=""): str,
                }
            ),
            description_placeholders={
                "nest_url": "https://home.nest.com",
            },
        )

    async def async_step_account_link(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input:
            user_input[CONF_ACCOUNT_TYPE] = self._default_account_type
            errors = self._normalize_and_validate_credentials(user_input)

            if not errors:
                try:
                    validation = await self.async_validate_input(user_input)
                    email = validation["email"]
                    token_payload = validation["token_payload"]
                except TimeoutError:
                    errors["base"] = "network_timeout"
                except ClientError:
                    errors["base"] = "cannot_connect"
                except BadCredentialsException:
                    errors["base"] = "authentication_rejected"
                except NoNestProtectDevicesFound:
                    errors["base"] = "no_devices_found"
                except UnexpectedNestResponse:
                    errors["base"] = "unexpected_response"
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
            step_id="wizard_login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WIZARD_OUTPUT, default=""): str,
                    vol.Optional(CONF_ISSUE_TOKEN, default=""): str,
                    vol.Optional(CONF_COOKIES, default=""): str,
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

        self._default_account_type = self._config_entry.data.get(
            CONF_ACCOUNT_TYPE, Environment.PRODUCTION
        )

        return await self.async_step_auth_bridge_start(user_input)
