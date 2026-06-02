"""Auth bridge session helpers for Nest Protect."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import secrets
from typing import Literal

from homeassistant.core import HomeAssistant

from .const import DOMAIN

AUTH_BRIDGE_DATA = "auth_bridge"
AUTH_BRIDGE_SESSION_TTL = datetime.timedelta(minutes=10)
ISSUE_TOKEN_URL_PREFIX = "https://accounts.google.com/o/oauth2/iframerpc"
AuthBridgeCompleteResult = Literal[
    "ok", "invalid_session", "expired_session", "already_completed"
]


@dataclass
class AuthBridgeSession:
    """Pending auth bridge callback state."""

    session_id: str
    secret: str
    expires_at: datetime.datetime
    result: dict[str, str] | None = None
    completed_at: datetime.datetime | None = None
    errors: dict[str, str] = field(default_factory=dict)


def get_auth_bridge_store(hass: HomeAssistant) -> dict[str, AuthBridgeSession]:
    """Return the auth bridge session store."""
    return hass.data.setdefault(DOMAIN, {}).setdefault(AUTH_BRIDGE_DATA, {})


def _utcnow() -> datetime.datetime:
    """Return a UTC now timestamp."""
    return datetime.datetime.now(tz=datetime.UTC)


def cleanup_expired_auth_bridge_sessions(hass: HomeAssistant) -> None:
    """Cleanup expired auth bridge sessions from store."""
    now = _utcnow()
    store = get_auth_bridge_store(hass)
    expired = [
        session_id
        for session_id, session in store.items()
        if session.expires_at <= now and session.completed_at is None
    ]
    for session_id in expired:
        store.pop(session_id, None)


def is_auth_bridge_session_expired(session: AuthBridgeSession) -> bool:
    """Return if auth bridge session expired."""
    return session.expires_at <= _utcnow()


def is_valid_issue_token(issue_token: str) -> bool:
    """Validate issue token format."""
    if not issue_token.startswith(ISSUE_TOKEN_URL_PREFIX):
        return False
    if "action=issueToken" not in issue_token:
        return False
    if "?" not in issue_token:
        return False
    return True


def is_valid_cookie_header(cookies: str) -> bool:
    """Validate cookie header format."""
    if len(cookies) <= 100:
        return False
    if "=" not in cookies:
        return False
    cookie_parts = [part.strip() for part in cookies.split(";") if part.strip()]
    if len(cookie_parts) < 3:
        return False
    for cookie_part in cookie_parts:
        if "=" not in cookie_part:
            return False
        name, value = cookie_part.split("=", 1)
        if not name.strip() or not value.strip():
            return False
    google_auth_markers = ("APISID=", "SAPISID=", "HSID=", "SSID=", "SID=")
    return any(marker in cookies for marker in google_auth_markers)


def create_auth_bridge_session(
    hass: HomeAssistant,
    *,
    ttl: datetime.timedelta = AUTH_BRIDGE_SESSION_TTL,
) -> AuthBridgeSession:
    """Create an auth bridge session for a config flow."""
    cleanup_expired_auth_bridge_sessions(hass)
    now = _utcnow()
    session = AuthBridgeSession(
        session_id=secrets.token_urlsafe(16),
        secret=secrets.token_urlsafe(32),
        expires_at=now + ttl,
    )
    get_auth_bridge_store(hass)[session.session_id] = session
    return session


def complete_auth_bridge_session(
    hass: HomeAssistant,
    session_id: str,
    secret: str,
    payload: dict[str, str],
) -> AuthBridgeCompleteResult:
    """Store auth bridge callback payload if the one-time secret matches."""
    session = get_auth_bridge_store(hass).get(session_id)
    if not session or not secrets.compare_digest(session.secret, secret):
        return "invalid_session"
    if session.expires_at <= _utcnow():
        get_auth_bridge_store(hass).pop(session_id, None)
        return "expired_session"
    if session.result is not None or session.completed_at is not None:
        return "already_completed"

    session.result = payload
    session.completed_at = _utcnow()
    return "ok"
