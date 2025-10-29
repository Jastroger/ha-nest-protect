"""OAuth helpers for Nest Protect."""

from __future__ import annotations

import time
from typing import Any, cast
from urllib.parse import urlparse

from aiohttp import ClientError
from aiohttp.client_exceptions import ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, OAUTH_AUTHORIZE_URL, OAUTH_SCOPES
from .pynest.const import TOKEN_URL


class NestOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation for the Nest Protect integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        domain: str,
        client_id: str,
        client_secret: str,
        name: str = "Nest Protect",
    ) -> None:
        super().__init__(
            hass,
            domain,
            client_id,
            client_secret,
            OAUTH_AUTHORIZE_URL,
            TOKEN_URL,
        )
        self._name = name

    @property
    def name(self) -> str:
        """Return a friendly name for the implementation."""
        return self._name

    @property
    def redirect_uri(self) -> str:
        """
        Return the redirect URI.

        Idee:
        - Wenn der Nutzer über eine echte externe URL kommt
          (DuckDNS, eigene Domain, Nabu Casa Remote URL),
          dann benutzen wir genau diese Basis + /auth/external/callback.
        - Wir sperren nur den home-assistant.io Relay-Fall aus,
          weil das die zentrale Nabu-Casa-Proxy-Infrastruktur ist,
          die wir hier NICHT nutzen.
        - nabu.casa ist jetzt erlaubt.
        - Wenn nichts passt: Fallback auf das Standardverhalten
          von LocalOAuth2Implementation.
        """
        request = config_entry_oauth2_flow.http.current_request.get()
        if request is not None:
            frontend_base = request.headers.get(
                config_entry_oauth2_flow.HEADER_FRONTEND_BASE
            )
            if frontend_base:
                parsed = urlparse(frontend_base)
                hostname = (parsed.hostname or "").lower()

                if hostname and not hostname.endswith("home-assistant.io"):
                    base = frontend_base.rstrip("/")
                    if base:
                        return f"{base}{config_entry_oauth2_flow.AUTH_CALLBACK_PATH}"

        return super().redirect_uri

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Return extra data that needs to be appended to the authorize URL."""
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }


async def async_ensure_implementation_from_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Ensure that the OAuth implementation for a config entry is registered."""
    domain = config_entry.data.get("auth_implementation")
    if not domain:
        raise ConfigEntryAuthFailed("missing_auth_implementation")

    implementations = await config_entry_oauth2_flow.async_get_implementations(
        hass, DOMAIN
    )

    if domain in implementations:
        return implementations[domain]

    client_id = cast(str | None, config_entry.data.get("client_id"))
    client_secret = cast(str | None, config_entry.data.get("client_secret"))

    if not client_id or not client_secret:
        raise ConfigEntryAuthFailed("missing_client_credentials")

    implementation = NestOAuth2Implementation(
        hass,
        domain,
        client_id,
        client_secret,
    )
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
    implementation = await async_ensure_implementation_from_entry(hass, config_entry)
    return NestProtectOAuth2Session(hass, config_entry, implementation)


async def async_token_from_refresh_token(
    hass: HomeAssistant, client_id: str, client_secret: str, refresh_token: str
) -> dict[str, Any]:
    """Build a token payload from a stored refresh token."""
    session = async_get_clientsession(hass)
    response = await session.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
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
    payload["expires_at"] = int(payload.get("expires_at", 0)) or (
        int(time.time()) + expires_in
    )

    return payload
