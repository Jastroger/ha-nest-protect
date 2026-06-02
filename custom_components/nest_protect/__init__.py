"""Nest Protect integration."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass

from aiohttp import ClientConnectorError, ClientError, ServerDisconnectedError
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .auth_bridge import (
    complete_auth_bridge_session,
    is_valid_cookie_header,
    is_valid_issue_token,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_ACCOUNT_TYPE,
    CONF_COOKIES,
    CONF_ISSUE_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    LOGGER,
    PLATFORMS,
)
from .pynest.client import NestClient
from .pynest.const import NEST_ENVIRONMENTS
from .pynest.enums import BucketType, Environment
from .pynest.exceptions import (
    BadCredentialsException,
    EmptyResponseException,
    NestServiceException,
    NotAuthenticatedException,
    PynestException,
)
from .pynest.models import (
    Bucket,
    FirstDataAPIResponse,
    GoogleAuthResponse,
    TopazBucket,
    WhereBucketValue,
)


@dataclass
class HomeAssistantNestProtectData:
    """Nest Protect data stored in the Home Assistant data object."""

    devices: dict[str, Bucket]
    areas: dict[str, str]
    client: NestClient
    subscription_task: asyncio.Task | None = None


class NestProtectAuthBridgeView(HomeAssistantView):
    """Receive auth bridge callback payloads."""

    url = "/api/nest_protect/auth_bridge/{session_id}"
    name = "api:nest_protect:auth_bridge"
    requires_auth = False

    async def post(self, request: web.Request, session_id: str) -> web.Response:
        """Handle auth bridge credential callback."""
        hass = request.app["hass"]

        try:
            payload = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid_json"}, status=400)

        secret = payload.get("secret")
        issue_token = payload.get(CONF_ISSUE_TOKEN)
        cookies = payload.get(CONF_COOKIES)
        if (
            not isinstance(secret, str)
            or not isinstance(issue_token, str)
            or not isinstance(cookies, str)
        ):
            return web.json_response({"error": "missing_fields"}, status=400)
        if not secret or not issue_token or not cookies:
            return web.json_response({"error": "missing_fields"}, status=400)
        if not is_valid_issue_token(issue_token):
            return web.json_response({"error": "invalid_issue_token"}, status=400)
        if not is_valid_cookie_header(cookies):
            return web.json_response({"error": "invalid_cookie_header"}, status=400)

        complete_status = complete_auth_bridge_session(
            hass,
            session_id,
            secret,
            {
                CONF_ISSUE_TOKEN: issue_token,
                CONF_COOKIES: cookies,
            },
        )
        if complete_status == "invalid_session":
            return web.json_response({"error": "invalid_session"}, status=403)
        if complete_status == "expired_session":
            return web.json_response({"error": "expired_session"}, status=410)
        if complete_status == "already_completed":
            return web.json_response({"error": "already_completed"}, status=409)

        return web.json_response({"ok": True})


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Nest Protect component."""
    if hass.http is not None and "http" in hass.config.components:
        hass.http.register_view(NestProtectAuthBridgeView())

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old Config entries."""
    LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version < 3:
        hass.config_entries.async_update_entry(
            config_entry,
            data={
                **config_entry.data,
                CONF_ACCOUNT_TYPE: config_entry.data.get(
                    CONF_ACCOUNT_TYPE, Environment.PRODUCTION
                ),
            },
            version=3,
        )

    LOGGER.debug("Migration to version %s successful", config_entry.version)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Nest Protect from a config entry."""
    issue_token = entry.data.get(CONF_ISSUE_TOKEN)
    cookies = entry.data.get(CONF_COOKIES)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    stored_access_token, stored_expires_at = _get_stored_access_token(entry)

    session = async_get_clientsession(hass)
    account_type = entry.data.get(CONF_ACCOUNT_TYPE, Environment.PRODUCTION)
    client = NestClient(session=session, environment=NEST_ENVIRONMENTS[account_type])

    auth = None
    nest = None

    try:
        if (
            stored_access_token
            and stored_expires_at
            and _is_access_token_valid(stored_expires_at)
        ):
            try:
                nest = await client.authenticate(stored_access_token)
            except (TimeoutError, ClientError, PynestException) as exception:
                LOGGER.debug(
                    "Stored access token authentication failed, falling back.",
                    exc_info=exception,
                )

        if nest is None:
            # Using user-retrieved cookies for authentication
            if issue_token and cookies:
                auth = await client.get_access_token_from_cookies(issue_token, cookies)
            # Using refresh_token from legacy authentication method
            elif refresh_token:
                auth = await client.get_access_token_from_refresh_token(refresh_token)
            else:
                raise ConfigEntryAuthFailed(
                    "No authentication data available for Nest Protect."
                )

            _store_access_token(hass, entry, auth)
            nest = await client.authenticate(auth.access_token)
    except (TimeoutError, ClientError) as exception:
        raise ConfigEntryNotReady from exception
    except BadCredentialsException as exception:
        if "USER_LOGGED_OUT" in str(exception):
            LOGGER.warning(
                "Nest Protect authentication expired. Starting reauthentication."
            )
            hass.config_entries.async_start_reauth(entry)
        raise ConfigEntryAuthFailed from exception
    except Exception as exception:  # pylint: disable=broad-except
        LOGGER.exception("Unknown exception.")
        raise ConfigEntryNotReady from exception

    data = await client.get_first_data(nest.access_token, nest.userid)

    device_buckets: list[Bucket] = []
    areas: dict[str, str] = {}

    for bucket in data.updated_buckets:
        # Nest Protect
        if bucket.type == BucketType.TOPAZ:
            device_buckets.append(bucket)
        # Temperature Sensors
        elif bucket.type == BucketType.KRYPTONITE:
            device_buckets.append(bucket)

        # Areas
        if bucket.type == BucketType.WHERE and isinstance(
            bucket.value, WhereBucketValue
        ):
            bucket_value = bucket.value
            for area in bucket_value.wheres:
                areas[area.where_id] = area.name

    devices: dict[str, Bucket] = {b.object_key: b for b in device_buckets}

    entry_data = HomeAssistantNestProtectData(
        devices=devices,
        areas=areas,
        client=client,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Subscribe for real-time updates
    entry_data.subscription_task = asyncio.create_task(
        _async_subscribe_for_data(hass, entry, data)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Cancel subscription task only after successful platform unload
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            entry_data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]
            if entry_data.subscription_task:
                entry_data.subscription_task.cancel()
                try:
                    await entry_data.subscription_task
                except asyncio.CancelledError:
                    # Task cancellation is expected during unload; ignore.
                    pass
            hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_subscribe_for_data(
    hass: HomeAssistant, entry: ConfigEntry, data: FirstDataAPIResponse
):
    """Subscribe for new data."""
    while entry.entry_id in hass.data.get(DOMAIN, {}):
        entry_data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]

        try:
            await _async_subscribe_once(hass, entry_data, data)
        except ServerDisconnectedError:
            LOGGER.debug("Subscriber: server disconnected.")
            await asyncio.sleep(5)
        except asyncio.exceptions.TimeoutError:
            LOGGER.debug("Subscriber: session timed out.")
            await asyncio.sleep(5)
        except ClientConnectorError:
            LOGGER.debug("Subscriber: cannot connect to host.")
            await asyncio.sleep(30)
        except EmptyResponseException:
            LOGGER.debug("Subscriber: Nest Service sent empty response.")
            await asyncio.sleep(5)
        except NotAuthenticatedException:
            LOGGER.debug("Subscriber: 401 exception.")
            await entry_data.client.get_access_token()
            await entry_data.client.authenticate(entry_data.client.auth.access_token)
        except BadCredentialsException:
            LOGGER.debug(
                "Bad credentials detected. Please re-authenticate the Nest Protect integration."
            )
            hass.config_entries.async_start_reauth(entry)
            return
        except NestServiceException:
            LOGGER.debug("Subscriber: Nest Service error. Updates paused for 2 minutes.")
            await asyncio.sleep(60 * 2)
        except PynestException:
            LOGGER.exception(
                "Unknown pynest exception. Please create an issue on GitHub with your logfile. Updates paused for 1 minute."
            )
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            LOGGER.debug("Subscriber: task cancelled, stopping subscription.")
            raise
        except Exception:  # pylint: disable=broad-except
            LOGGER.exception(
                "Unknown exception. Please create an issue on GitHub with your logfile. Updates paused for 5 minutes."
            )
            await asyncio.sleep(60 * 5)


