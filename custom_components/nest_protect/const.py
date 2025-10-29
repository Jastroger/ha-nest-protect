"""Constants for Nest Protect."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import Platform

LOGGER: logging.Logger = logging.getLogger(__package__)

DOMAIN: Final = "nest_protect"
ATTRIBUTION: Final = "Data provided by Google"

# Google OAuth authorize endpoint
OAUTH_AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"

# Wichtig:
# Ursprünglich wollten wir zwei Scopes anfragen:
#   - https://www.googleapis.com/auth/nest-account.readonly
#   - https://www.googleapis.com/auth/userinfo.email
#
# Der Scope "nest-account.readonly" ist aber für normale/neue Google Cloud Projekte
# nicht mehr freigeschaltet. Google antwortet dann mit:
#   invalid_scope
#
# Für unseren Flow reicht faktisch ein normales Google OAuth Token aus,
# plus userinfo.email zur Account-Zuordnung. Den Rest erledigen wir
# dann über den inoffiziellen Nest-Login-Proxy in client.py.
#
# Deshalb reduzieren wir die Scopes hier auf userinfo.email.
#
OAUTH_SCOPES: Final = [
    "https://www.googleapis.com/auth/userinfo.email",
]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]
