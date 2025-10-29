"""Binary sensor platform for legacy Nest Protect integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeAssistantNestProtectData
from .const import DOMAIN, LOGGER


async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    """Set up binary sensors for the entry."""
    data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]
    devices = data.devices or {}
    entities = []

    # devices is expected to be a mapping or list depending on your client implementation
    if isinstance(devices, dict):
        devs = devices.get("devices", []) or []
    else:
        devs = devices or []

    for dev in devs:
        traits = dev.get("traits", {}) if isinstance(dev, dict) else {}
        if any(k.endswith("SmokeAlarm") or k.endswith("CarbonMonoxide") for k in traits.keys()):
            entities.append(NestProtectBinarySensor(data, dev))

    if not entities:
        LOGGER.debug("No Nest Protect smoke/CO devices found for entry %s", entry.entry_id)

    async_add_entities(entities)


class NestProtectBinarySensor(BinarySensorEntity):
    """Representation of a Nest Protect smoke/CO alarm (legacy)."""

    def __init__(self, integration_data: HomeAssistantNestProtectData, device: dict):
        self._integration_data = integration_data
        self._device = device
        self._name = device.get("customName") or device.get("name")
        self._unique_id = device.get("name")

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> bool:
        traits = self._device.get("traits", {})
        trait = traits.get("sdm.devices.traits.SmokeAlarm") or traits.get("sdm.devices.traits.CarbonMonoxideDetector")
        if not trait:
            return False
        # Different trait shapes may exist; be defensive
        alarm_state = trait.get("alarmState") or trait.get("state", {}).get("alarmState")
        return alarm_state in ("SMOKE", "FIRE", "ALARM", "CO_ALARM")
