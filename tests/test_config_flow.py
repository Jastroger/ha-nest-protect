"""Tests for the Nest Protect config flow helpers."""

from custom_components.nest_protect.config_flow import ConfigFlow
from custom_components.nest_protect.const import (
    CONF_COOKIES,
    CONF_ISSUE_TOKEN,
    CONF_WIZARD_OUTPUT,
)


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


def test_parse_wizard_output_block():
    """Test parsing the auth wizard's copy-paste block."""
    issue_token, cookies = ConfigFlow._parse_wizard_output(
        "\n".join(
            [
                "NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1",
                f"issue_token={VALID_ISSUE_TOKEN}",
                f"cookies={VALID_COOKIES}",
                "END_NEST_PROTECT_AUTH_WIZARD_OUTPUT",
            ]
        )
    )

    assert issue_token == VALID_ISSUE_TOKEN
    assert cookies == VALID_COOKIES


def test_parse_wizard_output_legacy_label_block():
    """Test parsing older label-style wizard output."""
    issue_token, cookies = ConfigFlow._parse_wizard_output(
        f"Issue Token URL:\n{VALID_ISSUE_TOKEN}\nCookie header:\n{VALID_COOKIES}"
    )

    assert issue_token == VALID_ISSUE_TOKEN
    assert cookies == VALID_COOKIES


def test_validate_credentials_accepts_full_wizard_block():
    """Test config flow helper accepts a full wizard block."""
    flow = ConfigFlow()
    user_input = {
        CONF_WIZARD_OUTPUT: "\n".join(
            [
                "NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1",
                f"issue_token={VALID_ISSUE_TOKEN}",
                f"cookies={VALID_COOKIES}",
                "END_NEST_PROTECT_AUTH_WIZARD_OUTPUT",
            ]
        ),
        CONF_ISSUE_TOKEN: "",
        CONF_COOKIES: "",
    }

    assert flow._normalize_and_validate_credentials(user_input) == {}
    assert user_input[CONF_ISSUE_TOKEN] == VALID_ISSUE_TOKEN
    assert user_input[CONF_COOKIES] == VALID_COOKIES
    assert CONF_WIZARD_OUTPUT not in user_input


def test_validate_credentials_reports_incomplete_wizard_block():
    """Test incomplete wizard block reports an actionable field error."""
    flow = ConfigFlow()
    errors = flow._normalize_and_validate_credentials(
        {
            CONF_WIZARD_OUTPUT: (
                "NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1\n"
                f"cookies={VALID_COOKIES}\n"
                "END_NEST_PROTECT_AUTH_WIZARD_OUTPUT"
            ),
            CONF_ISSUE_TOKEN: "",
            CONF_COOKIES: "",
        }
    )

    assert errors == {CONF_WIZARD_OUTPUT: "missing_issue_token"}


def test_reauth_accepts_wizard_block_shape():
    """Test reauth can reuse the same wizard block normalization path."""
    flow = ConfigFlow()
    user_input = {
        CONF_WIZARD_OUTPUT: f"{VALID_ISSUE_TOKEN}\n{VALID_COOKIES}",
        CONF_ISSUE_TOKEN: "",
        CONF_COOKIES: "",
    }

    assert flow._normalize_and_validate_credentials(user_input) == {}
    assert user_input[CONF_ISSUE_TOKEN] == VALID_ISSUE_TOKEN
    assert user_input[CONF_COOKIES] == VALID_COOKIES


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
