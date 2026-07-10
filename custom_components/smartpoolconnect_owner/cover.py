"""Cover platform for SmartPoolConnect pool cover/deck."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .entity import SmartPoolConnectEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PoolCover(entry.runtime_data)])


class PoolCover(SmartPoolConnectEntity, CoverEntity):
    _attr_translation_key = "cover"
    _attr_device_class = CoverDeviceClass.SHADE

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator, "cover")
        self._attr_name = "Pool Cover"

    @property
    def is_closed(self) -> bool | None:
        state = self.coordinator.data.cover_state

        if state in ("opening", "closing"):
            return None

        if state == "closed":
            return True

        if state == "open":
            return False

        return None

    @property
    def is_opening(self) -> bool:
        return self.coordinator.data.cover_state == "opening"

    @property
    def is_closing(self) -> bool:
        return self.coordinator.data.cover_state == "closing"

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_cover_open()
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_cover_close()
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_cover_stop()
        await self.coordinator.async_request_refresh()