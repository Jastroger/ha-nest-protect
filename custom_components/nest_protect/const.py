"""Constants for Nest Protect integration (legacy compatible)."""

from __future__ import annotations
import logging
from typing import Final

LOGGER = logging.getLogger(__package__)

DOMAIN: Final = "nest_protect"
ATTRIBUTION: Final = "Data provided by Google"

# Platforms used by the original integration (adjust if you have others)
PLATFORMS: Final = ["binary_sensor", "sensor", "select", "switch"]

# OAuth constants (legacy flow still uses a Google OAuth)
OAUTH_AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL: Final = "https://oauth2.googleapis.com/token"

# Minimal scopes we request for legacy user identification. The legacy client then
# tries to exchange the Google access token for a Nest JWT (this is the point
# that may be blocked by Google -> restricted mode).
OAUTH_SCOPES: Final = [
    "https://www.googleapis.com/auth/userinfo.email",
]
