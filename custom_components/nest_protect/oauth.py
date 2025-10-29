"""OAuth helpers for Nest Protect."""

from __future__ import annotations

import time
from typing import Any, cast

from aiohttp import ClientError
from aiohttp.client_exceptions import ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, OAUTH_AUTHORIZE_URL, OAUTH_SCOPES
from .pynest.const import NEST_ENVIRONMENTS, TOKEN_URL
from .pynest.enums import Environment
from .pynest.models import NestEnvironment


def implementation_domain(environment: Environment) -> str:
    """Return the config entry OAuth implementation domain."""

    return f"{DOMAIN}_{environment.value}"


class NestOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation for the Nest Protect integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        domain: str,
        environment: NestEnvironment,
    ) -> None:
        super().__init__(
            hass,
            domain,
            environment.client_id,
            environment.client_secret or "",
            OAUTH_AUTHORIZE_URL,
            TOKEN_URL,
        )
        self._environment = environment

    @property
    def name(self) -> str:  # pragma: no cover - simple property
        """Return a friendly name for the implementation."""

        return self._environment.name

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Return extra data that needs to be appended to the authorize url."""

        return {
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }


async def async_ensure_oauth_implementation(
    hass: HomeAssistant, environment: Environment
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Ensure that the OAuth implementation for the environment is registered."""

    domain = implementation_domain(environment)
    implementations = await config_entry_oauth2_flow.async_get_implementations(
        hass, DOMAIN
    )

    if domain not in implementations:
        env = NEST_ENVIRONMENTS[environment]
        implementation = NestOAuth2Implementation(hass, domain, env)
        config_entry_oauth2_flow.async_register_implementation(
            hass, DOMAIN, implementation
        )
        implementations = await config_entry_oauth2_flow.async_get_implementations(
            hass, DOMAIN
        )

    return implementations[domain]


class NestProtectOAuth2Session:
    """Thin wrapper around Home Assistant's OAuth2 session."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        implementation: config_entry_oauth2_flow.AbstractOAuth2Implementation,
    ) -> None:
        self._session = config_entry_oauth2_flow.OAuth2Session(
            hass, config_entry, implementation
        )

    @property
    def token(self) -> dict[str, Any]:
        """Return the current OAuth token."""

        return self._session.token

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing if required."""

        try:
            await self._session.async_ensure_token_valid()
        except (ClientResponseError, ClientError) as err:
            raise ConfigEntryAuthFailed(err) from err
        except Exception as err:  # pylint: disable=broad-except
            raise ConfigEntryAuthFailed(err) from err

        access_token = cast(str | None, self._session.token.get("access_token"))

        if not access_token:
            raise ConfigEntryAuthFailed("No OAuth access token available")

        return access_token


async def async_get_nest_oauth_session(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> NestProtectOAuth2Session:
    """Create an OAuth session for the config entry."""

    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, config_entry
        )
    )

    return NestProtectOAuth2Session(hass, config_entry, implementation)


async def async_token_from_refresh_token(
    hass: HomeAssistant, environment: Environment, refresh_token: str
) -> dict[str, Any]:
    """Build a token payload from a stored refresh token."""

    env = NEST_ENVIRONMENTS[environment]
    session = async_get_clientsession(hass)
    response = await session.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": env.client_id,
            "client_secret": env.client_secret,
            "grant_type": "refresh_token",
        },
    )

    try:
        payload: dict[str, Any] = await response.json()
    except ClientError as err:
        raise ConfigEntryAuthFailed(err) from err

    if response.status >= 400 or "access_token" not in payload:
        raise ConfigEntryAuthFailed(payload.get("error", "oauth_error"))

    payload.setdefault("refresh_token", refresh_token)
    expires_in = int(payload.get("expires_in", 0))
    payload["expires_in"] = expires_in
    payload["expires_at"] = time.time() + expires_in

    return payload
