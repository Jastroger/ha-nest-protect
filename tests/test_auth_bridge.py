"""Tests for auth bridge session helpers."""

import datetime
import json
from types import SimpleNamespace

import pytest

from custom_components.nest_protect.auth_bridge import (
    NestProtectAuthBridgeView,
    cleanup_expired_auth_bridge_sessions,
    complete_auth_bridge_session,
    create_auth_bridge_session,
    get_auth_bridge_store,
)
from custom_components.nest_protect.const import CONF_COOKIES, CONF_ISSUE_TOKEN

VALID_ISSUE_TOKEN = (
    "https://accounts.google.com/o/oauth2/iframerpc?"
    "action=issueToken&response_type=token"
)
VALID_COOKIES = (
    "SID=example-session; HSID=example-hsid; SSID=example-ssid; "
    "APISID=example-apisid; SAPISID=example-sapisid; "
    "ACCOUNT_CHOOSER=example; NID=example; CONSENT=YES+example"
)


class MockRequest:
    """Mock request object."""

    def __init__(self, hass, payload):
        self.app = {"hass": hass}
        self._payload = payload

    async def json(self):
        """Return payload JSON."""
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_create_auth_bridge_session_stores_session():
    """Test auth bridge session creation."""
    hass = SimpleNamespace(data={})

    session = create_auth_bridge_session(hass)

    assert session.session_id
    assert session.secret
    assert get_auth_bridge_store(hass)[session.session_id] is session


def test_complete_auth_bridge_session_rejects_wrong_secret():
    """Test auth bridge secret verification."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)

    assert (
        complete_auth_bridge_session(
            hass,
            session.session_id,
            "wrong-secret",
            {
                CONF_ISSUE_TOKEN: "issue-token",
                CONF_COOKIES: "cookies",
            },
        )
        == "invalid_session"
    )
    assert session.result is None


def test_complete_auth_bridge_session_stores_payload():
    """Test successful auth bridge completion."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    payload = {
        CONF_ISSUE_TOKEN: "issue-token",
        CONF_COOKIES: "cookies",
    }

    assert (
        complete_auth_bridge_session(
            hass,
            session.session_id,
            session.secret,
            payload,
        )
        == "ok"
    )
    assert session.result == payload


def test_complete_auth_bridge_session_is_one_time_use():
    """Test successful callback cannot be overwritten."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    payload = {
        CONF_ISSUE_TOKEN: "issue-token",
        CONF_COOKIES: "cookies",
    }

    assert (
        complete_auth_bridge_session(
            hass,
            session.session_id,
            session.secret,
            payload,
        )
        == "ok"
    )
    assert (
        complete_auth_bridge_session(
            hass,
            session.session_id,
            session.secret,
            {
                CONF_ISSUE_TOKEN: "issue-token-2",
                CONF_COOKIES: "cookies-2",
            },
        )
        == "already_completed"
    )
    assert session.result == payload


def test_auth_bridge_session_expiry_cleanup():
    """Test expired auth bridge sessions are cleaned up."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass, ttl=datetime.timedelta(seconds=-1))

    cleanup_expired_auth_bridge_sessions(hass)
    assert session.session_id not in get_auth_bridge_store(hass)


async def test_auth_bridge_callback_wrong_secret():
    """Test auth bridge callback rejects wrong secret."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    response = await NestProtectAuthBridgeView().post(
        MockRequest(
            hass,
            {
                "secret": "wrong",
                CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
                CONF_COOKIES: VALID_COOKIES,
            },
        ),
        session.session_id,
    )

    assert response.status == 403
    assert json.loads(response.text) == {"error": "invalid_session"}


async def test_auth_bridge_callback_missing_fields():
    """Test auth bridge callback rejects missing fields."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    response = await NestProtectAuthBridgeView().post(
        MockRequest(
            hass, {"secret": session.secret, CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN}
        ),
        session.session_id,
    )

    assert response.status == 400
    assert json.loads(response.text) == {"error": "missing_fields"}


async def test_auth_bridge_callback_invalid_issue_token():
    """Test auth bridge callback rejects invalid issue token."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    response = await NestProtectAuthBridgeView().post(
        MockRequest(
            hass,
            {
                "secret": session.secret,
                CONF_ISSUE_TOKEN: "https://example.com/not-issue-token",
                CONF_COOKIES: VALID_COOKIES,
            },
        ),
        session.session_id,
    )

    assert response.status == 400
    assert json.loads(response.text) == {"error": "invalid_issue_token"}


async def test_auth_bridge_callback_invalid_cookies():
    """Test auth bridge callback rejects invalid cookies."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    response = await NestProtectAuthBridgeView().post(
        MockRequest(
            hass,
            {
                "secret": session.secret,
                CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
                CONF_COOKIES: "SID=short",
            },
        ),
        session.session_id,
    )

    assert response.status == 400
    assert json.loads(response.text) == {"error": "invalid_cookie_header"}


async def test_auth_bridge_callback_success():
    """Test auth bridge callback accepts valid payload."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    response = await NestProtectAuthBridgeView().post(
        MockRequest(
            hass,
            {
                "secret": session.secret,
                CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
                CONF_COOKIES: VALID_COOKIES,
            },
        ),
        session.session_id,
    )

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True}
    assert session.result == {
        CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
        CONF_COOKIES: VALID_COOKIES,
    }


async def test_auth_bridge_callback_second_post_rejected():
    """Test auth bridge callback only allows one successful post."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    view = NestProtectAuthBridgeView()
    first_response = await view.post(
        MockRequest(
            hass,
            {
                "secret": session.secret,
                CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
                CONF_COOKIES: VALID_COOKIES,
            },
        ),
        session.session_id,
    )
    second_response = await view.post(
        MockRequest(
            hass,
            {
                "secret": session.secret,
                CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
                CONF_COOKIES: VALID_COOKIES,
            },
        ),
        session.session_id,
    )

    assert first_response.status == 200
    assert second_response.status == 409
    assert json.loads(second_response.text) == {"error": "already_completed"}


