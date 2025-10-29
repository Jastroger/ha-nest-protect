"""Tests for NestClient."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.nest_protect.pynest.client import NestClient
from custom_components.nest_protect.pynest.const import NEST_REQUEST


class DummyResponse:
    """Minimal response stub for testing."""

    def __init__(self, payload):
        self._payload = payload
        self.status = 200
        self.content_type = "application/json"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class DummySession:
    """Minimal session stub for NestClient tests."""

    def __init__(self, payload=None):
        self._payload = payload

    async def close(self) -> None:
        return None

    def post(self, *args, **kwargs):
        return DummyResponse(self._payload)


async def test_ensure_authenticated_fetches_session():
    """Ensure authenticate is called when no session is cached."""

    async with NestClient(session=DummySession()) as nest_client:
        nest_session = SimpleNamespace(
            access_token="nest",
            userid="user",
            email="user@example.com",
            user="user.1",
            is_expired=lambda: False,
        )

        with patch.object(
            NestClient, "authenticate", AsyncMock(return_value=nest_session)
        ) as authenticate:
            result = await nest_client.ensure_authenticated("token")

    authenticate.assert_awaited_once_with("token")
    assert result is nest_session


async def test_ensure_authenticated_reuses_session():
    """Ensure cached sessions are reused when still valid."""

    async with NestClient(session=DummySession()) as nest_client:
        existing_session = SimpleNamespace(
            access_token="existing",
            userid="user",
            email="user@example.com",
            user="user.1",
            is_expired=lambda: False,
        )
        nest_client.nest_session = existing_session

        with patch.object(NestClient, "authenticate", AsyncMock()) as authenticate:
            result = await nest_client.ensure_authenticated("token")

    authenticate.assert_not_called()
    assert result is existing_session


async def test_get_first_data_success():
    """Test getting initial data from the API."""

    payload = {
        "updated_buckets": [
            {
                "object_key": "topaz.example-object-key",
                "object_revision": 1,
                "object_timestamp": 1,
                "value": {},
            }
        ],
        "service_urls": {
            "urls": {
                "rubyapi_url": "https://home.nest.com/",
                "czfe_url": "https://xxxx.transport.home.nest.com",
                "log_upload_url": "https://logsink.home.nest.com/upload/user",
                "transport_url": "https://xxxx.transport.home.nest.com",
                "weather_url": "https://apps-weather.nest.com/weather/v1?query=",
                "support_url": "https://nest.secure.force.com/support/webapp?",
                "direct_transport_url": "https://xxx.transport.home.nest.com:443",
            },
            "limits": {
                "thermostats_per_structure": 20,
                "structures": 5,
                "smoke_detectors_per_structure": 18,
                "smoke_detectors": 54,
                "thermostats": 60,
            },
            "weave": {
                "service_config": "xxxx",
                "pairing_token": "xxxx",
                "access_token": "xxxx",
            },
        },
        "weather_for_structures": {},
        "_2fa_enabled": False,
    }

    nest_client = NestClient(session=DummySession(payload))
    with patch(
        "custom_components.nest_protect.pynest.client.APP_LAUNCH_URL_FORMAT",
        "/api/0.1/user/{user_id}/app_launch",
    ):
        result = await nest_client.get_first_data("access-token", "example-user")

    assert result.service_urls["urls"]["transport_url"] == "https://xxxx.transport.home.nest.com"
    assert result.updated_buckets[0].object_key == "topaz.example-object-key"
    assert NEST_REQUEST["known_bucket_types"]  # Ensure constant imported
