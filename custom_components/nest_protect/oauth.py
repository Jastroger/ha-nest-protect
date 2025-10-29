"""OAuth helpers for Nest Protect (legacy Home Assistant LocalOAuth integration)."""

from __future__ import annotations
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_entry_oauth2_flow

from .const import OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL, OAUTH_SCOPES, DOMAIN


class NestOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation for Nest Protect (legacy)."""

    def __init__(
        self,
        hass: HomeAssistant,
        domain: str,
        client_id: str,
        client_secret: str,
        name: str = "Nest Protect",
    ) -> None:
        super().__init__(hass, domain, client_id, client_secret, OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }


async def async_ensure_implementation_from_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Ensure the implementation is registered and return it."""
    domain = config_entry.data.get("auth_implementation")
    if not domain:
        raise config_entry_oauth2_flow.ConfigEntryAuthFailed("missing_auth_implementation")

    implementations = await config_entry_oauth2_flow.async_get_implementations(hass, DOMAIN)
    if domain in implementations:
        return implementations[domain]

    client_id = cast(str | None, config_entry.data.get("client_id"))
    client_secret = cast(str | None, config_entry.data.get("client_secret"))
    if not client_id or not client_secret:
        raise config_entry_oauth2_flow.ConfigEntryAuthFailed("missing_client_credentials")

    impl = NestOAuth2Implementation(hass, domain, client_id, client_secret)
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, impl)
    implementations = await config_entry_oauth2_flow.async_get_implementations(hass, DOMAIN)
    return implementations[domain]
