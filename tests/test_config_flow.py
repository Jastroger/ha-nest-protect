"""Tests for the Nest Protect config flow helpers."""

from custom_components.nest_protect.config_flow import ConfigFlow
from custom_components.nest_protect.const import CONF_COOKIES, CONF_ISSUE_TOKEN


VALID_ISSUE_TOKEN = (
    "https://accounts.google.com/o/oauth2/iframerpc?"
    "action=issueToken&response_type=token"
)
VALID_COOKIES = (
    "SID=example-session; HSID=example-hsid; SSID=example-ssid; "
    "APISID=example-apisid; SAPISID=example-sapisid; "
    "ACCOUNT_CHOOSER=example; NID=example; 1P_JAR=example; "
    "CONSENT=YES+example"
)


def test_normalize_issue_token_strips_whitespace():
    """Test issue token normalization."""
    assert ConfigFlow._normalize_issue_token(f" \n{VALID_ISSUE_TOKEN}\n ") == (
        VALID_ISSUE_TOKEN
    )


def test_normalize_cookies_compacts_multiline_header():
    """Test cookie normalization."""
    cookies = "SID=example;\n  HSID=example;   SSID=example"
    assert ConfigFlow._normalize_cookies(cookies) == (
        "SID=example; HSID=example; SSID=example"
    )


def test_split_issue_token_and_cookies_from_combined_paste():
    """Test combined paste support."""
    issue_token, cookies = ConfigFlow._split_issue_token_and_cookies(
        f"{VALID_ISSUE_TOKEN}\n{VALID_COOKIES}",
        "",
    )

    assert issue_token == VALID_ISSUE_TOKEN
    assert cookies == VALID_COOKIES


def test_validate_credentials_requires_issue_token():
    """Test missing issue token validation."""
    flow = ConfigFlow()
    errors = flow._normalize_and_validate_credentials(
        {CONF_ISSUE_TOKEN: "", CONF_COOKIES: VALID_COOKIES}
    )

    assert errors == {CONF_ISSUE_TOKEN: "missing_issue_token"}


def test_validate_credentials_rejects_invalid_issue_token():
    """Test invalid issue token validation."""
    flow = ConfigFlow()
    errors = flow._normalize_and_validate_credentials(
        {CONF_ISSUE_TOKEN: "https://example.com", CONF_COOKIES: VALID_COOKIES}
    )

    assert errors == {CONF_ISSUE_TOKEN: "invalid_issue_token"}


def test_validate_credentials_requires_cookie_header():
    """Test missing cookie header validation."""
    flow = ConfigFlow()
    errors = flow._normalize_and_validate_credentials(
        {CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN, CONF_COOKIES: ""}
    )

    assert errors == {CONF_COOKIES: "missing_cookie_header"}


def test_validate_credentials_rejects_incomplete_cookie_header():
    """Test incomplete cookie header validation."""
    flow = ConfigFlow()
    errors = flow._normalize_and_validate_credentials(
        {CONF_ISSUE_TOKEN: VALID_ISSUE_TOKEN, CONF_COOKIES: "SID=short"}
    )

    assert errors == {CONF_COOKIES: "incomplete_cookie_header"}


def test_validate_credentials_normalizes_user_input():
    """Test that valid credentials are normalized in place."""
    flow = ConfigFlow()
    user_input = {
        CONF_ISSUE_TOKEN: f"\n{VALID_ISSUE_TOKEN}\n",
        CONF_COOKIES: "SID=example;\n HSID=example; SSID=example; "
        "APISID=example; SAPISID=example; ACCOUNT_CHOOSER=example; "
        "NID=example; CONSENT=YES+example",
    }

    assert flow._normalize_and_validate_credentials(user_input) == {}
    assert user_input[CONF_ISSUE_TOKEN] == VALID_ISSUE_TOKEN
    assert "\n" not in user_input[CONF_COOKIES]
