"""Switch platform for Nest Protect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.helpers.entity import EntityCategory

from . import HomeAssistantNestProtectData
from .const import DOMAIN, LOGGER
from .entity import NestDescriptiveEntity


@dataclass
class NestProtectSwitchDescriptionMixin:
    """Extra description data for Nest Protect switches."""


@dataclass
class NestProtectSwitchDescription(
    SwitchEntityDescription, NestProtectSwitchDescriptionMixin
):
    """Description of a Nest Protect switch entity."""


# Diese sind die konfigurierbaren Flags am Protect (Pathlight, Heads-Up usw.)
SWITCH_DESCRIPTIONS: list[NestProtectSwitchDescription] = [
    NestProtectSwitchDescription(
        key="night_light_enable",
        name="Pathlight",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-night",
    ),
    NestProtectSwitchDescription(
        key="ntp_green_led_enable",
        name="Nightly Promise",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:led-off",
    ),
    NestProtectSwitchDescription(
        key="heads_up_enable",
        name="Heads-Up",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:exclamation-thick",
    ),
    NestProtectSwitchDescription(
        key="steam_detection_enable",
        name="Steam Check",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:pot-steam",
    ),
]


async def async_setup_entry(hass, entry, async_add_devices):
    """Set up the Nest Protect switches from a config entry."""
    data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]

    # Wichtigster Fix: devices kann None sein (restricted mode). Dann bauen wir einfach nichts.
    device_map = data.devices or {}
    entities: list[NestProtectSwitch] = []

    # Map {config_key: entity_description}
    SUPPORTED_KEYS: dict[str, NestProtectSwitchDescription] = {
        description.key: description for description in SWITCH_DESCRIPTIONS
    }

    # device_map soll ein dict {object_key -> Bucket} sein
    for device in device_map.values():
        # device.value ist das Dict mit den Flags (night_light_enable etc.)
        for key in getattr(device, "value", {}):
            if description := SUPPORTED_KEYS.get(key):
                entities.append(
                    NestProtectSwitch(device, description, data.areas, data.client)
                )

    if not entities:
        LOGGER.debug(
            "nest_protect.switch: keine Entities erzeugt. "
            "restricted=%s reason=%s devices_present=%s",
            getattr(data, "restricted", False),
            getattr(data, "restricted_reason", None),
            bool(device_map),
        )

    async_add_devices(entities)


class NestProtectSwitch(NestDescriptiveEntity, SwitchEntity):
    """Representation of a Nest Protect switch entity (Pathlight, Heads-Up, etc.)."""

    entity_description: NestProtectSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return True if the feature is enabled."""
        return self.bucket.value.get(self.entity_description.key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the feature."""
        await self._async_send_update(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the feature."""
        await self._async_send_update(False)

    async def _async_send_update(self, new_state: bool) -> None:
        """Send update to Nest backend for this setting."""
        # Wenn wir im restricted mode sind, client kann evtl. nicht authentifizieren.
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
                    self.entity_description.key: new_state,
                },
            }
        ]

        # Stelle sicher, dass das Session-Token noch gültig ist
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
            "NestProtectSwitch updated %s -> %s result=%s",
            self.entity_description.key,
            new_state,
            result,
        )
