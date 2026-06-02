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


def test_wait_for_capture_times_out() -> None:
    """Capture loop should stop at timeout instead of running forever."""
    addon_main._set_state(
        issue_token="",
        cookies="",
        cancel_requested=False,
    )

    with pytest.raises(addon_main.CaptureTimeoutError):
        addon_main._wait_for_capture(timeout_seconds=0.01, poll_interval_seconds=0.001)