async def _async_subscribe_once(
    hass: HomeAssistant,
    entry_data: HomeAssistantNestProtectData,
    data: FirstDataAPIResponse,
) -> None:
    """Fetch one long-poll subscription update and apply it."""
    await asyncio.sleep(0)

    if not entry_data.client.nest_session or entry_data.client.nest_session.is_expired():
        LOGGER.debug("Subscriber: authenticate for new Nest session")

    if not entry_data.client.auth or entry_data.client.auth.is_expired():
        LOGGER.debug("Subscriber: retrieving new Google access token")
        auth = await entry_data.client.get_access_token()
        entry_data.client.nest_session = await entry_data.client.authenticate(
            auth.access_token
        )

    result = await entry_data.client.subscribe_for_data(
        entry_data.client.nest_session.access_token,
        entry_data.client.nest_session.userid,
        data.service_urls["urls"]["transport_url"],
        data.updated_buckets,
    )

    for bucket in result["objects"]:
        key = bucket["object_key"]

        if key.startswith("topaz."):
            topaz = TopazBucket(**bucket)
            entry_data.devices[key] = topaz
            async_dispatcher_send(hass, key, topaz)

        if key.startswith("where."):
            bucket_value = Bucket(**bucket).value

            for area in bucket_value["wheres"]:
                entry_data.areas[area["where_id"]] = area["name"]

        if key.startswith("kryptonite."):
            kryptonite = Bucket(**bucket)
            entry_data.devices[key] = kryptonite
            async_dispatcher_send(hass, key, kryptonite)

    buckets = {d["object_key"]: d for d in result["objects"]}
    LOGGER.debug(buckets)

    objects = [
        dict(vars(b), **buckets.get(b.object_key, {})) for b in data.updated_buckets
    ]

    data.updated_buckets = [
        Bucket(
            object_key=bucket["object_key"],
            object_revision=bucket["object_revision"],
            object_timestamp=bucket["object_timestamp"],
            value=bucket["value"],
            type=bucket["type"],
        )
        for bucket in objects
    ]


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


def _get_stored_access_token(
    entry: ConfigEntry,
) -> tuple[str | None, datetime.datetime | None]:
    access_token = entry.data.get(CONF_ACCESS_TOKEN) or entry.options.get(
        CONF_ACCESS_TOKEN
    )
    expires_at_raw = entry.data.get(CONF_ACCESS_TOKEN_EXPIRES_AT) or entry.options.get(
        CONF_ACCESS_TOKEN_EXPIRES_AT
    )
    if not access_token or not expires_at_raw:
        return None, None

    try:
        expires_at = datetime.datetime.fromisoformat(expires_at_raw)
    except ValueError:
        LOGGER.debug("Stored access token expiry is invalid, ignoring value.")
        return None, None

    return access_token, expires_at


def _is_access_token_valid(expires_at: datetime.datetime) -> bool:
    return expires_at > datetime.datetime.now() + datetime.timedelta(minutes=2)


def _store_access_token(
    hass: HomeAssistant, entry: ConfigEntry, auth: GoogleAuthResponse
) -> None:
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_ACCESS_TOKEN: auth.access_token,
            CONF_ACCESS_TOKEN_EXPIRES_AT: auth.expiry_date.isoformat(),
        },
    )
