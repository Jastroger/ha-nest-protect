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
    """Runtime data stored for this config entry."""
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
        LOGGER.error("No access_token in config entry; cannot authenticate.")
        restricted = True
        restricted_reason = "missing_access_token"
        devices = {}
    else:
        # Try authenticate + fetch devices
        restricted = False
        restricted_reason = None
        devices = {}

        try:
            await client.authenticate(access_token)
            fetched = await client.fetch_devices()
            devices = fetched or {}
            restricted = client.restricted
            restricted_reason = client.restricted_reason
        except PynestException as err:
            LOGGER.warning(
                "Nest Protect startup in restricted fallback: %s", err
            )
            restricted = True
            restricted_reason = str(err)
            try:
                # fallback dummy devices
                devices = client._dummy_devices()
            except Exception:
                devices = {}
        except Exception as err:
            # network issue etc.
            raise ConfigEntryNotReady from err

    hass.data[DOMAIN][entry.entry_id] = HomeAssistantNestProtectData(
        client=client,
        devices=devices,
        restricted=restricted,
        restricted_reason=restricted_reason,
    )

    # Forward to platforms (sensor, binary_sensor, switch, select)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
