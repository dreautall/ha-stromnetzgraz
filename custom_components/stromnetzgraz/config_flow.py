"""Config flow for Stromnetz Graz integration."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
import aiohttp
from datetime import timedelta, datetime

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from homeassistant.components.input_number import DOMAIN as INPUT_NUMBER_DOMAIN
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN

from homeassistant.components.recorder import get_instance
import homeassistant.util.dt as dt_util

from sngraz import StromNetzGraz, InvalidLogin
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

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

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            for entity in user_input:
                print(entity)
                print(self.hass.states.get(user_input[entity]))

            return self.async_create_entry(title="", data=user_input)

        entities = await get_instance(self.hass).async_add_executor_job(
            self.hass.states.async_entity_ids
        )
        data_schema = vol.Schema({})
        for entity in entities:
            if not entity.startswith("sensor.meter_consumption_"):
                continue
            meter_id = entity[25:]
            data_schema = data_schema.extend(
                {
                    vol.Optional(
                        meter_id,
                        default=self.config_entry.options.get(meter_id),
                    ): selector.EntitySelector(
                        selector.EntityFilterSelectorConfig(
                            domain=[SENSOR_DOMAIN, NUMBER_DOMAIN, INPUT_NUMBER_DOMAIN],
                        )
                    )
                }
            )

        return self.async_show_form(step_id="init", data_schema=data_schema)
