"""Nest Protect integration init."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, LOGGER


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
    }

    for platform in ["binary_sensor", "sensor"]:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await hass.config_entries.async_forward_entry_unload(entry, platform)
        for platform in ["binary_sensor", "sensor"]
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
