"""Nest Protect integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientConnectorError, ClientError, ServerDisconnectedError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_ACCOUNT_TYPE,
    DOMAIN,
    LOGGER,
    PLATFORMS,
)
from .oauth import (
    async_ensure_oauth_implementation,
    async_get_nest_oauth_session,
    async_token_from_refresh_token,
    implementation_domain,
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
from .pynest.models import Bucket, FirstDataAPIResponse, TopazBucket, WhereBucketValue


@dataclass
class HomeAssistantNestProtectData:
    """Nest Protect data stored in the Home Assistant data object."""

    devices: dict[str, Bucket]
    areas: dict[str, str]
    client: NestClient
    oauth_session: "NestProtectOAuth2Session"


async def async_ensure_token_data(
    hass: HomeAssistant, account_type: Environment | str, entry_data: dict[str, Any]
) -> dict[str, Any]:
    """Build token data for migrated entries."""

    env = Environment(account_type)

    await async_ensure_oauth_implementation(hass, env)

    refresh_token = entry_data.get("refresh_token", "")
    try:
        token = (
            await async_token_from_refresh_token(hass, env, refresh_token)
            if refresh_token
            else _empty_token(refresh_token)
        )
    except ConfigEntryAuthFailed:
        LOGGER.debug("Failed to migrate refresh token for %s", env, exc_info=True)
        token = _empty_token(refresh_token)

    return {
        CONF_ACCOUNT_TYPE: env,
        "auth_implementation": implementation_domain(env),
        "token": token,
    }


def _empty_token(refresh_token: str) -> dict[str, Any]:
    """Return an empty token payload to trigger re-auth."""

    return {
        "access_token": "",
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "scope": "",
        "id_token": "",
        "expires_in": 0,
        "expires_at": 0,
    }


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old Config entries."""
    LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        entry_data = {**config_entry.data}
        entry_data[CONF_ACCOUNT_TYPE] = Environment.PRODUCTION

        config_entry.data = {**entry_data}
        config_entry.version = 2

    if config_entry.version < 4:
        current_data = {**config_entry.data}
        account_type = Environment(
            current_data.get(CONF_ACCOUNT_TYPE, Environment.PRODUCTION)
        )

        implementation = await async_ensure_token_data(hass, account_type, current_data)

        hass.config_entries.async_update_entry(
            config_entry, data=implementation, version=4
        )

    LOGGER.debug("Migration to version %s successful", config_entry.version)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Nest Protect from a config entry."""
    session = async_create_clientsession(hass)
    account_type = Environment(entry.data[CONF_ACCOUNT_TYPE])
    client = NestClient(session=session, environment=NEST_ENVIRONMENTS[account_type])

    oauth_session = await async_get_nest_oauth_session(hass, entry)

    try:
        access_token = await oauth_session.async_get_access_token()
        nest = await client.ensure_authenticated(access_token)
    except ConfigEntryAuthFailed:
        raise
    except (TimeoutError, ClientError) as exception:
        raise ConfigEntryNotReady from exception
    except BadCredentialsException as exception:
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = HomeAssistantNestProtectData(
        devices=devices,
        areas=areas,
        client=client,
        oauth_session=oauth_session,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Subscribe for real-time updates
    _register_subscribe_task(hass, entry, data)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


def _register_subscribe_task(
    hass: HomeAssistant, entry: ConfigEntry, data: FirstDataAPIResponse
) -> None:
    """Register the background subscription task and ensure it is cleaned up."""

    task = hass.async_create_background_task(
        _async_subscribe_for_data(hass, entry, data),
        name="nest_protect-subscribe",
    )

    entry.async_on_unload(task.cancel)


async def _async_subscribe_for_data(
    hass: HomeAssistant, entry: ConfigEntry, data: FirstDataAPIResponse
):
    """Subscribe for new data."""
    entry_data: HomeAssistantNestProtectData = hass.data[DOMAIN][entry.entry_id]

    try:
        access_token = await entry_data.oauth_session.async_get_access_token()
        nest = await entry_data.client.ensure_authenticated(access_token)

        # Subscribe to Google Nest subscribe endpoint
        result = await entry_data.client.subscribe_for_data(
            nest.access_token,
            nest.userid,
            data.service_urls["urls"]["transport_url"],
            data.updated_buckets,
        )

        # TODO write this data away in a better way, best would be to directly model API responses in client
        for bucket in result["objects"]:
            key = bucket["object_key"]

            # Nest Protect
            if key.startswith("topaz."):
                topaz = TopazBucket(**bucket)
                entry_data.devices[key] = topaz

                # TODO investigate if we want to use dispatcher, or get data from entry data in sensors
                async_dispatcher_send(hass, key, topaz)

            # Areas
            if key.startswith("where."):
                bucket_value = Bucket(**bucket).value

                for area in bucket_value["wheres"]:
                    entry_data.areas[area["where_id"]] = area["name"]

            # Temperature Sensors
            if key.startswith("kryptonite."):
                kryptonite = Bucket(**bucket)
                entry_data.devices[key] = kryptonite

                async_dispatcher_send(hass, key, kryptonite)

        # Update buckets with new data, to only receive new updates
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

        _register_subscribe_task(hass, entry, data)
    except ServerDisconnectedError:
        LOGGER.debug("Subscriber: server disconnected.")
        _register_subscribe_task(hass, entry, data)

    except asyncio.exceptions.TimeoutError:
        LOGGER.debug("Subscriber: session timed out.")
        _register_subscribe_task(hass, entry, data)

    except ClientConnectorError:
        LOGGER.debug("Subscriber: cannot connect to host.")
        _register_subscribe_task(hass, entry, data)

    except EmptyResponseException:
        LOGGER.debug("Subscriber: Nest Service sent empty response.")
        _register_subscribe_task(hass, entry, data)

    except ConfigEntryAuthFailed:
        LOGGER.debug("Subscriber: OAuth credentials invalid.")
        raise

    except NotAuthenticatedException:
        LOGGER.debug("Subscriber: 401 exception.")
        # Renewing access token
        access_token = await entry_data.oauth_session.async_get_access_token()
        await entry_data.client.ensure_authenticated(access_token)
        _register_subscribe_task(hass, entry, data)

    except BadCredentialsException as exception:
        LOGGER.debug(
            "Bad credentials detected. Please re-authenticate the Nest Protect integration."
        )
        raise ConfigEntryAuthFailed from exception

    except NestServiceException:
        LOGGER.debug("Subscriber: Nest Service error. Updates paused for 2 minutes.")

        await asyncio.sleep(60 * 2)
        _register_subscribe_task(hass, entry, data)

    except PynestException:
        LOGGER.exception(
            "Unknown pynest exception. Please create an issue on GitHub with your logfile. Updates paused for 1 minute."
        )

        # Wait a minute before retrying
        await asyncio.sleep(60)
        _register_subscribe_task(hass, entry, data)

    except Exception:  # pylint: disable=broad-except
        # Wait 5 minutes before retrying
        await asyncio.sleep(60 * 5)
        _register_subscribe_task(hass, entry, data)

        LOGGER.exception(
            "Unknown exception. Please create an issue on GitHub with your logfile. Updates paused for 5 minutes."
        )


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True
