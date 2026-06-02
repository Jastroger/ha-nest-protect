"""Tests for diagnostics safety."""

from custom_components.nest_protect.diagnostics import TO_REDACT


def test_diagnostics_redacts_auth_secrets():
    """Test that diagnostics redacts credential and token fields."""
    assert "access_token" in TO_REDACT
    assert "cookie" in TO_REDACT
    assert "cookies" in TO_REDACT
    assert "issue_token" in TO_REDACT
    assert "refresh_token" in TO_REDACT
    assert "wizard_output" in TO_REDACT
    assert "auth_bridge_secret" in TO_REDACT
    assert "auth_bridge_session" in TO_REDACT
    assert "id_token" in TO_REDACT
    assert "jwt" in TO_REDACT
