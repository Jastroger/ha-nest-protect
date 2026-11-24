"""Verify the auth flow text as Home Assistant loads it."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.nest_protect.const import DOMAIN


@pytest.mark.parametrize("language", ["en", "de", "fr", "nl", "pt-BR"])
async def test_auth_bridge_translations(hass: HomeAssistant, language: str) -> None:
    """Every supported language has the mobile flow text and options."""
    categories = {
        "config": (
            "step.auth_method.description",
            "step.auth_method.data.method",
            "step.auth_bridge.title",
            "step.auth_bridge.menu_options.auth_bridge_addon",
            "step.auth_bridge.menu_options.auth_bridge_standalone",
            "step.auth_bridge.menu_option_descriptions.auth_bridge_addon",
            "step.auth_bridge.menu_option_descriptions.auth_bridge_standalone",
            "step.auth_bridge_standalone.data.bridge_url",
            "step.auth_bridge_standalone.data_description.bridge_url",
            "step.auth_bridge_login.description",
            "step.auth_bridge_finish.title",
            "error.invalid_auth_bridge_url",
        ),
        "selector": (
            "auth_method.options.bridge",
            "auth_method.options.extension",
            "auth_method.options.manual",
        ),
    }
    for category, paths in categories.items():
        translations = await async_get_translations(
            hass, language, category, integrations=[DOMAIN]
        )
        for path in paths:
            assert translations[f"component.{DOMAIN}.{category}.{path}"].strip()
