"""Config flow for Stromnetz Graz integration."""
from __future__ import annotations

from collections.abc import Mapping
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
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .sngraz import InvalidLogin, SNGrazError
from . import async_create_api
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

        await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
        self._abort_if_unique_id_configured()

        errors = await self._async_validate(
            user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
        )
        if errors:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

    async def _async_validate(self, username: str, password: str) -> dict[str, str]:
        """Try to log in; returns form errors (empty on success)."""
        errors: dict[str, str] = {}
        sn = await async_create_api(self.hass, username, password)
        try:
            await sn.authenticate()
        except asyncio.TimeoutError:
            errors["base"] = "timeout"
        except (aiohttp.ClientError, SNGrazError):
            errors["base"] = "cannot_connect"
        except InvalidLogin as err:
            errors["base"] = "invalid_login"
            _LOGGER.warning("Invalid Login: %s", err)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        await sn.close_connection()
        return errors

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Start re-authentication after the stored login was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Pick a price entity per meter; its history is turned into a cost statistic."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        meters = [
            meter
            for installation in self.config_entry.runtime_data.get_installations()
            for meter in installation.get_meters()
        ]
        price_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "number", "input_number"])
        )
        # suggested_value, not default: a cleared field must stay cleared.
        schema = vol.Schema(
            {
                vol.Optional(
                    str(meter.id),
                    description={
                        "suggested_value": self.config_entry.options.get(str(meter.id))
                    },
                ): price_selector
                for meter in meters
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "meters": "\n".join(f"- `{m.id}`: {m._short_name}" for m in meters)
            },
        )
