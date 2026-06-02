#!/usr/bin/env python3
"""Capture Nest Protect issue token and cookies with Playwright."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import sys
from typing import Any


NEST_LOGIN_URL = "https://home.nest.com"
ISSUE_TOKEN_MARKER = "action=issueToken"
OAUTH_IFRAME_MARKER = "oauth2/iframe"


@dataclass
class CaptureResult:
    """Values captured from browser network requests."""

    issue_token_url: str | None = None
    oauth_cookie: str | None = None

    @property
    def complete(self) -> bool:
        """Return true when both required values were captured."""
        return bool(self.issue_token_url and self.oauth_cookie)


def mask_secret(value: str | None, visible: int = 10) -> str:
    """Mask a token or cookie value for status output."""
    if not value:
        return "missing"
    if len(value) <= visible * 2:
        return "***"
    return f"{value[:visible]}...{value[-visible:]}"


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


def print_intro(browser: str) -> None:
    """Print user-facing instructions."""
    print("Nest Protect credential wizard")
    print("--------------------------------")
    print("This script opens a local browser and watches Network requests.")
    print("It does not send your credentials anywhere except to Google/Nest in the browser.")
    print("")
    print(f"Browser mode: {browser}")
    print("A fresh private browser context will be used.")
    print("Complete Google login, including 2FA, in the browser window.")
    print("Do not log out of home.nest.com after copying the captured values.")
    print("")


def print_status(result: CaptureResult) -> None:
    """Print masked capture status."""
    print("Current capture status:")
    print(f"  Issue Token URL: {mask_secret(result.issue_token_url)}")
    print(f"  Cookie header:    {mask_secret(result.oauth_cookie)}")


def print_copy_ready(result: CaptureResult) -> None:
    """Print final values in copy-friendly formats."""
    print("")
    print("Captured values")
    print("---------------")
    print("Paste this block into the first Home Assistant setup field:")
    print("")
    print(result.issue_token_url)
    print(result.oauth_cookie)
    print("")
    print("Or paste the values separately:")
    print("")
    print("Issue Token URL:")
    print(result.issue_token_url)
    print("")
    print("Cookie header:")
    print(result.oauth_cookie)
    print("")
    print("Security note: treat these values like passwords.")


def browser_launch_kwargs(browser: str) -> dict[str, str]:
    """Return Playwright launch kwargs for the requested browser."""
    if browser == "chrome":
        return {"channel": "chrome"}
    if browser == "edge":
        return {"channel": "msedge"}
    return {}


def run_wizard(browser_name: str) -> int:
    """Run the capture wizard."""
    playwright_error, sync_playwright = load_playwright()
    result = CaptureResult()

    def handle_request(request: Any) -> None:
        url = request.url
        if ISSUE_TOKEN_MARKER in url and not result.issue_token_url:
            result.issue_token_url = url
            print("Captured Issue Token URL.")

        if OAUTH_IFRAME_MARKER in url:
            cookie_header = request.headers.get("cookie")
            if cookie_header:
                result.oauth_cookie = cookie_header
                print("Captured Cookie header from oauth2/iframe request.")

    print_intro(browser_name)

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
                    "Press Enter after login, 's' for status, or 'q' to quit: "
                ).strip().lower()
                if user_input == "q":
                    break
                if user_input == "s":
                    print_status(result)
                    continue
                print_status(result)
                if result.complete:
                    print_copy_ready(result)
                    break
                print("")
                print("Both values have not been captured yet.")
                print("Stay in the browser window and make sure home.nest.com is loaded.")

            context.close()
            browser.close()
    except playwright_error as err:
        print("")
        print("Could not start or use the Playwright browser.")
        print(str(err).splitlines()[0])
        print("")
        print("Try installing the browser runtime:")
        print("  python -m playwright install chromium")
        if browser_name == "chrome":
            print("Or run with the bundled Chromium browser:")
            print("  python scripts/nest_protect_cookie_wizard.py --browser chromium")
        if browser_name == "edge":
            print("Or run with the bundled Chromium browser:")
            print("  python scripts/nest_protect_cookie_wizard.py --browser chromium")
        return 2

    return 0 if result.complete else 1


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        choices=("chromium", "chrome", "edge"),
        default="chromium",
        help="Browser to launch. Defaults to Playwright Chromium.",
    )
    args = parser.parse_args()
    return run_wizard(args.browser)


if __name__ == "__main__":
    raise SystemExit(main())
