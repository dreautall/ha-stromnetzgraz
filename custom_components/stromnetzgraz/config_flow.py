"""Config flow for Stromnetz Graz integration."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
import aiohttp

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
)
from homeassistant.data_entry_flow import FlowResult

from sngraz import StromNetzGraz, InvalidLogin
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stromnetz Graz."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}
        sn = StromNetzGraz(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
        try:
            await sn.authenticate()
        except asyncio.TimeoutError:
            errors["base"] = "timeout"
        except aiohttp.ClientError:
            errors["base"] = "cannot_connect"
        except InvalidLogin as err:
            errors["base"] = "invalid_login"
            _LOGGER.warning("Invalid Login: %s", err)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        await sn.close_connection()

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        return self.async_create_entry(title=sn._username, data=user_input)
