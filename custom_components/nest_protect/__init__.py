"""Nest Protect integration init."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, LOGGER, PLATFORMS
from .pynest.client import NestClient
from .pynest.exceptions import PynestException


@dataclass
class HomeAssistantNestProtectData:
    """Stored runtime data for this config entry."""
    client: NestClient | None
    devices: dict[str, Any]
    restricted: bool
    restricted_reason: str | None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Nest Protect from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    client = NestClient(session)

    access_token = entry.data.get("access_token")
    if not access_token:
        LOGGER.error(
            "No access_token in config entry; cannot authenticate. "
            "Falling back to restricted mode."
        )
        restricted = True
        restricted_reason = "missing_access_token"
        devices: dict[str, Any] = client._dummy_devices()
    else:
        restricted = False
        restricted_reason = None
        devices = {}

        try:
            # try to authenticate with Google access_token -> get Nest jwt
            await client.authenticate(access_token)

            # try to fetch devices
            fetched = await client.fetch_devices()
            devices = fetched or {}

            restricted = client.restricted
            restricted_reason = client.restricted_reason

        except PynestException as err:
            # nest blocked us / insufficient scopes / whatever.
            LOGGER.warning(
                "Nest Protect startup in restricted fallback: %s", err
            )
            restricted = True
            restricted_reason = str(err)
            try:
                devices = client._dummy_devices()
            except Exception:
                devices = {}
        except Exception as err:
            # network errors etc. should delay config entry setup
            raise ConfigEntryNotReady from err

    hass.data[DOMAIN][entry.entry_id] = HomeAssistantNestProtectData(
        client=client,
        devices=devices,
        restricted=restricted,
        restricted_reason=restricted_reason,
    )

    # load platforms (sensor / binary_sensor / switch / select)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Nest Protect config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
