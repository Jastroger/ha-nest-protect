#!/usr/bin/env python3
"""Capture Nest Protect credentials with a zero-DevTools Playwright wizard."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError


NEST_LOGIN_URL = "https://home.nest.com"
NEST_AUTH_URL_JWT = "https://nestauthproxyservice-pa.googleapis.com/v1/issue_jwt"
NEST_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/77.0.3865.120 Safari/537.36"
)
ISSUE_TOKEN_URL_PREFIX = "https://accounts.google.com/o/oauth2/iframerpc"
APP_LAUNCH_URL_FORMAT = "{host}/api/0.1/user/{user_id}/app_launch"
WIZARD_BLOCK_BEGIN = "NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1"
WIZARD_BLOCK_END = "END_NEST_PROTECT_AUTH_WIZARD_OUTPUT"


@dataclass
class CaptureState:
    """State observed while the browser loads the Nest web app."""

    google_login_seen: bool = False
    google_consent_seen: bool = False
    oauth_iframe_seen: bool = False
    issue_token_url: str | None = None
    oauth_cookie: str | None = None
    jwt_exchange_succeeded: bool = False
    app_launch_succeeded: bool = False

    @property
    def complete(self) -> bool:
        """Return true when both required captured values are present."""
        return bool(self.issue_token_url and self.oauth_cookie)


def mask_secret(value: str | None, visible: int = 10) -> str:
    """Mask a token or cookie value for normal status output."""
    if not value:
        return "missing"
    if len(value) <= visible * 2:
        return "***"
    return f"{value[:visible]}...{value[-visible:]}"


def is_issue_token_url(url: str) -> bool:
    """Return true for the usable Google issueToken request URL."""
    return url.startswith(ISSUE_TOKEN_URL_PREFIX) and "action=issueToken" in url


def update_capture_state(state: CaptureState, url: str, headers: dict[str, str]) -> None:
    """Update capture state from one browser request."""
    if "accounts.google.com" in url:
        state.google_login_seen = True

    if "consent" in url.lower():
        state.google_consent_seen = True

    if "oauth2/iframe" in url:
        state.oauth_iframe_seen = True
        cookie_header = headers.get("cookie")
        if cookie_header:
            state.oauth_cookie = cookie_header

    if is_issue_token_url(url):
        state.issue_token_url = url


def format_wizard_output(state: CaptureState) -> str:
    """Return the one block users paste into Home Assistant."""
    return "\n".join(
        [
            WIZARD_BLOCK_BEGIN,
            f"issue_token={state.issue_token_url}",
            f"cookies={state.oauth_cookie}",
            WIZARD_BLOCK_END,
        ]
    )


def load_playwright() -> Any:
    """Import Playwright and print setup help if it is missing."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ModuleNotFoundError:
        print("Playwright is not installed.")
        print("")
        print("Install it with:")
        print("  python -m pip install playwright")
        print("  python -m playwright install chromium")
        sys.exit(2)

    return Error, sync_playwright


def print_intro(browser: str, validate: bool) -> None:
    """Print user-facing instructions."""
    print("Nest Protect Auth Wizard")
    print("------------------------")
    print("This is the recommended zero-DevTools setup path.")
    print("You do not need browser developer tools, HAR files, or console snippets.")
    print("")
    print("A real browser will open. Sign in to Google normally in that window.")
    print("The wizard only watches local browser network requests for the two values")
    print("Home Assistant needs. It does not read or steal your Google password.")
    print("")
    print(f"Browser mode: {browser}")
    print(f"Credential validation: {'enabled' if validate else 'disabled'}")
    print("")


def print_status(state: CaptureState) -> None:
    """Print masked status for all important wizard states."""
    print("Current status:")
    print(f"  Google login page seen:      {state.google_login_seen}")
    print(f"  Google consent page seen:    {state.google_consent_seen}")
    print(f"  oauth2 iframe seen:          {state.oauth_iframe_seen}")
    print(f"  Issue Token URL captured:    {mask_secret(state.issue_token_url)}")
    print(f"  Cookie header captured:      {mask_secret(state.oauth_cookie)}")
    print(f"  JWT exchange succeeded:      {state.jwt_exchange_succeeded}")
    print(f"  Nest app_launch succeeded:   {state.app_launch_succeeded}")


def print_incomplete_help(state: CaptureState) -> None:
    """Print actionable recovery guidance for incomplete captures."""
    print("")
    print("The wizard has not captured a complete usable block yet.")
    print("Keep the browser open and try these steps:")
    print("  1. Reload https://home.nest.com in the browser window.")
    print("  2. Wait until the Nest web app is fully loaded.")
    print("  3. If prompted, finish Google login and consent.")
    print("  4. Try a fresh browser context by closing this wizard and running it again.")
    print("  5. Confirm your Google account can see Nest Protect at home.nest.com.")
    print("  6. Confirm any Google account migration has completed.")
    if state.oauth_iframe_seen and not state.issue_token_url:
        print("")
        print("The oauth2 iframe was seen, but no issueToken request was captured yet.")
        print("Reload home.nest.com and wait for the Nest web app to finish loading.")


def print_copy_ready(state: CaptureState) -> None:
    """Print final values in one copy-paste block."""
    print("")
    print("Copy this whole block into Home Assistant:")
    print("-----------------------------------------")
    print(format_wizard_output(state))
    print("-----------------------------------------")
    print("Treat this block like a password. Do not share it.")


def browser_launch_kwargs(browser: str) -> dict[str, str]:
    """Return Playwright launch kwargs for the requested browser."""
    if browser == "chrome":
        return {"channel": "chrome"}
    if browser == "edge":
        return {"channel": "msedge"}
    return {}


