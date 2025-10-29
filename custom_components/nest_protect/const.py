"""Constants for Nest Protect integration."""

from __future__ import annotations
import logging
from typing import Final

LOGGER = logging.getLogger(__package__)

DOMAIN: Final = "nest_protect"
ATTRIBUTION: Final = "Data provided by Google"

OAUTH_AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_SCOPES: Final = [
    "https://www.googleapis.com/auth/userinfo.email",
]

PLATFORMS: Final = ["binary_sensor", "sensor"]
