"""SDM client helpers for Nest Protect using Smart Device Management API."""

from __future__ import annotations

import aiohttp
from typing import Any

SDM_BASE = "https://smartdevicemanagement.googleapis.com/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


async def exchange_code_for_tokens(
    session: aiohttp.ClientSession,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str = "https://www.google.com",
) -> dict[str, Any]:
    """
    Exchange an authorization code for tokens.
    Returns JSON containing access_token, refresh_token, expires_in, ...
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    async with session.post(OAUTH_TOKEN_URL, data=data) as resp:
        payload = await resp.json()
        if resp.status >= 400:
            raise Exception(f"Token exchange failed: {resp.status} - {payload}")
        return payload


async def refresh_tokens(
    session: aiohttp.ClientSession, client_id: str, client_secret: str, refresh_token: str
) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with session.post(OAUTH_TOKEN_URL, data=data) as resp:
        payload = await resp.json()
        if resp.status >= 400:
            raise Exception(f"Token refresh failed: {resp.status} - {payload}")
        return payload


async def sdm_list_devices(session: aiohttp.ClientSession, access_token: str, enterprise_name: str) -> dict:
    """
    Call SDM devices.list for the enterprise (enterprise name like 'enterprises/XYZ').
    Docs: devices.list under Smart Device Management API. :contentReference[oaicite:4]{index=4}
    """
    url = f"{SDM_BASE}/{enterprise_name}/devices"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with session.get(url, headers=headers) as resp:
        payload = await resp.json()
        if resp.status >= 400:
            raise Exception(f"SDM devices.list failed: {resp.status} - {payload}")
        return payload


async def sdm_execute_command(
    session: aiohttp.ClientSession, access_token: str, device_name: str, command: dict
) -> dict:
    """
    Execute a command on a device:
    POST {SDM_BASE}/{device_name}:executeCommand
    device_name example: enterprises/PROJECT/devices/DEVICEID
    command example: {"command": "sdm.devices.commands.SmokeAlarm.Silence", "params": {}}
    """
    url = f"{SDM_BASE}/{device_name}:executeCommand"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with session.post(url, headers=headers, json=command) as resp:
        payload = await resp.json()
        if resp.status >= 400:
            raise Exception(f"SDM executeCommand failed: {resp.status} - {payload}")
        return payload
