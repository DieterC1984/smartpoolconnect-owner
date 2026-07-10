"""Coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PoolStatus, SmartPoolConnectClient, SmartPoolConnectError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SmartPoolConnectCoordinator(DataUpdateCoordinator[PoolStatus]):
    """SmartPoolConnect data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SmartPoolConnectClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> PoolStatus:
        try:
            return await self.client.async_get_status()
        except SmartPoolConnectError as err:
            raise UpdateFailed(str(err)) from err
