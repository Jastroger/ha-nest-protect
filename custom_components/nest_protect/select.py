"""Select platform for Nest Protect (brightness etc.)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.entity import EntityCategory

from . import HomeAssistantNestProtectData
from .const import DOMAIN, LOGGER
from .entity import NestDescriptiveEntity


@dataclass
class NestProtectSelectDescription(SelectEntityDescription):
    """Description of a Nest Protect select entity."""


# Mapping Helligkeitswerte <-> Presets
BRIGHTNESS_TO_PRESET: dict[int, str] = {
    1: "low",
    2: "medium",
    3: "high",
}
PRESET_TO_BRIGHTNESS = {v: k for k, v in BRIGHTNESS_TO_PRESET.items()}


SELECT_DESCRIPTIONS: list[NestProtectSelectDescription] = [
    NestProtectSelectDescription(
        key="night_light_brightness",
        translation_key="night_light_brightness",
        name="Brightness",
        icon="mdi:lightbulb-on",
        options=[*PRESET_TO_BRIGHTNESS],
        entity_category=EntityCategory.CONFIG,
    ),
]


async def async_setup_entry(hass, entry, async_add_devices):
    """Set up Nest Protect select entities."""
    data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]

    device_map = data.devices or {}
    entities: list[NestProtectSelect] = []

    SUPPORTED_KEYS: dict[str, NestProtectSelectDescription] = {
        description.key: description for description in SELECT_DESCRIPTIONS
    }

    for device in device_map.values():
        for key in getattr(device, "value", {}):
            if description := SUPPORTED_KEYS.get(key):
                entities.append(
                    NestProtectSelect(device, description, data.areas, data.client)
                )

    if not entities:
        LOGGER.debug(
            "nest_protect.select: keine Entities erzeugt. "
            "restricted=%s reason=%s devices_present=%s",
            getattr(data, "restricted", False),
            getattr(data, "restricted_reason", None),
            bool(device_map),
        )

    async_add_devices(entities)


class NestProtectSelect(NestDescriptiveEntity, SelectEntity):
    """Representation of an adjustable Nest Protect setting (like Pathlight brightness)."""

    entity_description: NestProtectSelectDescription

    @property
    def current_option(self) -> str | None:
        """Return the current preset (low/medium/high) for this device setting."""
        raw_value = self.bucket.value.get(self.entity_description.key)
        if raw_value is None:
            return None
        return BRIGHTNESS_TO_PRESET.get(raw_value)

    @property
    def options(self) -> list[str]:
        """Return allowed options (low/medium/high)."""
        return self.entity_description.options

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting a new preset option."""
        new_value = PRESET_TO_BRIGHTNESS.get(option)

        if new_value is None:
            LOGGER.warning(
                "Unbekannte Option %s für %s",
                option,
                self.entity_description.key,
            )
            return

        if self.client is None or not hasattr(self.client, "nest_session"):
            LOGGER.warning(
                "Kann %s nicht setzen (kein aktiver Nest-Client / restricted mode).",
                self.entity_description.key,
            )
            return

        objects = [
            {
                "object_key": self.bucket.object_key,
                "op": "MERGE",
                "value": {
                    self.entity_description.key: new_value,
                },
            }
        ]

        await self.client.ensure_authenticated(self.client.nest_session.access_token)

        transport_url = (
            self.client.transport_url
            or self.client.nest_session.urls.transport_url
        )

        result = await self.client.update_objects(
            self.client.nest_session.access_token,
            self.client.nest_session.userid,
            transport_url,
            objects,
        )

        LOGGER.debug(
            "NestProtectSelect updated %s -> %s (%s) result=%s",
            self.entity_description.key,
            option,
            new_value,
            result,
        )
