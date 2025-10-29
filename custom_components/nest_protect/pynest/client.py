"""PyNest API Client."""

from __future__ import annotations

import logging
from random import randint
import time
from types import TracebackType
from typing import Any, cast

from aiohttp import ClientSession, ClientTimeout, ContentTypeError, FormData

from .const import (
    APP_LAUNCH_URL_FORMAT,
    DEFAULT_NEST_ENVIRONMENT,
    NEST_AUTH_URL_JWT,
    NEST_REQUEST,
    USER_AGENT,
)
from .exceptions import (
    BadGatewayException,
    EmptyResponseException,
    GatewayTimeoutException,
    NotAuthenticatedException,
    PynestException,
)
from .models import (
    Bucket,
    FirstDataAPIResponse,
    NestAuthResponse,
    NestEnvironment,
    NestResponse,
)

_LOGGER = logging.getLogger(__package__)


class NestClient:
    """Interface class for the Nest API."""

    nest_session: NestResponse | None = None
    session: ClientSession
    transport_url: str | None = None
    environment: NestEnvironment

    def __init__(
        self,
        session: ClientSession | None = None,
        environment: NestEnvironment = DEFAULT_NEST_ENVIRONMENT,
    ) -> None:
        """Initialize NestClient."""

        self.session = session if session else ClientSession()
        self.environment = environment

    async def __aenter__(self) -> NestClient:
        """__aenter__."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """__aexit__."""
        await self.session.close()

    async def ensure_authenticated(self, access_token: str) -> NestResponse:
        """Ensure the client has a valid Nest session."""

        if self.nest_session and not self.nest_session.is_expired():
            return self.nest_session

        if not access_token:
            raise NotAuthenticatedException("Unable to retrieve Google access token")

        self.nest_session = await self.authenticate(access_token)

        return self.nest_session

    async def authenticate(self, access_token: str) -> NestResponse:
        """Start a new Nest session with an access token."""

        async with self.session.post(
            NEST_AUTH_URL_JWT,
            data=FormData(
                {
                    "embed_google_oauth_access_token": True,
                    "expire_after": "3600s",
                    "google_oauth_access_token": access_token,
                    "policy_id": "authproxy-oauth-policy",
                }
            ),
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
                "Referer": self.environment.host,
            },
        ) as response:
            result = await response.json()
            nest_auth = NestAuthResponse(**result)

        async with self.session.get(
            self.environment.host + "/session",
            headers={
                "Authorization": f"Basic {nest_auth.jwt}",
                "cookie": "G_ENABLED_IDPS=google; eu_cookie_accepted=1; viewer-volume=0.5; cztoken="
                + (nest_auth.jwt if nest_auth.jwt else ""),
            },
        ) as response:
            try:
                nest_response = await response.json()
            except ContentTypeError as exception:
                nest_response = await response.text()

                raise PynestException(
                    f"{response.status} error while authenticating - {nest_response}. Please create an issue on GitHub."
                ) from exception

            # Change variable names since Python cannot handle vars that start with a number
            if nest_response.get("2fa_state"):
                nest_response["_2fa_state"] = nest_response.pop("2fa_state")
            if nest_response.get("2fa_enabled"):
                nest_response["_2fa_enabled"] = nest_response.pop("2fa_enabled")
            if nest_response.get("2fa_state_changed"):
                nest_response["_2fa_state_changed"] = nest_response.pop(
                    "2fa_state_changed"
                )

            if nest_response.get("error"):
                _LOGGER.error("Authentication error: %s", nest_response.get("error"))

                raise PynestException(
                    f"{response.status} error while authenticating - {nest_response}."
                )

            try:
                self.nest_session = NestResponse(**nest_response)
            except Exception as exception:
                nest_response = await response.text()

                if result.get("error"):
                    _LOGGER.error("Could not interpret Nest response")

                raise PynestException(
                    f"{response.status} error while authenticating - {nest_response}. Please create an issue on GitHub."
                ) from exception

            return self.nest_session

    async def get_first_data(
        self, nest_access_token: str, user_id: str, request: dict = NEST_REQUEST
    ) -> FirstDataAPIResponse:
        """Get first data."""
        async with self.session.post(
            APP_LAUNCH_URL_FORMAT.format(host=self.environment.host, user_id=user_id),
            json=request,
            headers={
                "Authorization": f"Basic {nest_access_token}",
                "X-nl-user-id": user_id,
                "X-nl-protocol-version": str(1),
            },
        ) as response:
            result = await response.json()

            if result.get("2fa_enabled"):
                result["_2fa_enabled"] = result.pop("2fa_enabled")

            if result.get("error"):
                _LOGGER.debug("Received error from Nest service", await response.text())

                raise PynestException(
                    f"{response.status} error while subscribing - {result}"
                )

            result = FirstDataAPIResponse(**result)

            self.transport_url = result.service_urls["urls"]["transport_url"]

            return result

    async def subscribe_for_data(
        self,
        nest_access_token: str,
        user_id: str,
        transport_url: str,
        updated_buckets: dict,
    ) -> Any:
        """Subscribe for data."""
        timeout = 600

        objects = []
        for bucket in updated_buckets:
            bucket = cast(Bucket, bucket)
            objects.append(
                {
                    "object_key": bucket.object_key,
                    "object_revision": bucket.object_revision,
                    "object_timestamp": bucket.object_timestamp,
                }
            )

        # TODO throw better exceptions
        async with self.session.post(
            f"{transport_url}/v6/subscribe",
            timeout=ClientTimeout(total=timeout),
            json={
                "objects": objects,
                # "timeout": timeout,
                # "sessionID": f"ios-${user_id}.{random}.{epoch}",
            },
            headers={
                "Authorization": f"Basic {nest_access_token}",
                "X-nl-user-id": user_id,
                "X-nl-protocol-version": str(1),
            },
        ) as response:
            _LOGGER.debug("Data received via subscriber (status: %s)", response.status)

            if response.status == 401:
                raise NotAuthenticatedException(await response.text())

            if response.status == 504:
                raise GatewayTimeoutException(await response.text())

            if response.status == 502:
                raise BadGatewayException(await response.text())

            if response.status == 200 and response.content_type == "text/plain":
                raise EmptyResponseException(await response.text())

            try:
                result = await response.json()
            except ContentTypeError as error:
                result = await response.text()

                raise PynestException(
                    f"{response.status} error while subscribing - {result}"
                ) from error

            # TODO type object
            return result

    async def update_objects(
        self,
        nest_access_token: str,
        user_id: str,
        transport_url: str,
        objects_to_update: dict,
    ) -> Any:
        """Subscribe for data."""

        epoch = int(time.time())
        random = str(randint(100, 999))

        # TODO throw better exceptions
        async with self.session.post(
            f"{transport_url}/v6/put",
            json={
                "session": f"ios-${user_id}.{random}.{epoch}",
                "objects": objects_to_update,
            },
            headers={
                "Authorization": f"Basic {nest_access_token}",
                "X-nl-user-id": user_id,
                "X-nl-protocol-version": str(1),
            },
        ) as response:
            if response.status == 401:
                raise NotAuthenticatedException(await response.text())

            try:
                result = await response.json()
            except ContentTypeError:
                result = await response.text()

                raise PynestException(
                    f"{response.status} error while subscribing - {result}"
                )

            # TODO type object

            return result
