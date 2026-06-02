"""Tests for auth bridge session helpers."""

from types import SimpleNamespace

from custom_components.nest_protect.auth_bridge import (
    complete_auth_bridge_session,
    create_auth_bridge_session,
    get_auth_bridge_store,
)
from custom_components.nest_protect.const import CONF_COOKIES, CONF_ISSUE_TOKEN


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

    assert not complete_auth_bridge_session(
        hass,
        session.session_id,
        "wrong-secret",
        {
            CONF_ISSUE_TOKEN: "issue-token",
            CONF_COOKIES: "cookies",
        },
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

    assert complete_auth_bridge_session(
        hass,
        session.session_id,
        session.secret,
        payload,
    )
    assert session.result == payload