def debug_secret(value: str | None, show_secrets: bool) -> str:
    """Return debug-safe secret output."""
    return value or "missing" if show_secrets else mask_secret(value)


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Make a small JSON request with stdlib urllib."""
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def validate_credentials(state: CaptureState, debug: bool, show_secrets: bool) -> bool:
    """Optionally validate captured values against Nest endpoints."""
    if not state.complete:
        return False

    try:
        if debug:
            print("Validating issue token and Cookie header...")
            print(f"  issue_token={debug_secret(state.issue_token_url, show_secrets)}")
            print(f"  cookies={debug_secret(state.oauth_cookie, show_secrets)}")

        auth = http_json(
            state.issue_token_url,
            headers={
                "Sec-Fetch-Mode": "cors",
                "User-Agent": NEST_USER_AGENT,
                "X-Requested-With": "XmlHttpRequest",
                "Referer": "https://accounts.google.com/o/oauth2/iframe",
                "cookie": state.oauth_cookie,
            },
        )
        if auth.get("error"):
            print(f"Google rejected the captured credentials: {auth['error']}")
            return False

        access_token = auth["access_token"]
        jwt_response = http_json(
            NEST_AUTH_URL_JWT,
            method="POST",
            data=parse.urlencode(
                {
                    "embed_google_oauth_access_token": True,
                    "expire_after": "3600s",
                    "google_oauth_access_token": access_token,
                    "policy_id": "authproxy-oauth-policy",
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": NEST_USER_AGENT,
                "Referer": NEST_LOGIN_URL,
            },
        )
        jwt = jwt_response.get("jwt")
        if not jwt:
            print("Nest auth proxy did not return a JWT.")
            return False
        state.jwt_exchange_succeeded = True

        nest_session = http_json(
            f"{NEST_LOGIN_URL}/session",
            headers={
                "Authorization": f"Basic {jwt}",
                "cookie": "G_ENABLED_IDPS=google; eu_cookie_accepted=1; "
                f"viewer-volume=0.5; cztoken={jwt}",
            },
        )

        app_launch = http_json(
            APP_LAUNCH_URL_FORMAT.format(
                host=NEST_LOGIN_URL, user_id=nest_session["userid"]
            ),
            method="POST",
            data=json.dumps(
                {
                    "known_bucket_types": [
                        "kryptonite",
                        "structure",
                        "topaz",
                        "where",
                        "user",
                    ],
                    "known_bucket_versions": [],
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Basic {nest_session['access_token']}",
                "Content-Type": "application/json",
                "X-nl-user-id": nest_session["userid"],
                "X-nl-protocol-version": "1",
            },
        )
        state.app_launch_succeeded = "updated_buckets" in app_launch
        if not state.app_launch_succeeded:
            print("Nest app_launch response did not include updated_buckets.")
        return state.app_launch_succeeded
    except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as err:
        print("Validation failed.")
        print(str(err))
        return False


def run_wizard(
    browser_name: str,
    *,
    validate: bool,
    debug: bool,
    show_secrets: bool,
) -> int:
    """Run the capture wizard."""
    playwright_error, sync_playwright = load_playwright()
    state = CaptureState()

    def handle_request(playwright_request: Any) -> None:
        before = CaptureState(**state.__dict__)
        update_capture_state(state, playwright_request.url, playwright_request.headers)
        if state.google_login_seen and not before.google_login_seen:
            print("Google login page seen.")
        if state.google_consent_seen and not before.google_consent_seen:
            print("Google consent page seen.")
        if state.oauth_iframe_seen and not before.oauth_iframe_seen:
            print("oauth2 iframe seen.")
        if state.issue_token_url and not before.issue_token_url:
            print("Issue Token URL captured.")
        if state.oauth_cookie and not before.oauth_cookie:
            print("Cookie header captured.")

    print_intro(browser_name, validate)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                **browser_launch_kwargs(browser_name),
            )
            context = browser.new_context()
            page = context.new_page()
            page.on("request", handle_request)
            page.goto(NEST_LOGIN_URL, wait_until="domcontentloaded")

            while True:
                user_input = input(
                    "Press Enter after login, 's' for status, 'r' to reload, "
                    "or 'q' to quit: "
                ).strip().lower()
                if user_input == "q":
                    break
                if user_input == "r":
                    page.goto(NEST_LOGIN_URL, wait_until="domcontentloaded")
                    continue
                print_status(state)
                if state.complete:
                    if validate and not validate_credentials(
                        state, debug=debug, show_secrets=show_secrets
                    ):
                        context.close()
                        browser.close()
                        return 3
                    print_copy_ready(state)
                    context.close()
                    browser.close()
                    return 0
                print_incomplete_help(state)

            context.close()
            browser.close()
    except playwright_error as err:
        print("")
        print("Could not start or use the Playwright browser.")
        print(str(err).splitlines()[0])
        print("")
        print("Try installing the browser runtime:")
        print("  python -m playwright install chromium")
        if browser_name in ("chrome", "edge"):
            print("Or run with the bundled Chromium browser:")
            print("  python scripts/nest_protect_cookie_wizard.py --browser chromium")
        return 2

    print_incomplete_help(state)
    return 1


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        choices=("chromium", "chrome", "edge"),
        default="chromium",
        help="Browser to launch. Defaults to Playwright Chromium.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Exchange captured credentials and call Nest app_launch before printing.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print verbose troubleshooting details with secrets masked.",
    )
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Unsafe debug mode: print full secrets in debug output.",
    )
    args = parser.parse_args()
    return run_wizard(
        args.browser,
        validate=args.validate,
        debug=args.debug,
        show_secrets=args.show_secrets,
    )


if __name__ == "__main__":
    raise SystemExit(main())
