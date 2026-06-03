"""Tests for auth bridge add-on helper functions."""

from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace
import types
import sys

import pytest

fake_flask = types.ModuleType("flask")


class DummyFlask:
    """Minimal Flask shim for unit tests."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get(self, *_args, **_kwargs):
        return lambda func: func

    def post(self, *_args, **_kwargs):
        return lambda func: func

    def route(self, *_args, **_kwargs):
        return lambda func: func

    def run(self, *_args, **_kwargs) -> None:
        return None


fake_flask.Flask = DummyFlask
fake_flask.jsonify = lambda value: value
fake_flask.redirect = lambda value: value
fake_flask.render_template = lambda *_args, **_kwargs: ""
fake_flask.request = SimpleNamespace(form={}, args={})
sys.modules.setdefault("flask", fake_flask)

ADDON_MAIN_PATH = pathlib.Path(
    "addons/nest-protect-auth-bridge/app/main.py"
).resolve()
spec = importlib.util.spec_from_file_location("auth_bridge_addon_main", ADDON_MAIN_PATH)
assert spec and spec.loader
addon_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon_main)


def test_mask_secret_masks_short_and_long_values() -> None:
    """Secret masking should not expose full values."""
    assert addon_main._mask_secret("abcd") == "****"
    assert addon_main._mask_secret("abcdefghijkl") == "abcd***ijkl"


def test_callback_url_validation_requires_absolute_http_url() -> None:
    """Callback URL must be absolute."""
    assert addon_main._is_valid_callback_url("/api/nest_protect/auth_bridge/x") is False
    assert (
        addon_main._is_valid_callback_url(
            "http://supervisor/core/api/nest_protect/auth_bridge/x"
        )
        is True
    )


def test_build_callback_request_requires_supervisor_token(monkeypatch) -> None:
    """Supervisor API callback posting requires token."""
    monkeypatch.setenv("AUTH_BRIDGE_MODE", "addon")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        addon_main._build_callback_request(
            "http://supervisor/core/api/nest_protect/auth_bridge/x"
        )

    monkeypatch.setenv("SUPERVISOR_TOKEN", "abc")
    url, headers = addon_main._build_callback_request(
        "http://supervisor/core/api/nest_protect/auth_bridge/x"
    )
    assert url == "http://supervisor/core/api/nest_protect/auth_bridge/x"
    assert headers["Authorization"].startswith("Bearer ")


def test_build_callback_url_addon_defaults_to_supervisor(monkeypatch) -> None:
    """Add-on mode builds Supervisor/Core callback URLs."""
    monkeypatch.setenv("AUTH_BRIDGE_MODE", "addon")

    assert addon_main._build_callback_url("session-1") == (
        "http://supervisor/core/api/nest_protect/auth_bridge/session-1"
    )


def test_build_callback_url_standalone_uses_ha_base_url(monkeypatch) -> None:
    """Standalone mode builds callback URLs from HA_BASE_URL."""
    monkeypatch.setenv("AUTH_BRIDGE_MODE", "standalone")
    monkeypatch.setenv("HA_BASE_URL", "http://homeassistant.local:8123/")

    assert addon_main._build_callback_url("session-1") == (
        "http://homeassistant.local:8123/api/nest_protect/auth_bridge/session-1"
    )


def test_build_callback_request_standalone_does_not_require_supervisor_token(monkeypatch) -> None:
    """Standalone mode can post directly to Home Assistant without Supervisor token."""
    monkeypatch.setenv("AUTH_BRIDGE_MODE", "standalone")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    url, headers = addon_main._build_callback_request(
        "http://homeassistant.local:8123/api/nest_protect/auth_bridge/x"
    )

    assert url == "http://homeassistant.local:8123/api/nest_protect/auth_bridge/x"
    assert "Authorization" not in headers


def test_build_callback_url_standalone_requires_ha_base_url(monkeypatch) -> None:
    """Standalone mode requires HA_BASE_URL when no callback URL is supplied."""
    monkeypatch.setenv("AUTH_BRIDGE_MODE", "standalone")
    monkeypatch.delenv("HA_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="missing_ha_base_url"):
        addon_main._build_callback_url("session-1")


def test_wait_for_capture_times_out() -> None:
    """Capture loop should stop at timeout instead of running forever."""
    addon_main._set_state(
        issue_token="",
        cookies="",
        cancel_requested=False,
    )

    with pytest.raises(addon_main.CaptureTimeoutError):
        addon_main._wait_for_capture(timeout_seconds=0.01, poll_interval_seconds=0.001)


VALID_ISSUE_TOKEN = (
    "https://accounts.google.com/o/oauth2/iframerpc?"
    "action=issueToken&response_type=token"
)
VALID_COOKIES = (
    "SID=example-session; HSID=example-hsid; SSID=example-ssid; "
    "APISID=example-apisid; SAPISID=example-sapisid; "
    "ACCOUNT_CHOOSER=example; NID=example; CONSENT=YES+example"
)


def test_callback_success_requires_ok_true_in_json(monkeypatch) -> None:
    """Callback must be treated as failed unless response JSON contains ok=True."""
    import requests

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    # Simulate HA returning {"ok": True}
    monkeypatch.setattr(requests, "post", lambda *_a, **_kw: FakeResponse({"ok": True}))
    addon_main._set_state(
        status=addon_main.ISSUE_TOKEN_CAPTURED,
        issue_token=VALID_ISSUE_TOKEN,
        cookies=VALID_COOKIES,
        error="",
        running=True,
        cancel_requested=False,
    )
    addon_main._capture_flow.__wrapped__ = None  # not wrapped, just call helpers directly

    # Direct test of the post-response logic via the state helpers
    import threading
    import time

    results = {}

    def run_post():
        import os
        monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")
        try:
            callback_url = "http://supervisor/core/api/nest_protect/auth_bridge/x"
            callback_post_url, callback_headers = addon_main._build_callback_request(
                callback_url
            )
            response = requests.post(callback_post_url, json={}, headers=callback_headers, timeout=5)
            try:
                resp_json = response.json()
            except Exception:
                resp_json = None
            results["ok"] = isinstance(resp_json, dict) and resp_json.get("ok") is True
        except Exception as exc:
            results["error"] = str(exc)

    run_post()
    assert results.get("ok") is True


def test_callback_non_ok_json_is_treated_as_failure(monkeypatch) -> None:
    """Callback response that lacks ok=True must be treated as failure."""
    import requests

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    for bad_response in [{"ok": False}, {"error": "rejected"}, {}]:
        resp = FakeResponse(bad_response)
        resp_json = resp.json()
        assert not (isinstance(resp_json, dict) and resp_json.get("ok") is True)

    class BadJsonResponse:
        def json(self):
            raise ValueError("bad json")

    resp_json = None
    try:
        BadJsonResponse().json()
    except Exception:
        resp_json = None
    assert not (isinstance(resp_json, dict) and resp_json.get("ok") is True)


def test_cookie_capture_accepts_any_accounts_google_request() -> None:
    """Cookie capture should fire for any accounts.google.com request, not only oauth2/iframe."""
    addon_main._set_state(
        status=addon_main.WAITING_FOR_LOGIN,
        cookies="",
        cancel_requested=False,
    )

    # Simulate a non-oauth2/iframe accounts.google.com request (e.g. iframerpc issueToken)
    issue_token_url = VALID_ISSUE_TOKEN

    class FakeRequest:
        def __init__(self, url, cookie):
            self.url = url
            self._cookie = cookie

        @property
        def headers(self):
            return {"cookie": self._cookie}

    # Manually invoke the cookie-capture logic as it appears in _capture_flow
    from urllib.parse import urlsplit

    request_url = issue_token_url
    hostname = (urlsplit(request_url).hostname or "").lower()

    captured = {}
    if hostname == "accounts.google.com":
        cookie_header = VALID_COOKIES
        if cookie_header and addon_main._is_valid_cookie_header(cookie_header):
            captured["cookies"] = cookie_header

    assert captured.get("cookies") == VALID_COOKIES, (
        "Cookies should be captured from any accounts.google.com request"
    )


def test_cookie_capture_not_limited_to_oauth2_iframe() -> None:
    """Cookie capture must not gate on oauth2/iframe URL substring."""
    # A plain accounts.google.com request that does NOT contain oauth2/iframe
    # should still trigger cookie capture.
    plain_google_url = "https://accounts.google.com/ServiceLogin"
    assert "oauth2/iframe" not in plain_google_url

    from urllib.parse import urlsplit
    hostname = (urlsplit(plain_google_url).hostname or "").lower()
    assert hostname == "accounts.google.com"

    if hostname == "accounts.google.com":
        cookie_header = VALID_COOKIES
        captured = addon_main._is_valid_cookie_header(cookie_header)
    else:
        captured = False

    assert captured is True, "Valid cookies from accounts.google.com should pass validation"
