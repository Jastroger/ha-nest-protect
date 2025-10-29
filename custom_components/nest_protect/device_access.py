"""Device Access helpers for Nest Protect (Device Access / SDM)."""

from __future__ import annotations

from urllib.parse import urlencode

# PartnerConnections auth base:
# The Device Access docs describe a PartnerConnections auth URL pattern that returns ?code=...
# We offer helper to build that URL for the user to open in browser.
# Docs: https://developers.google.com/nest/device-access/api/authorization. :contentReference[oaicite:3]{index=3}
PARTNER_AUTH_BASE = "https://nestservices.google.com/partnerconnections/{project_id}/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


def build_partner_auth_url(
    device_access_project_id: str,
    client_id: str,
    redirect_uri: str = "https://www.google.com",
    scopes: list[str] | None = None,
) -> str:
    """
    Build a PartnerConnections authorization URL.
    Many guides use https://www.google.com as redirect and instruct user to copy code from URL.
    """
    if scopes is None:
        scopes = [
            "https://www.googleapis.com/auth/sdm.service",
            "https://www.googleapis.com/auth/pubsub",
        ]

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    }
    base = PARTNER_AUTH_BASE.format(project_id=device_access_project_id)
    return f"{base}?{urlencode(params)}"
