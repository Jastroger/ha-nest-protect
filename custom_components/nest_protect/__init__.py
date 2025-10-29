"""Nest Protect integration init."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, LOGGER, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nest Protect integration from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "device_access": entry.data.get("device_access", False),
        "device_access_project_id": entry.data.get("device_access_project_id"),
        "access_token": entry.data.get("access_token"),
        "refresh_token": entry.data.get("refresh_token"),
        "sdm_devices": entry.data.get("sdm_devices"),
        "restricted": entry.data.get("restricted", False),
        "restricted_reason": entry.data.get("restricted_reason"),
        "no_devices_found": entry.data.get("no_devices_found"),
    }

    # Home Assistant API changed:
    # - Newer HA: hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # - Older HA: hass.config_entries.async_forward_entry_setup(entry, platform) per platform
    #
    # We'll try the new API first, fall back to the old one.

    if hasattr(hass.config_entries, "async_forward_entry_setups"):
        # New style: forward all platforms in one go
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    else:
        # Old style: forward one by one
        for platform in PLATFORMS:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = True
    if hasattr(hass.config_entries, "async_unload_platforms"):
        # Newer HA prefers async_unload_platforms
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, PLATFORMS
        )
    else:
        # Fallback for older HA
        results = []
        for platform in PLATFORMS:
            res = await hass.config_entries.async_forward_entry_unload(entry, platform)
            results.append(res)
        unload_ok = all(results)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
