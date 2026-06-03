"""Nest Protect auth bridge add-on web app."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request
import requests

NEST_LOGIN_URL = "https://home.nest.com"
DEFAULT_CAPTURE_TIMEOUT_SECONDS = 600
DEFAULT_AUTH_BRIDGE_PORT = 8099
MODE_ADDON = "addon"
MODE_STANDALONE = "standalone"

BROWSER_STARTING = "browser_starting"
BROWSER_READY = "browser_ready"
WAITING_FOR_LOGIN = "waiting_for_login"
GOOGLE_LOGIN_SEEN = "google_login_seen"
OAUTH_IFRAME_SEEN = "oauth_iframe_seen"
ISSUE_TOKEN_CAPTURED = "issue_token_captured"
COOKIE_HEADER_CAPTURED = "cookie_header_captured"
POSTING = "posting_to_home_assistant"
DONE = "done"
FAILED = "failed"
TIMEOUT = "timeout"

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

state_lock = threading.Lock()
state: dict[str, Any] = {
    "status": WAITING_FOR_LOGIN,
    "message": "Idle",
    "session_id": "",
    "secret": "",
    "callback_url": "",
    "issue_token": "",
    "cookies": "",
    "error": "",
    "running": False,
    "cancel_requested": False,
}


class CaptureTimeoutError(RuntimeError):
    """Raised when auth bridge capture exceeds timeout."""


class CaptureCancelledError(RuntimeError):
    """Raised when capture is cancelled by the user."""


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}***{value[-4:]}"


def _set_state(**kwargs: Any) -> None:
    with state_lock:
        state.update(kwargs)


def _clear_sensitive_state() -> None:
    _set_state(session_id="", secret="", callback_url="", issue_token="", cookies="")


def _is_issue_token_url(url: str) -> bool:
    return (
        url.startswith("https://accounts.google.com/o/oauth2/iframerpc")
        and "action=issueToken" in url
    )


def _is_valid_cookie_header(cookies: str) -> bool:
    if len(cookies) <= 100:
        return False
    markers = ("APISID=", "SAPISID=", "HSID=", "SSID=", "SID=")
    return any(marker in cookies for marker in markers)


def _is_valid_callback_url(callback_url: str) -> bool:
    parsed = urlsplit(callback_url)
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path)


def _get_auth_bridge_mode() -> str:
    """Return the configured Auth Bridge deployment mode."""
    mode = os.environ.get("AUTH_BRIDGE_MODE", MODE_ADDON).strip().lower()
    if mode not in {MODE_ADDON, MODE_STANDALONE}:
        raise RuntimeError("invalid_auth_bridge_mode")
    return mode


def _build_callback_url(session_id: str, callback_url: str = "") -> str:
    """Build the Home Assistant callback URL for the current deployment mode."""
    if callback_url:
        return callback_url

    mode = _get_auth_bridge_mode()
    if mode == MODE_ADDON:
        return f"http://supervisor/core/api/nest_protect/auth_bridge/{session_id}"

    ha_base_url = os.environ.get("HA_BASE_URL", "").strip().rstrip("/")
    if not ha_base_url:
        raise RuntimeError("missing_ha_base_url")
    return f"{ha_base_url}/api/nest_protect/auth_bridge/{session_id}"


def _extract_launch_values() -> tuple[str, str, str]:
    session_id = (request.form.get("session_id") or request.args.get("session_id") or "").strip()
    secret = (request.form.get("secret") or request.args.get("secret") or "").strip()
    callback_url = (
        request.form.get("callback_url") or request.args.get("callback_url") or ""
    ).strip()
    return session_id, secret, callback_url


def _build_callback_request(callback_url: str) -> tuple[str, dict[str, str]]:
    headers: dict[str, str] = {}
    parsed = urlsplit(callback_url)
    if (
        _get_auth_bridge_mode() == MODE_ADDON
        and parsed.hostname == "supervisor"
        and parsed.path.startswith("/core/api/")
    ):
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("missing_supervisor_token")
        headers["Authorization"] = "Bearer " + token
    return callback_url, headers


def _wait_for_capture(timeout_seconds: float, poll_interval_seconds: float = 0.25) -> tuple[str, str]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        with state_lock:
            issue_token = state.get("issue_token", "")
            cookies = state.get("cookies", "")
            cancel_requested = bool(state.get("cancel_requested"))

        if cancel_requested:
            raise CaptureCancelledError("cancelled")

        if issue_token and cookies and _is_issue_token_url(issue_token) and _is_valid_cookie_header(cookies):
            return issue_token, cookies

        if time.monotonic() >= deadline:
            raise CaptureTimeoutError("capture_timeout")

        time.sleep(poll_interval_seconds)


def _capture_flow(session_id: str, secret: str, callback_url: str) -> None:
    _set_state(
        status=BROWSER_STARTING,
        message="Starting browser",
        issue_token="",
        cookies="",
        error="",
        running=True,
        cancel_requested=False,
    )

    profile_dir = tempfile.mkdtemp(prefix="nest-auth-bridge-")
    context = None

    try:
        from playwright.sync_api import Error, sync_playwright

        timeout_seconds = int(
            os.environ.get("AUTH_BRIDGE_TIMEOUT_SECONDS", DEFAULT_CAPTURE_TIMEOUT_SECONDS)
        )
        chromium_path = os.environ.get("CHROMIUM_EXECUTABLE", "/usr/bin/chromium-browser")

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                executable_path=chromium_path,
                viewport={"width": 1280, "height": 800},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            _set_state(status=BROWSER_READY, message="Browser ready")

            page = context.pages[0] if context.pages else context.new_page()

            def handle_request(playwright_request: Any) -> None:
                request_url = playwright_request.url
                hostname = (urlsplit(request_url).hostname or "").lower()
                if hostname == "accounts.google.com":
                    _set_state(status=GOOGLE_LOGIN_SEEN, message="Google login detected")
                    cookie_header = playwright_request.headers.get("cookie")
                    if cookie_header and _is_valid_cookie_header(cookie_header):
                        _set_state(
                            status=COOKIE_HEADER_CAPTURED,
                            cookies=cookie_header,
                            message="Cookie header captured",
                        )
                if "oauth2/iframe" in request_url:
                    _set_state(status=OAUTH_IFRAME_SEEN, message="OAuth iframe request detected")
                if _is_issue_token_url(request_url):
                    _set_state(
                        status=ISSUE_TOKEN_CAPTURED,
                        issue_token=request_url,
                        message="issueToken request captured",
                    )

            page.on("request", handle_request)
            page.goto(NEST_LOGIN_URL, wait_until="domcontentloaded")
            _set_state(status=WAITING_FOR_LOGIN, message="Complete Google/Nest sign-in")

            issue_token, cookies = _wait_for_capture(timeout_seconds)

            callback_post_url, callback_headers = _build_callback_request(callback_url)
            _set_state(status=POSTING, message="Posting credentials to Home Assistant")
            response = requests.post(
                callback_post_url,
                json={
                    "secret": secret,
                    "issue_token": issue_token,
                    "cookies": cookies,
                },
                headers=callback_headers,
                timeout=30,
            )
            try:
                resp_json = response.json()
            except Exception:
                resp_json = None
            if not isinstance(resp_json, dict) or resp_json.get("ok") is not True:
                _set_state(
                    status=FAILED,
                    message="Home Assistant callback failed",
                    error="callback_rejected",
                )
            else:
                _set_state(status=DONE, message="Done")
    except CaptureTimeoutError:
        _set_state(status=TIMEOUT, message="Timed out waiting for login", error="timeout")
    except CaptureCancelledError:
        _set_state(status=FAILED, message="Cancelled", error="")
    except Exception:
        LOGGER.warning("Auth bridge failed")
        _set_state(status=FAILED, message="Failed", error="request_failed")
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                LOGGER.debug("Failed closing browser context", exc_info=True)
        shutil.rmtree(profile_dir, ignore_errors=True)
        _clear_sensitive_state()
        _set_state(running=False)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.route("/start", methods=["POST", "GET"])
def start() -> Any:
    session_id, secret, callback_url = _extract_launch_values()

    if not session_id or not secret:
        _set_state(
            status=FAILED,
            message=(
                "Open the launch link from Home Assistant so this session can be "
                "connected."
            ),
        )
        return redirect("./")

    try:
        callback_url = _build_callback_url(session_id, callback_url)
    except RuntimeError as err:
        _set_state(status=FAILED, message="Missing callback configuration", error=str(err))
        return redirect("./")

    if not _is_valid_callback_url(callback_url):
        _set_state(status=FAILED, message="Invalid callback URL")
        return redirect("./")

    try:
        _build_callback_request(callback_url)
    except RuntimeError as err:
        _set_state(status=FAILED, message="Callback authentication unavailable", error=str(err))
        return redirect("./")

    with state_lock:
        if state.get("running"):
            return redirect("./")

    _set_state(
        session_id=session_id,
        secret=secret,
        callback_url=callback_url,
        status=BROWSER_STARTING,
        message="Starting browser",
        error="",
        cancel_requested=False,
    )

    thread = threading.Thread(
        target=_capture_flow,
        args=(session_id, secret, callback_url),
        daemon=True,
    )
    thread.start()

    return redirect("./")


@app.post("/cancel")
def cancel() -> Any:
    with state_lock:
        running = bool(state.get("running"))
    if running:
        _set_state(cancel_requested=True, message="Cancelling login", error="")
    else:
        _set_state(cancel_requested=False)
    return redirect("./")


@app.post("/reset")
def reset() -> Any:
    _set_state(
        status=WAITING_FOR_LOGIN,
        message="Idle",
        issue_token="",
        cookies="",
        error="",
        running=False,
        cancel_requested=False,
    )
    _clear_sensitive_state()
    return redirect("./")


@app.get("/status")
def status() -> Any:
    with state_lock:
        response = {
            "status": state["status"],
            "message": state["message"],
            "running": state["running"],
            "session_id": _mask_secret(state["session_id"]),
            "error": _mask_secret(state["error"]),
        }
    return jsonify(response)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("AUTH_BRIDGE_APP_PORT", "8100")),
    )
