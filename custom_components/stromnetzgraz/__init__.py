"""The Stromnetz Graz integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import os
import ssl
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_BASE,
    CONF_USERNAME,
    CONF_PASSWORD,
)

from . import sngraz
from .sngraz import StromNetzGraz, InvalidLogin

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
        # sngraz returns False (instead of raising) when the login request fails.
        if not await conn.authenticate():
            raise ConfigEntryNotReady("Login request failed")
        # This fills in all installations and meters.
        await conn.update_info()
        if not conn.get_installations():
            raise ConfigEntryNotReady("No installations returned")
        await _async_prepare_meters(hass, entry, conn)
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


async def _async_prepare_meters(
    hass: HomeAssistant, entry: SNGrazConfigEntry, conn: StromNetzGraz
) -> None:
    """Fix each meter's first reading date and store base readings that are missing."""
    # Copy: mutating the stored dict in place would hide the change from async_update_entry.
    base_readings = dict(entry.data.get(CONF_BASE) or {})
    changed = False
    for installation in conn.get_installations():
        for meter in installation.get_meters():
            # sngraz rounds readingsAvailableSince down to the hour, but the API rejects
            # (HTTP 400) any fromDate before it; round up to the next hour instead.
            if (first := await meter._get_first_reading_date()) is not None:
                meter._first_reading_date = first.replace(second=0) + timedelta(hours=1)

            if str(meter.id) in base_readings:
                continue
            # Fails when the API sends no meter reading (MR); retried on the next setup.
            if (base_reading := await meter.get_first_reading()) is None:
                _LOGGER.warning(
                    "could not get first reading for %s, summing consumption instead",
                    meter.id,
                )
                continue
            base_readings[str(meter.id)] = base_reading
            changed = True

    if changed:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_BASE: base_readings}
        )


async def async_unload_entry(hass: HomeAssistant, entry: SNGrazConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close_connection()

    return unload_ok
