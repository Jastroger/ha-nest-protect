#!/usr/bin/env python3
"""Capture Nest Protect issue token and cookies with Playwright."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright


@dataclass
class CaptureResult:
    issue_token_url: Optional[str] = None
    oauth_cookie: Optional[str] = None


NEST_LOGIN_URL = "https://home.nest.com"


def print_intro() -> None:
    print("Nest Protect Cookie Wizard")
    print("---------------------------")
    print("This helper launches a local browser using Playwright.")
    print("No credentials are sent to any external service by this script.")
    print("Log in using the browser window that opens.")
    print("When you are done, return here and press Enter to collect values.")
    print("")


def print_status(result: CaptureResult) -> None:
    issue_status = "found" if result.issue_token_url else "missing"
    cookie_status = "found" if result.oauth_cookie else "missing"
    print(f"Current status: issue_token={issue_status}, cookies={cookie_status}")


def print_copy_ready(result: CaptureResult) -> None:
    print("\nCopy-ready values:")
    print("-------------------")
    print(f"issue_token: {result.issue_token_url}")
    print(f"cookies: {result.oauth_cookie}")
    print("\nJSON snippet:")
    print("{")
    print(f"  \"issue_token\": \"{result.issue_token_url}\",")
    print(f"  \"cookies\": \"{result.oauth_cookie}\"")
    print("}")


def run_wizard() -> None:
    result = CaptureResult()

    def handle_request(request) -> None:
        url = request.url
        if "issueToken" in url and not result.issue_token_url:
            result.issue_token_url = url
        if "oauth2/iframe" in url:
            cookie_header = request.headers.get("cookie")
            if cookie_header:
                result.oauth_cookie = cookie_header

    print_intro()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.on("request", handle_request)
        page.goto(NEST_LOGIN_URL, wait_until="domcontentloaded")

        while True:
            user_input = input("Press Enter once login is complete (or type 'q' to quit): ")
            if user_input.strip().lower() == "q":
                break
            print_status(result)
            if result.issue_token_url and result.oauth_cookie:
                print_copy_ready(result)
                break
            print("Still waiting on both values. You can continue in the browser window.")

        context.close()
        browser.close()


if __name__ == "__main__":
    run_wizard()
