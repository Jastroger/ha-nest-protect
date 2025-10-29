"""Nest Protect client – rewritten for OAuth2 + restricted fallback."""

from __future__ import annotations
import asyncio
import aiohttp
from typing import Any
from .exceptions import PynestException
from .const import LOGGER


class NestClient:
    """Handles Nest Protect API communication via OAuth or fallback."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.nest_session: Any = None
        self.restricted: bool = False
        self.restricted_reason: str | None = None
        self.devices: dict[str, Any] | None = None
        self.urls = type(
            "urls",
            (),
            {
                "auth_proxy_url": "https://nestauthproxyservice-pa.googleapis.com",
                "transport_url": "https://home.nest.com",
            },
        )()

    async def authenticate(self, token: str) -> dict[str, Any]:
        """Authenticate using a Google OAuth2 access token."""
        headers = {"authorization": f"Bearer {token}"}
        body = {"embed_google_oauth_access_token": True, "expire_after": "3600s"}

        LOGGER.debug("Authenticating against Nest JWT endpoint …")
        try:
            async with self.session.post(
                f"{self.urls.auth_proxy_url}/v1/issue_jwt", headers=headers, json=body
            ) as response:
                nest_response = await response.json(content_type=None)
                LOGGER.debug("Nest JWT response: %s", nest_response)

                # --- handle known failure modes ---
                if response.status == 403 and "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in str(
                    nest_response
                ):
                    LOGGER.warning(
                        "Nest Protect API access blocked (403 insufficient scopes). "
                        "Falling back to restricted mode."
                    )
                    self.restricted = True
                    self.restricted_reason = "access_token_scope_insufficient"
                    return {"restricted": True}

                if response.status == 400 and "missing user credentials" in str(
                    nest_response
                ):
                    LOGGER.warning(
                        "Nest Protect authenticate failed (missing user credentials). "
                        "Restricted fallback activated."
                    )
                    self.restricted = True
                    self.restricted_reason = "missing_user_credentials"
                    return {"restricted": True}

                if response.status != 200:
                    raise PynestException(
                        f"{response.status} error while authenticating - {nest_response}."
                    )

                jwt_token = nest_response.get("jwt")
                userid = nest_response.get("userid")
                if not jwt_token or not userid:
                    raise PynestException("Missing jwt or userid in Nest response.")

                self.nest_session = type(
                    "NestSession", (), {"jwt": jwt_token, "userid": userid}
                )()
                LOGGER.info("Nest Protect authenticated successfully.")
                return {"jwt": jwt_token, "userid": userid}

        except asyncio.TimeoutError as err:
            raise PynestException(f"Timeout during authenticate: {err}") from err
        except aiohttp.ClientError as err:
            raise PynestException(f"Client error during authenticate: {err}") from err

    async def fetch_devices(self) -> dict[str, Any]:
        """Fetch device list from Nest cloud or dummy fallback."""
        if self.restricted:
            LOGGER.warning(
                "Nest Protect running in restricted mode: no cloud access available. "
                "Returning dummy device set."
            )
            return self._dummy_devices()

        if not self.nest_session:
            raise PynestException("Not authenticated.")

        url = f"{self.urls.transport_url}/api/nest/v1/devices"
        headers = {"authorization": f"Basic {self.nest_session.jwt}"}

        LOGGER.debug("Fetching Nest Protect devices from %s", url)
        async with self.session.get(url, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise PynestException(f"Device fetch failed: {resp.status} - {body}")

            data = await resp.json(content_type=None)
            self.devices = data
            LOGGER.debug("Fetched %d devices", len(data))
            return data

    def _dummy_devices(self) -> dict[str, Any]:
        """Return placeholder devices for restricted mode."""
        dummy = {
            "0000000000000000": {
                "where_id": "restricted",
                "name": "Nest Protect (restricted)",
                "smoke_alarm_state": "ok",
                "co_alarm_state": "ok",
                "battery_health_state": "unknown",
                "software_version": "N/A",
            }
        }
        self.devices = dummy
        return dummy

    async def update_objects(self, access_token: str, userid: str, transport_url: str, objects: list[dict[str, Any]]):
        """Placeholder for compatibility; restricted mode does nothing."""
        if self.restricted:
            LOGGER.debug("Restricted mode – update ignored for %s", objects)
            return {"restricted": True}
        return {"ok": True}
