"""Coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

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
        self._last_good_data: PoolStatus | None = None

    async def _async_update_data(self) -> PoolStatus:
        """Fetch new data from SmartPoolConnect.

        Temporary SmartPoolConnect or network failures should not make all
        entities unavailable after a previous successful update. When a refresh
        fails and cached data exists, Home Assistant keeps showing the last
        known values and the coordinator automatically recovers on the next
        successful refresh.
        """
        try:
            data = await self.client.async_get_status()

            if data is not None:
                self._last_good_data = data

            return data

        except SmartPoolConnectError as err:
            if self._last_good_data is not None:
                _LOGGER.warning(
                    "SmartPoolConnect update failed, keeping previous values: %s",
                    err,
                )
                return self._last_good_data

            raise UpdateFailed(str(err)) from err

        except Exception as err:
            if self._last_good_data is not None:
                _LOGGER.warning(
                    "Unexpected SmartPoolConnect update error, keeping previous values: %s",
                    err,
                )
                return self._last_good_data

            raise UpdateFailed(str(err)) from err
