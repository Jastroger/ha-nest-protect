"""Auth bridge session helpers for Nest Protect."""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets

from homeassistant.core import HomeAssistant

from .const import DOMAIN

AUTH_BRIDGE_DATA = "auth_bridge"


@dataclass
class AuthBridgeSession:
    """Pending auth bridge callback state."""

    session_id: str
    secret: str
    result: dict[str, str] | None = None
    errors: dict[str, str] = field(default_factory=dict)


def get_auth_bridge_store(hass: HomeAssistant) -> dict[str, AuthBridgeSession]:
    """Return the auth bridge session store."""
    return hass.data.setdefault(DOMAIN, {}).setdefault(AUTH_BRIDGE_DATA, {})


def create_auth_bridge_session(hass: HomeAssistant) -> AuthBridgeSession:
    """Create an auth bridge session for a config flow."""
    session = AuthBridgeSession(
        session_id=secrets.token_urlsafe(16),
        secret=secrets.token_urlsafe(32),
    )
    get_auth_bridge_store(hass)[session.session_id] = session
    return session


def complete_auth_bridge_session(
    hass: HomeAssistant,
    session_id: str,
    secret: str,
    payload: dict[str, str],
) -> bool:
    """Store auth bridge callback payload if the one-time secret matches."""
    session = get_auth_bridge_store(hass).get(session_id)
    if not session or not secrets.compare_digest(session.secret, secret):
        return False

    session.result = payload
    return True
