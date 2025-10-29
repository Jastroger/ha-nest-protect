"""Sensor platform for Nest Protect (legacy)."""

from __future__ import annotations

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity

from . import HomeAssistantNestProtectData
from .const import DOMAIN, LOGGER


async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]
    devices = data.devices or {}
    entities = []

    if isinstance(devices, dict):
        devs = devices.get("devices", []) or []
    else:
        devs = devices or []

    for dev in devs:
        if dev.get("traits", {}).get("sdm.devices.traits.Temperature") or dev.get("traits", {}).get("sdm.devices.traits.SensorState"):
            entities.append(SimpleNestSensor(data, dev))

    async_add_entities(entities)


class SimpleNestSensor(SensorEntity):
    def __init__(self, integration_data: HomeAssistantNestProtectData, device: dict):
        self._integration_data = integration_data
        self._device = device
        self._name = f"{device.get('customName') or device.get('name')} Battery"
        self._unique_id = f"{device.get('name')}_battery"

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def state(self):
        traits = self._device.get("traits", {})
        batt = traits.get("sdm.devices.traits.Battery")
        if batt:
            return batt.get("batteryHealth", batt.get("level"))
        return None
