"""Auth bridge session helpers for Nest Protect."""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass, field
from typing import Literal

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow

from .const import CONF_COOKIES, CONF_ISSUE_TOKEN, DOMAIN

AUTH_BRIDGE_DATA = "auth_bridge"
AUTH_BRIDGE_VIEW_REGISTERED = f"{DOMAIN}_auth_bridge_view_registered"
AUTH_BRIDGE_SESSION_TTL = dt.timedelta(minutes=10)
GOOGLE_OAUTH_IFRAME_URL = "https://accounts.google.com/o/oauth2/iframerpc"
MIN_COOKIE_HEADER_LENGTH = 101
MIN_COOKIE_PAIRS = 3
AuthBridgeCompleteResult = Literal[
    "ok", "invalid_session", "expired_session", "already_completed"
]


@dataclass
class AuthBridgeSession:
    """Pending auth bridge callback state."""

    session_id: str
    secret: str
    expires_at: dt.datetime
    flow_id: str | None = None
    result: dict[str, str] | None = None
    completed_at: dt.datetime | None = None
    errors: dict[str, str] = field(default_factory=dict)


def get_auth_bridge_store(hass: HomeAssistant) -> dict[str, AuthBridgeSession]:
    """Return the auth bridge session store."""
    return hass.data.setdefault(DOMAIN, {}).setdefault(AUTH_BRIDGE_DATA, {})


def _utcnow() -> dt.datetime:
    """Return a UTC now timestamp."""
    return dt.datetime.now(tz=dt.UTC)


def cleanup_expired_auth_bridge_sessions(hass: HomeAssistant) -> None:
    """Cleanup expired auth bridge sessions from store."""
    now = _utcnow()
    store = get_auth_bridge_store(hass)
    expired = [
        session_id for session_id, session in store.items() if session.expires_at <= now
    ]
    for session_id in expired:
        store.pop(session_id, None)


def is_auth_bridge_session_expired(session: AuthBridgeSession) -> bool:
    """Return if auth bridge session expired."""
    return session.expires_at <= _utcnow()


def is_valid_issue_token(issue_token: str) -> bool:
    """Validate issue token format."""
    if not issue_token.startswith(GOOGLE_OAUTH_IFRAME_URL):
        return False
    if "action=issueToken" not in issue_token:
        return False
    return "?" in issue_token


def is_valid_cookie_header(cookies: str) -> bool:
    """Validate cookie header format."""
    if len(cookies) < MIN_COOKIE_HEADER_LENGTH:
        return False
    if "=" not in cookies:
        return False
    cookie_parts = [part.strip() for part in cookies.split(";") if part.strip()]
    if len(cookie_parts) < MIN_COOKIE_PAIRS:
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
    ttl: dt.timedelta = AUTH_BRIDGE_SESSION_TTL,
    flow_id: str | None = None,
) -> AuthBridgeSession:
    """Create an auth bridge session for a config flow."""
    cleanup_expired_auth_bridge_sessions(hass)
    now = _utcnow()
    session = AuthBridgeSession(
        session_id=secrets.token_urlsafe(16),
        secret=secrets.token_urlsafe(32),
        expires_at=now + ttl,
        flow_id=flow_id,
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


class NestProtectAuthBridgeView(HomeAssistantView):
    """Receive auth bridge callback payloads."""

    url = "/api/nest_protect/auth_bridge/{session_id}"
    name = "api:nest_protect:auth_bridge"
    requires_auth = False

    async def post(self, request: web.Request, session_id: str) -> web.Response:
        """Handle auth bridge credential callback."""
        hass = request.app["hass"]

        try:
            payload = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid_json"}, status=400)

        secret = payload.get("secret")
        issue_token = payload.get(CONF_ISSUE_TOKEN)
        cookies = payload.get(CONF_COOKIES)
        if (
            not isinstance(secret, str)
            or not isinstance(issue_token, str)
            or not isinstance(cookies, str)
        ):
            return web.json_response({"error": "missing_fields"}, status=400)
        if not secret or not issue_token or not cookies:
            return web.json_response({"error": "missing_fields"}, status=400)
        if not is_valid_issue_token(issue_token):
            return web.json_response({"error": "invalid_issue_token"}, status=400)
        if not is_valid_cookie_header(cookies):
            return web.json_response({"error": "invalid_cookie_header"}, status=400)

        complete_status = complete_auth_bridge_session(
            hass,
            session_id,
            secret,
            {
                CONF_ISSUE_TOKEN: issue_token,
                CONF_COOKIES: cookies,
            },
        )
        if complete_status == "invalid_session":
            return web.json_response({"error": "invalid_session"}, status=403)
        if complete_status == "expired_session":
            return web.json_response({"error": "expired_session"}, status=410)
        if complete_status == "already_completed":
            return web.json_response({"error": "already_completed"}, status=409)

        session = get_auth_bridge_store(hass)[session_id]
        if session.flow_id is not None:
            try:
                await hass.config_entries.flow.async_configure(session.flow_id, {})
            except UnknownFlow:
                get_auth_bridge_store(hass).pop(session_id, None)
                return web.json_response({"error": "invalid_session"}, status=410)

        return web.json_response({"ok": True})


@callback
def register_auth_bridge_view(hass: HomeAssistant) -> None:
    """Register the callback before the first entry is configured."""
    if not hass.data.get(AUTH_BRIDGE_VIEW_REGISTERED):
        hass.http.register_view(NestProtectAuthBridgeView())
        hass.data[AUTH_BRIDGE_VIEW_REGISTERED] = True
