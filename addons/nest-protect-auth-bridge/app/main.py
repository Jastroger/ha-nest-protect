"""Nest Protect auth bridge add-on web app."""

from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request
from playwright.sync_api import Error, sync_playwright
import requests

NEST_LOGIN_URL = "https://home.nest.com"

WAITING_FOR_LOGIN = "waiting_for_login"
GOOGLE_LOGIN_SEEN = "google_login_seen"
OAUTH_IFRAME_SEEN = "oauth_iframe_seen"
ISSUE_TOKEN_CAPTURED = "issue_token_captured"
COOKIE_HEADER_CAPTURED = "cookie_header_captured"
POSTING = "posting_to_home_assistant"
DONE = "done"
FAILED = "failed"

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
}


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}***{value[-4:]}"


def _set_state(**kwargs: Any) -> None:
    with state_lock:
        state.update(kwargs)


def _is_issue_token_url(url: str) -> bool:
    return (
        url.startswith("https://accounts.google.com/o/oauth2/iframerpc")
        and "action=issueToken" in url
    )


def _capture_flow(session_id: str, secret: str, callback_url: str) -> None:
    _set_state(
        status=WAITING_FOR_LOGIN,
        message="Open browser and sign in to Google/Nest",
        issue_token="",
        cookies="",
        error="",
        running=True,
    )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            def handle_request(playwright_request: Any) -> None:
                request_url = playwright_request.url
                hostname = (urlsplit(request_url).hostname or "").lower()
                if hostname == "accounts.google.com":
                    _set_state(status=GOOGLE_LOGIN_SEEN)
                if "oauth2/iframe" in request_url:
                    _set_state(status=OAUTH_IFRAME_SEEN)
                    cookie_header = playwright_request.headers.get("cookie")
                    if cookie_header:
                        _set_state(
                            status=COOKIE_HEADER_CAPTURED,
                            cookies=cookie_header,
                            message="Cookie header captured",
                        )
                if _is_issue_token_url(request_url):
                    _set_state(
                        status=ISSUE_TOKEN_CAPTURED,
                        issue_token=request_url,
                        message="issueToken request captured",
                    )

            page.on("request", handle_request)
            page.goto(NEST_LOGIN_URL, wait_until="domcontentloaded")

            while True:
                with state_lock:
                    issue_token = state["issue_token"]
                    cookies = state["cookies"]
                if issue_token and cookies:
                    break
                page.wait_for_timeout(500)

            _set_state(status=POSTING, message="Posting credentials to Home Assistant")
            response = requests.post(
                callback_url,
                json={
                    "secret": secret,
                    "issue_token": issue_token,
                    "cookies": cookies,
                },
                timeout=30,
            )
            if response.status_code >= 400:
                _set_state(
                    status=FAILED,
                    message="Home Assistant callback failed",
                    error=f"HTTP {response.status_code}",
                )
            else:
                _set_state(status=DONE, message="Done")

            context.close()
            browser.close()
    except (Error, requests.RequestException, RuntimeError):
        LOGGER.warning("Auth bridge failed")
        _set_state(status=FAILED, message="Failed", error="request_failed")
    finally:
        _set_state(running=False)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.post("/start")
def start() -> Any:
    session_id = (request.form.get("session_id") or request.args.get("session_id") or "").strip()
    secret = (request.form.get("secret") or request.args.get("secret") or "").strip()
    callback_url = (
        request.form.get("callback_url") or request.args.get("callback_url") or ""
    ).strip()

    if not session_id or not secret or not callback_url:
        _set_state(status=FAILED, message="Missing required launch values")
        return redirect("/")

    if not callback_url.startswith(("http://", "https://", "/")):
        _set_state(status=FAILED, message="Invalid callback URL")
        return redirect("/")

    with state_lock:
        if state.get("running"):
            return redirect("/")

    _set_state(
        session_id=session_id,
        secret=secret,
        callback_url=callback_url,
        status=WAITING_FOR_LOGIN,
        message="Starting browser",
        error="",
    )

    thread = threading.Thread(
        target=_capture_flow,
        args=(session_id, secret, callback_url),
        daemon=True,
    )
    thread.start()

    return redirect("/")


@app.get("/status")
def status() -> Any:
    with state_lock:
        response = {
            "status": state["status"],
            "message": state["message"],
            "running": state["running"],
            "session_id": _mask_secret(state["session_id"]),
            "secret": _mask_secret(state["secret"]),
            "callback_url": _mask_secret(state["callback_url"]),
            "issue_token": _mask_secret(state["issue_token"]),
            "cookies": _mask_secret(state["cookies"]),
            "error": _mask_secret(state["error"]),
        }
    return jsonify(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
