"""Config flow for SmartPoolConnect Owner Portal."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import (
    AuthenticationError,
    SmartPoolConnectClient,
    SmartPoolConnectError,
)
from .const import CONF_POOL_ID, CONF_SESSION_COOKIE, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_POOL_ID): str,
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_SESSION_COOKIE): str,
    }
)


class SmartPoolConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:

        errors: dict[str, str] = {}

        if user_input is not None:
            client = SmartPoolConnectClient(
                user_input.get(CONF_USERNAME),
                user_input.get(CONF_PASSWORD),
                pool_id=user_input[CONF_POOL_ID],
                session_cookie=user_input.get(CONF_SESSION_COOKIE),
            )

            try:
                _LOGGER.warning(
                    "Starting SmartPool validation for pool %s",
                    user_input[CONF_POOL_ID],
                )

                await client.async_login()

                _LOGGER.warning(
                    "Login completed successfully"
                )

                status = await client.async_get_status()

                _LOGGER.warning(
                    "Status request completed successfully"
                )

            except AuthenticationError as err:
                _LOGGER.exception(
                    "Authentication failed"
                )
                errors["base"] = "invalid_auth"

            except SmartPoolConnectError as err:
                _LOGGER.exception(
                    "SmartPool connection failed: %s",
                    err,
                )
                errors["base"] = "cannot_connect"

            except Exception as err:
                _LOGGER.exception(
                    "Unexpected setup error: %s",
                    err,
                )
                errors["base"] = "unknown"

            else:
                await self.async_set_unique_id(
                    user_input[CONF_POOL_ID]
                )

                self._abort_if_unique_id_configured()

                data = {
                    CONF_POOL_ID: user_input[CONF_POOL_ID],
                }

                if user_input.get(CONF_USERNAME):
                    data[CONF_USERNAME] = user_input[CONF_USERNAME]

                if user_input.get(CONF_PASSWORD):
                    data[CONF_PASSWORD] = user_input[CONF_PASSWORD]

                if user_input.get(CONF_SESSION_COOKIE):
                    data[CONF_SESSION_COOKIE] = user_input[
                        CONF_SESSION_COOKIE
                    ]

                return self.async_create_entry(
                    title=status.name
                    or f"Pool {user_input[CONF_POOL_ID]}",
                    data=data,
                )

            finally:
                await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
