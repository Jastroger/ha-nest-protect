"""Minimal wrapper for pynest client usage (legacy authentication path)."""

from __future__ import annotations
import aiohttp
import time
from typing import Any

from .exceptions import PynestException

NEST_AUTH_URL_JWT = "https://nestauthproxyservice-pa.googleapis.com/v1/issue_jwt"
# keep other internal constants in your existing pynest.const etc.

class NestAuthResult:
    def __init__(self, access_token: str, userid: str | None = None, email: str | None = None, user: str | None = None):
        self.access_token = access_token
        self.userid = userid
        self.email = email
        self.user = user

class NestClient:
    """Client wrapper that tries legacy nesting auth and surfaces clear exceptions."""

    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session or aiohttp.ClientSession()

    async def authenticate(self, google_access_token: str) -> NestAuthResult:
        """
        Try to exchange Google access token for Nest JWT via the known nestauthproxyservice.
        If the server rejects the request with a 400 + missing user credentials, raise PynestException.
        """
        headers = {"Authorization": f"Bearer {google_access_token}"}
        async with self._session.post(NEST_AUTH_URL_JWT, headers=headers, json={}) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                raise PynestException(f"{resp.status} error while authenticating - {text}")
            if resp.status >= 400:
                err = data or {}
                # Common response observed: {'error': 'invalid_request', 'error_description': 'missing user credentials'}
                msg = f"{resp.status} error while authenticating - {err}."
                raise PynestException(msg)
            # expected: {'jwt': '...', 'user': '...', 'userid': '...', ...}
            jwt = data.get("jwt") or data.get("nest_jwt") or data.get("access_token")
            userid = data.get("userid") or data.get("user_id") or data.get("sub")
            email = data.get("email")
            user = data.get("user") or userid
            if not jwt:
                raise PynestException(f"{resp.status} error while authenticating - missing token in response")
            return NestAuthResult(access_token=jwt, userid=userid, email=email, user=user)

    async def get_first_data(self, jwt_token: str, userid: str | None):
        """
        Placeholder: call initial endpoints using the Nest JWT. In your original implementation
        you probably fetch /app_launch or /session endpoints. Keep that code here.
        """
        # If you have existing implementation, keep it unchanged.
        raise NotImplementedError("Implement in your original pynest.client code")
