"""Binary sensor platform for Nest Protect (Smoke/CO)."""

from __future__ import annotations
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .sdm_client import sdm_execute_command, sdm_get_device


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    """Set up binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data.get("sdm_devices", {}).get("devices", [])
    entities = []
    for dev in devices:
        traits = dev.get("traits", {})
        if any(k.endswith("SmokeAlarm") or k.endswith("CarbonMonoxide") for k in traits):
            entities.append(NestProtectBinarySensor(hass, entry.entry_id, dev))
    async_add_entities(entities)


class NestProtectBinarySensor(BinarySensorEntity):
    """Representation of a Nest Protect smoke/CO alarm."""

    def __init__(self, hass: HomeAssistant, entry_id: str, device: dict):
        self.hass = hass
        self._entry_id = entry_id
        self._device = device
        self._device_name = device.get("name")
        self._attr_name = device.get("customName") or device.get("name")
        self._attr_unique_id = self._device_name

    @property
    def is_on(self) -> bool:
        """Return true if alarm is active."""
        traits = self._device.get("traits", {})
        for trait_key, trait_value in traits.items():
            if trait_key.endswith("SmokeAlarm"):
                state = trait_value.get("alarmState") or trait_value.get("state", {}).get("alarmState")
                return state in ("SMOKE", "FIRE", "ALARM")
            if trait_key.endswith("CarbonMonoxide"):
                state = trait_value.get("alarmState") or trait_value.get("state", {}).get("alarmState")
                return state in ("CO_ALARM", "ALARM")
        return False

    @property
    def extra_state_attributes(self):
        data = self.hass.data[DOMAIN][self._entry_id]
        attrs = {"restricted": data.get("restricted", False)}
        if data.get("restricted_reason"):
            attrs["restricted_reason"] = data["restricted_reason"]
        return attrs

    async def async_update(self):
        """Refresh device state from SDM."""
        data = self.hass.data[DOMAIN][self._entry_id]
        if not data.get("device_access"):
            return
        session = async_get_clientsession(self.hass)
        try:
            updated = await sdm_get_device(session, data["access_token"], self._device_name)
            if updated:
                self._device = updated
        except Exception:
            pass

    async def async_silence(self):
        """Send Silence command."""
        data = self.hass.data[DOMAIN][self._entry_id]
        if not data.get("device_access"):
            raise RuntimeError("Device Access not configured")
        session = async_get_clientsession(self.hass)
        cmd = {"command": "sdm.devices.commands.SmokeAlarm.Silence", "params": {}}
        await sdm_execute_command(session, data["access_token"], self._device_name, cmd)