async def test_auth_bridge_callback_rejects_expired_session():
    """Test auth bridge callback rejects expired sessions."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass, ttl=datetime.timedelta(seconds=-1))
    response = await NestProtectAuthBridgeView().post(
        MockRequest(
            hass,
            {
                "secret": session.secret,
                CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
                CONF_COOKIES: VALID_COOKIES,
            },
        ),
        session.session_id,
    )

    assert response.status == 410
    assert json.loads(response.text) == {"error": "expired_session"}


async def test_auth_bridge_callback_invalid_json():
    """Test auth bridge callback rejects invalid JSON."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass)
    response = await NestProtectAuthBridgeView().post(
        MockRequest(hass, ValueError("bad json")),
        session.session_id,
    )

    assert response.status == 400
    assert json.loads(response.text) == {"error": "invalid_json"}


def test_complete_auth_bridge_session_rejects_expired():
    """Test expired session completion is rejected."""
    hass = SimpleNamespace(data={})
    session = create_auth_bridge_session(hass, ttl=datetime.timedelta(seconds=-1))

    assert (
        complete_auth_bridge_session(
            hass,
            session.session_id,
            session.secret,
            {
                CONF_ISSUE_TOKEN: "issue-token",
                CONF_COOKIES: "cookies",
            },
        )
        == "expired_session"
    )


async def test_addon_menu_option_opens_ingress(hass):
    """The Home Assistant app option opens the bridge through ingress."""
    from urllib.parse import parse_qs, urlsplit

    from homeassistant.data_entry_flow import FlowResultType
    from homeassistant.setup import async_setup_component

    from custom_components.nest_protect.const import DOMAIN

    assert await async_setup_component(hass, "http", {})
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = result["flow_id"]
    await flow.async_configure(flow_id, {"account_type": "production"})
    await flow.async_configure(flow_id, {"method": "bridge"})

    result = await flow.async_configure(flow_id, {"next_step_id": "auth_bridge_addon"})
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth_bridge_login"

    url = urlsplit(result["url"])
    assert url.path == "/hassio/ingress/nest_protect_auth_bridge/"
    query = parse_qs(url.query)
    session_id = query["session_id"][0]
    assert query["callback_url"] == [
        f"http://supervisor/core/api/nest_protect/auth_bridge/{session_id}"
    ]


@pytest.mark.parametrize("foreground", [True, False])
async def test_mobile_bridge_flow_uses_native_link_and_waits_for_callback(
    hass, hass_client_no_auth, foreground
):
    """A clean install opens the bridge and advances only after a valid callback."""
    from unittest.mock import patch
    from urllib.parse import parse_qs, urlsplit

    from homeassistant.data_entry_flow import FlowResultType
    from homeassistant.setup import async_setup_component

    from custom_components.nest_protect.config_flow import ConfigFlow
    from custom_components.nest_protect.const import DOMAIN

    assert await async_setup_component(hass, "http", {})
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = result["flow_id"]
    result = await flow.async_configure(flow_id, {"account_type": "production"})
    assert result["type"] is FlowResultType.FORM

    result = await flow.async_configure(flow_id, {"method": "bridge"})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["auth_bridge_addon", "auth_bridge_standalone"]

    result = await flow.async_configure(
        flow_id, {"next_step_id": "auth_bridge_standalone"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "auth_bridge_standalone"

    result = await flow.async_configure(flow_id, {"bridge_url": "not-an-address"})
    assert result["errors"] == {"bridge_url": "invalid_auth_bridge_url"}
    result = await flow.async_configure(
        flow_id, {"bridge_url": "http://bridge.example.test:8099/"}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    url = urlsplit(result["url"])
    assert (url.scheme, url.netloc, url.path) == (
        "http",
        "bridge.example.test:8099",
        "/",
    )
    launch = parse_qs(url.query)
    callback = f"/api/nest_protect/auth_bridge/{launch['session_id'][0]}"
    client = await hass_client_no_auth()
    payload = {
        CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN,
        CONF_COOKIES: VALID_COOKIES,
    }
    response = await client.post(callback, json={**payload, "secret": "wrong"})
    assert response.status == 403
    pending = await flow.async_configure(flow_id)
    assert pending["type"] is FlowResultType.EXTERNAL_STEP
    assert pending["url"] == result["url"]

    with (
        patch("custom_components.nest_protect.auth_bridge.async_call_later") as timer,
        patch.object(
            ConfigFlow,
            "async_validate_input",
            return_value=[VALID_ISSUE_TOKEN, VALID_COOKIES, "nest@example.test"],
        ) as validate,
    ):
        response = await client.post(
            callback, json={**payload, "secret": launch["secret"][0]}
        )
        assert response.status == 200
        timer.assert_called_once()
        finish_if_pending = timer.call_args.args[2]
        if foreground:
            result = await flow.async_configure(flow_id)
            assert result["type"] is FlowResultType.CREATE_ENTRY

        await finish_if_pending(datetime.datetime.now(tz=datetime.UTC))
        validate.assert_awaited_once()
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert entry.data[CONF_COOKIES] == VALID_COOKIES
