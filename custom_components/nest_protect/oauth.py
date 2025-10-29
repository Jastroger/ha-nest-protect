"""OAuth helpers for Nest Protect (legacy Home Assistant OAuth2 flow with Nabu Casa redirect support)."""

from __future__ import annotations

import time
from typing import Any, cast
from urllib.parse import urlparse

from aiohttp import ClientError
from aiohttp.client_exceptions import ClientResponseError

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL, OAUTH_SCOPES


class NestOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation for Nest Protect."""

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
            OAUTH_TOKEN_URL,
        )
        self._name = name

    @property
    def name(self) -> str:
        """Return a human-friendly name."""
        return self._name

    @property
    def redirect_uri(self) -> str:
        """
        Return the redirect URI we tell Google.

        Ziel dieses Overrides:
        - Wenn der Flow im Browser über eine echte externe URL (z. B. deine Nabu-Casa-URL)
          aufgerufen wird, dann benutzen wir GENAU diese Basis-URL + /auth/external/callback.
        - Wir blocken nur den Sonderfall 'home-assistant.io' (my.home-assistant.io Relay),
          weil dieser Flow hier NICHT über deren zentralen Redirect-Proxy geht.
        - Wir erlauben ausdrücklich nabu.casa.
        - Wenn wir die echte URL nicht sauber erkennen können, fallback auf das
          Default-Verhalten von LocalOAuth2Implementation (super()).

        Wichtig: Die URL, die hier letztlich zurückkommt, MUSS 1:1 in der Google Cloud Console
        unter "Authorized redirect URIs" eingetragen sein. Beispiel:
        https://deinname.ui.nabu.casa/auth/external/callback
        """
        # Home Assistant setzt im OAuth-Flow einen aktuellen Request in einen ContextVar,
        # aus dem wir den Header X-HA-Frontend-Base (HEADER_FRONTEND_BASE) holen können.
        request = config_entry_oauth2_flow.http.current_request.get()
        if request is not None:
            frontend_base = request.headers.get(
                config_entry_oauth2_flow.HEADER_FRONTEND_BASE
            )
            if frontend_base:
                parsed = urlparse(frontend_base)
                hostname = (parsed.hostname or "").lower()

                # Wir wollen NICHT den zentralen my.home-assistant.io Redirect-Proxy verwenden.
                # Aber wir erlauben nabu.casa, duckdns, eigene Domain etc.
                if hostname and not hostname.endswith("home-assistant.io"):
                    base = frontend_base.rstrip("/")
                    if base:
                        return f"{base}{config_entry_oauth2_flow.AUTH_CALLBACK_PATH}"

        # Fallback auf das Standardverhalten (kann lokale IP sein)
        return super().redirect_uri

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Return extra data passed to the Google authorize URL."""
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }


async def async_ensure_implementation_from_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """
    Ensure that the OAuth implementation for this config entry is registered.

    This is necessary on Home Assistant restart: we may need to re-register
    the implementation so token refresh keeps working.
    """
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

    impl = NestOAuth2Implementation(
        hass,
        domain,
        client_id,
        client_secret,
    )
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, impl)

    # fetch again now that it's registered
    implementations = await config_entry_oauth2_flow.async_get_implementations(
        hass, DOMAIN
    )
    return implementations[domain]


class NestProtectOAuth2Session:
    """Wrapper around Home Assistant OAuth2Session to fetch/refresh tokens."""

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
        """Return the current stored token dict."""
        return self._session.token

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        try:
            await self._session.async_ensure_token_valid()
        except (ClientResponseError, ClientError) as err:
            raise ConfigEntryAuthFailed(err) from err
        except Exception as err:
            raise ConfigEntryAuthFailed(err) from err

        access_token = cast(str | None, self._session.token.get("access_token"))
        if not access_token:
            raise ConfigEntryAuthFailed("No OAuth access token available")

        return access_token


async def async_get_nest_oauth_session(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> NestProtectOAuth2Session:
    """Helper to build a NestProtectOAuth2Session from a ConfigEntry."""
    implementation = await async_ensure_implementation_from_entry(hass, config_entry)
    return NestProtectOAuth2Session(hass, config_entry, implementation)


async def async_token_from_refresh_token(
    hass: HomeAssistant, client_id: str, client_secret: str, refresh_token: str
) -> dict[str, Any]:
    """
    Manually refresh a token using the stored refresh_token.

    This is used if we want to rebuild a token dict for reauth.
    """
    session = async_get_clientsession(hass)
    async with session.post(
        OAUTH_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
    ) as resp:
        payload: dict[str, Any] = await resp.json()

    if resp.status >= 400 or "access_token" not in payload:
        raise ConfigEntryAuthFailed(payload.get("error", "oauth_error"))

    # normalize token shape for HA expectations
    expires_in_raw = payload.get("expires_in", 0)
    try:
        expires_in = int(expires_in_raw)
    except Exception:
        expires_in = 0

    payload.setdefault("refresh_token", refresh_token)
    payload["expires_in"] = expires_in
    payload["expires_at"] = int(time.time()) + expires_in if expires_in else 0

    return payload
