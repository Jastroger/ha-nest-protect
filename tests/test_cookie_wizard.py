"""Tests for the external Nest Protect auth wizard."""

from scripts.nest_protect_cookie_wizard import (
    CaptureState,
    format_wizard_output,
    is_issue_token_url,
    mask_secret,
    update_capture_state,
)


VALID_ISSUE_TOKEN = (
    "https://accounts.google.com/o/oauth2/iframerpc?"
    "action=issueToken&response_type=token"
)
VALID_COOKIES = (
    "SID=example-session; HSID=example-hsid; SSID=example-ssid; "
    "APISID=example-apisid; SAPISID=example-sapisid"
)


def test_is_issue_token_url_requires_iframerpc_issue_token():
    """Test issue token URL detection."""
    assert is_issue_token_url(VALID_ISSUE_TOKEN)
    assert not is_issue_token_url("https://accounts.google.com/o/oauth2/iframe")


def test_update_capture_state_tracks_oauth_iframe_without_issue_token():
    """Test incomplete state where iframe is seen but no issue token exists."""
    state = CaptureState()

    update_capture_state(
        state,
        "https://accounts.google.com/o/oauth2/iframe",
        {"cookie": VALID_COOKIES},
    )

    assert state.oauth_iframe_seen
    assert state.oauth_cookie == VALID_COOKIES
    assert state.issue_token_url is None
    assert not state.complete


def test_update_capture_state_tracks_complete_capture():
    """Test complete capture state."""
    state = CaptureState()

    update_capture_state(state, VALID_ISSUE_TOKEN, {})
    update_capture_state(
        state,
        "https://accounts.google.com/o/oauth2/iframe",
        {"cookie": VALID_COOKIES},
    )

    assert state.issue_token_url == VALID_ISSUE_TOKEN
    assert state.oauth_cookie == VALID_COOKIES
    assert state.complete


def test_format_wizard_output_contains_parseable_block():
    """Test final copy-paste block shape."""
    state = CaptureState(
        issue_token_url=VALID_ISSUE_TOKEN,
        oauth_cookie=VALID_COOKIES,
    )

    output = format_wizard_output(state)

    assert "NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1" in output
    assert f"issue_token={VALID_ISSUE_TOKEN}" in output
    assert f"cookies={VALID_COOKIES}" in output
    assert "END_NEST_PROTECT_AUTH_WIZARD_OUTPUT" in output


def test_mask_secret_hides_normal_output():
    """Test status output masking."""
    assert mask_secret("a" * 40) == "aaaaaaaaaa...aaaaaaaaaa"
    assert mask_secret("short") == "***"
