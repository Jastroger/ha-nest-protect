"""OAuth2 helper for Nest Protect fallback."""

from __future__ import annotations
import aiohttp
import asyncio
from typing import Any
from .pynest.exceptions import PynestException
from .const import LOGGER  # eine Ebene hoch (..), weil LOGGER im Hauptpaket liegt


class NestOAuthClient:
    """Handles OAuth2 code exchange and token refresh."""

    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, session: aiohttp.ClientSession, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.session = session
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_in: int = 0

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }

        LOGGER.debug("Exchanging OAuth code for tokens …")
        try:
            async with self.session.post(self.TOKEN_URL, data=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    raise PynestException(
                        f"OAuth token exchange failed: {resp.status} - {data}"
                    )
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.expires_in = int(data.get("expires_in", 0))
                LOGGER.debug("OAuth token exchange successful.")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PynestException(f"OAuth exchange error: {err}") from err

    async def refresh(self) -> dict[str, Any]:
        """Refresh access token using stored refresh token."""
        if not self.refresh_token:
            raise PynestException("No refresh token available.")

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        LOGGER.debug("Refreshing OAuth token …")
        try:
            async with self.session.post(self.TOKEN_URL, data=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    raise PynestException(
                        f"OAuth refresh failed: {resp.status} - {data}"
                    )
                self.access_token = data.get("access_token")
                self.expires_in = int(data.get("expires_in", 0))
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PynestException(f"OAuth refresh error: {err}") from err
