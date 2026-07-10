"""Config flow for SmartPoolConnect Owner."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, SmartPoolConnectClient, SmartPoolConnectError
from .const import CONF_POOL_ID, DOMAIN


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate user input by attempting a login and first status fetch."""
    client = SmartPoolConnectClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        pool_id=data[CONF_POOL_ID],
    )
    try:
        await client.async_login()
    finally:
        await client.close()


class SmartPoolConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartPoolConnect Owner."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POOL_ID])
            self._abort_if_unique_id_configured()

            try:
                await validate_input(self.hass, user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except SmartPoolConnectError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="SmartPoolConnect Owner",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_POOL_ID): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
