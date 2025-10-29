"""Nest Protect integration - legacy-style initializer with HomeAssistantNestProtectData."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, LOGGER, PLATFORMS


@dataclass
class HomeAssistantNestProtectData:
    """Container with state stored for this integration entry."""
    hass: HomeAssistant
    entry: ConfigEntry
    client: Any | None = None
    nest_auth: dict | None = None
    user: str | None = None
    devices: dict | None = None
    restricted: bool = False
    restricted_reason: str | None = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Nest Protect integration for a config entry (legacy flow)."""
    hass.data.setdefault(DOMAIN, {})

    data = HomeAssistantNestProtectData(hass=hass, entry=entry)
    data.restricted = entry.data.get("restricted", False)
    data.restricted_reason = entry.data.get("restricted_reason")

    # store container
    hass.data[DOMAIN][entry.entry_id] = data

    # Forward setup to platforms (compat for HA versions)
    # Use new API if available, fallback to per-platform forwarding.
    try:
        if hasattr(hass.config_entries, "async_forward_entry_setups"):
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        else:
            for platform in PLATFORMS:
                hass.async_create_task(
                    hass.config_entries.async_forward_entry_setup(entry, platform)
                )
    except Exception as err:
        LOGGER.exception("Error forwarding entry setups: %s", err)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an entry."""
    unload_ok = True
    if hasattr(hass.config_entries, "async_unload_platforms"):
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    else:
        # fallback: try per-platform unload
        results = []
        for platform in PLATFORMS:
            try:
                res = await hass.config_entries.async_forward_entry_unload(entry, platform)
            except Exception:
                res = False
            results.append(res)
        unload_ok = all(results)

    hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
