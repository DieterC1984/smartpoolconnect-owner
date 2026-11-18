"""Coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    AuthenticationError,
    PoolStatus,
    SmartPoolConnectClient,
    SmartPoolConnectError,
    TransientServerError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)
_HISTORICAL_STORAGE_VERSION = 1


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
        self._historical_store = Store[dict[str, str]](
            hass,
            _HISTORICAL_STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.historical",
        )
        self._historical_cache_loaded = False
        self._stored_last_backwash: str | None = None

    async def _async_load_historical_cache(self) -> None:
        """Restore the last backwash date once before the first network refresh."""

        if self._historical_cache_loaded:
            return
        self._historical_cache_loaded = True
        try:
            stored = await self._historical_store.async_load()
        except Exception:
            _LOGGER.warning("Could not load historical sensor cache", exc_info=True)
            return
        if not isinstance(stored, dict):
            return
        value = stored.get("last_backwash_at")
        if isinstance(value, str):
            self.client.restore_last_backwash(value)
            self._stored_last_backwash = value

    async def _async_save_historical_cache(self, data: PoolStatus) -> None:
        """Persist only a changed, validated last-backwash timestamp."""

        if data.last_backwash_at is None:
            return
        value = data.last_backwash_at.isoformat()
        if value == self._stored_last_backwash:
            return
        try:
            await self._historical_store.async_save({"last_backwash_at": value})
        except Exception:
            _LOGGER.warning("Could not save historical sensor cache", exc_info=True)
            return
        self._stored_last_backwash = value

    async def _async_update_data(self) -> PoolStatus:
        """Fetch new data from SmartPoolConnect.

        Temporary SmartPoolConnect or network failures should not make all
        entities unavailable after a previous successful update. When a refresh
        fails and cached data exists, Home Assistant keeps showing the last
        known values and the coordinator automatically recovers on the next
        successful refresh.
        """
        await self._async_load_historical_cache()
        try:
            data = await self.client.async_get_status()

            if data is not None:
                self._last_good_data = data
                await self._async_save_historical_cache(data)

            return data

        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except TransientServerError as err:
            if self._last_good_data is not None:
                _LOGGER.debug(
                    "Temporary SmartPoolConnect backend error, keeping previous values: %s",
                    err,
                )
                return self._last_good_data

            raise UpdateFailed(str(err)) from err

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
