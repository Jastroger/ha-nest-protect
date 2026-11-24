"""Verify the auth flow text as Home Assistant loads it."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.nest_protect.const import DOMAIN


@pytest.mark.parametrize("language", ["en", "de", "fr", "nl", "pt-BR"])
async def test_setup_translations(hass: HomeAssistant, language: str) -> None:
    """Every supported language has the setup text and options."""
    paths = (
        "step.user.title",
        "step.user.description",
        "step.user.data.account_type",
        "step.auth_method.title",
        "step.auth_method.menu_options.auth_bridge",
        "step.auth_method.menu_options.extension",
        "step.auth_method.menu_options.account_link",
        "step.auth_method.menu_option_descriptions.auth_bridge",
        "step.auth_method.menu_option_descriptions.extension",
        "step.auth_method.menu_option_descriptions.account_link",
        "step.auth_bridge.title",
        "step.auth_bridge.menu_options.auth_bridge_addon",
        "step.auth_bridge.menu_options.auth_bridge_standalone",
        "step.auth_bridge.menu_option_descriptions.auth_bridge_addon",
        "step.auth_bridge.menu_option_descriptions.auth_bridge_standalone",
        "step.auth_bridge_standalone.data.bridge_url",
        "step.auth_bridge_standalone.data_description.bridge_url",
        "step.auth_bridge_login.description",
        "step.auth_bridge_finish.title",
        "step.auth_bridge_finish.description",
        "step.extension.description",
        "step.extension.data.auth_code",
        "step.account_link.description",
        "step.account_link.data.issue_token",
        "step.account_link.data.cookies",
        "abort.already_configured",
        "abort.wrong_account",
        "error.cannot_connect",
        "error.invalid_auth",
        "error.invalid_issue_token",
        "error.invalid_cookies",
        "error.invalid_code",
        "error.invalid_auth_bridge_url",
        "error.unknown",
    )
    translations = await async_get_translations(
        hass, language, "config", integrations=[DOMAIN]
    )
    for path in paths:
        assert translations[f"component.{DOMAIN}.config.{path}"].strip()

    selectors = await async_get_translations(
        hass, language, "selector", integrations=[DOMAIN]
    )
    for value in ("production", "fieldtest"):
        assert selectors[
            f"component.{DOMAIN}.selector.account_type.options.{value}"
        ].strip()
