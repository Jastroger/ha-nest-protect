"""Test init."""

import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nest_protect import _is_access_token_valid

from .conftest import ComponentSetup


def _mock_auth_response() -> SimpleNamespace:
    """Return a fake Google auth response."""
    return SimpleNamespace(
        access_token="google-access-token",
        expiry_date=datetime.datetime.now() + datetime.timedelta(hours=1),
    )


def _mock_nest_response() -> SimpleNamespace:
    """Return a fake Nest auth response."""
    return SimpleNamespace(
        access_token="nest-access-token",
        userid="user-id",
        user="user-id",
    )


def _mock_first_data_response() -> SimpleNamespace:
    """Return a fake first data response."""
    return SimpleNamespace(
        updated_buckets=[],
        service_urls={"urls": {"transport_url": "https://transport.example.test"}},
    )


async def _subscription_waiter(*_args, **_kwargs) -> None:
    """Keep the subscription task alive until it is cancelled."""
    await asyncio.Event().wait()


async def test_init_with_refresh_token(
    hass,
    component_setup_with_refresh_token: ComponentSetup,
    config_entry_with_refresh_token: MockConfigEntry,
):
    """Test initialization."""
    with patch(
        "custom_components.nest_protect.NestClient.get_access_token_from_refresh_token",
        return_value=_mock_auth_response(),
    ), patch(
        "custom_components.nest_protect.NestClient.authenticate",
        return_value=_mock_nest_response(),
    ), patch(
        "custom_components.nest_protect.NestClient.get_first_data",
        return_value=_mock_first_data_response(),
    ), patch(
        "custom_components.nest_protect._async_subscribe_once",
        side_effect=_subscription_waiter,
    ):
        await component_setup_with_refresh_token()

    assert config_entry_with_refresh_token.state is ConfigEntryState.LOADED


async def test_access_token_failure_with_refresh_token(
    hass,
    component_setup_with_refresh_token: ComponentSetup,
    config_entry_with_refresh_token: MockConfigEntry,
):
    """Test failure when getting an access token."""
    with patch(
        "custom_components.nest_protect.NestClient.get_access_token_from_refresh_token",
        side_effect=aiohttp.ClientError(),
    ):
        await component_setup_with_refresh_token()

    assert config_entry_with_refresh_token.state is ConfigEntryState.SETUP_RETRY


async def test_authenticate_failure_with_refresh_token(
    hass,
    component_setup_with_refresh_token: ComponentSetup,
    config_entry_with_refresh_token: MockConfigEntry,
):
    """Test failure when authenticating."""
    with patch(
        "custom_components.nest_protect.NestClient.get_access_token_from_refresh_token"
    ), patch(
        "custom_components.nest_protect.NestClient.authenticate",
        side_effect=aiohttp.ClientError(),
    ):
        await component_setup_with_refresh_token()

    assert config_entry_with_refresh_token.state is ConfigEntryState.SETUP_RETRY


async def test_init_with_cookies(
    hass,
    component_setup_with_cookies: ComponentSetup,
    config_entry_with_cookies: MockConfigEntry,
):
    """Test initialization."""
    with patch(
        "custom_components.nest_protect.NestClient.get_access_token_from_cookies",
        return_value=_mock_auth_response(),
    ), patch(
        "custom_components.nest_protect.NestClient.authenticate",
        return_value=_mock_nest_response(),
    ), patch(
        "custom_components.nest_protect.NestClient.get_first_data",
        return_value=_mock_first_data_response(),
    ), patch(
        "custom_components.nest_protect._async_subscribe_once",
        side_effect=_subscription_waiter,
    ):
        await component_setup_with_cookies()

    assert config_entry_with_cookies.state is ConfigEntryState.LOADED


async def test_access_token_failure_with_cookies(
    hass,
    component_setup_with_cookies: ComponentSetup,
    config_entry_with_cookies: MockConfigEntry,
):
    """Test failure when getting an access token."""
    with patch(
        "custom_components.nest_protect.NestClient.get_access_token_from_cookies",
        side_effect=aiohttp.ClientError(),
    ):
        await component_setup_with_cookies()

    assert config_entry_with_cookies.state is ConfigEntryState.SETUP_RETRY


async def test_authenticate_failure_with_cookies(
    hass,
    component_setup_with_cookies: ComponentSetup,
    config_entry_with_cookies: MockConfigEntry,
):
    """Test failure when authenticating."""
    with patch(
        "custom_components.nest_protect.NestClient.get_access_token_from_cookies"
    ), patch(
        "custom_components.nest_protect.NestClient.authenticate",
        side_effect=aiohttp.ClientError(),
    ):
        await component_setup_with_cookies()

    assert config_entry_with_cookies.state is ConfigEntryState.SETUP_RETRY


def test_is_access_token_valid_has_safety_margin():
    """Test access token validity requires a two-minute safety margin."""
    assert not _is_access_token_valid(
        datetime.datetime.now() + datetime.timedelta(seconds=90)
    )
    assert _is_access_token_valid(
        datetime.datetime.now() + datetime.timedelta(minutes=5)
    )
