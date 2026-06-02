"""Constants for Nest Protect."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import Platform

LOGGER: logging.Logger = logging.getLogger(__package__)

DOMAIN: Final = "nest_protect"
ATTRIBUTION: Final = "Data provided by Google"

CONF_ACCOUNT_TYPE: Final = "account_type"
CONF_AUTH_BRIDGE_SESSION: Final = "auth_bridge_session"
CONF_AUTH_BRIDGE_SECRET: Final = "auth_bridge_secret"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_WIZARD_OUTPUT: Final = "wizard_output"
CONF_ISSUE_TOKEN: Final = "issue_token"
CONF_COOKIES: Final = "cookies"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_ACCESS_TOKEN_EXPIRES_AT: Final = "access_token_expires_at"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]
