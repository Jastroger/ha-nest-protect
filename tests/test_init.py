"""Test init."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nest_protect import async_migrate_entry
from custom_components.nest_protect.const import CONF_ACCOUNT_TYPE, DOMAIN
from custom_components.nest_protect.oauth import implementation_domain
from custom_components.nest_protect.pynest.enums import Environment

from .conftest import ComponentSetup


class DummySession:
    async def close(self) -> None:
        return None


async def test_init_with_oauth(
    hass,
    component_setup: ComponentSetup,
    config_entry: MockConfigEntry,
):
    """Test successful initialization using OAuth credentials."""

    fake_oauth = SimpleNamespace(async_get_access_token=AsyncMock(return_value="access"))
    nest_session = SimpleNamespace(
        access_token="nest-access",
        userid="user-id",
        email="user@example.com",
        user="user.1234",
    )
    first_data = SimpleNamespace(
        updated_buckets=[],
        service_urls={"urls": {"transport_url": "https://transport"}},
    )

    with patch(
        "custom_components.nest_protect.async_get_nest_oauth_session",
        return_value=fake_oauth,
    ), patch(
        "custom_components.nest_protect.async_create_clientsession",
        return_value=DummySession(),
    ), patch(
        "custom_components.nest_protect.NestClient.ensure_authenticated",
        AsyncMock(return_value=nest_session),
    ), patch(
        "custom_components.nest_protect.NestClient.get_first_data",
        AsyncMock(return_value=first_data),
    ), patch("custom_components.nest_protect._register_subscribe_task"):
        await component_setup()

    assert config_entry.state is ConfigEntryState.LOADED


async def test_access_token_failure(
    hass,
    component_setup: ComponentSetup,
    config_entry: MockConfigEntry,
):
    """Test failure when retrieving an access token."""

    fake_oauth = SimpleNamespace(
        async_get_access_token=AsyncMock(side_effect=ConfigEntryAuthFailed())
    )

    with patch(
        "custom_components.nest_protect.async_get_nest_oauth_session",
        return_value=fake_oauth,
    ), patch(
        "custom_components.nest_protect.async_create_clientsession",
        return_value=DummySession(),
    ):
        await component_setup()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_authenticate_failure(
    hass,
    component_setup: ComponentSetup,
    config_entry: MockConfigEntry,
):
    """Test failure when authenticating with Nest."""

    fake_oauth = SimpleNamespace(async_get_access_token=AsyncMock(return_value="token"))

    with patch(
        "custom_components.nest_protect.async_get_nest_oauth_session",
        return_value=fake_oauth,
    ), patch(
        "custom_components.nest_protect.async_create_clientsession",
        return_value=DummySession(),
    ), patch(
        "custom_components.nest_protect.NestClient.ensure_authenticated",
        AsyncMock(side_effect=ClientError()),
    ):
        await component_setup()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_migrate_entry_with_refresh_token(hass):
    """Ensure legacy entries with refresh tokens migrate to OAuth format."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ACCOUNT_TYPE: Environment.PRODUCTION, "refresh_token": "refresh"},
        version=3,
    )
    entry.add_to_hass(hass)
    migrated_token = {
        "access_token": "token",
        "refresh_token": "refresh",
        "token_type": "Bearer",
        "scope": "scope",
        "id_token": "id",  # optional
        "expires_in": 60,
        "expires_at": 123,
    }

    with patch(
        "custom_components.nest_protect.async_ensure_oauth_implementation",
        AsyncMock(),
    ), patch(
        "custom_components.nest_protect.async_token_from_refresh_token",
        AsyncMock(return_value=migrated_token),
    ):
        assert await async_migrate_entry(hass, entry)

    assert entry.version == 4
    assert entry.data["token"] == migrated_token
    assert (
        entry.data["auth_implementation"]
        == implementation_domain(Environment.PRODUCTION)
    )


async def test_migrate_entry_without_refresh_token(hass):
    """Ensure entries without refresh tokens migrate and trigger reauth."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ACCOUNT_TYPE: Environment.FIELDTEST},
        version=3,
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.nest_protect.async_ensure_oauth_implementation",
        AsyncMock(),
    ):
        assert await async_migrate_entry(hass, entry)

    assert entry.version == 4
    token = entry.data["token"]
    assert token["access_token"] == ""
    assert token["refresh_token"] == ""
    assert entry.data["auth_implementation"] == implementation_domain(
        Environment.FIELDTEST
    )
