"""The Stromnetz Graz integration."""
from __future__ import annotations

import asyncio
import logging
import os
import ssl
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
)

import sngraz
from sngraz import StromNetzGraz, InvalidLogin

PLATFORMS = [Platform.SENSOR]
type SNGrazConfigEntry = ConfigEntry[StromNetzGraz]
_LOGGER = logging.getLogger(__name__)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(
        cafile=os.path.join(os.path.dirname(sngraz.__file__), "certchain.crt")
    )
    return ctx


async def async_create_api(
    hass: HomeAssistant, username: str, password: str
) -> StromNetzGraz:
    """Create the API client; sngraz would otherwise load certificates inside the event loop."""
    ctx = await hass.async_add_executor_job(_ssl_context)
    session = aiohttp.ClientSession(
        headers={aiohttp.hdrs.USER_AGENT: f"pySNGraz/{sngraz.__version__}"},
        connector=aiohttp.TCPConnector(ssl=ctx),
    )
    return StromNetzGraz(username, password, websession=session)


async def async_setup_entry(hass: HomeAssistant, entry: SNGrazConfigEntry) -> bool:
    """Set up Stromnetz Graz from a config entry."""
    conn = await async_create_api(
        hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )

    try:
        await conn.authenticate()
    except InvalidLogin as err:
        await conn.close_connection()
        raise ConfigEntryAuthFailed(f"Invalid login: {err}") from err
    except (asyncio.TimeoutError, aiohttp.ClientError) as err:
        await conn.close_connection()
        raise ConfigEntryNotReady(f"Error connecting: {err}") from err
    except Exception:
        await conn.close_connection()
        raise

    entry.runtime_data = conn

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SNGrazConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close_connection()

    return unload_ok
