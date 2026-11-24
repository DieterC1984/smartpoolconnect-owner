"""Cover platform for SmartPoolConnect pool cover/deck."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .const import CONF_POOL_ID, DOMAIN
from .entity import SmartPoolConnectEntity


def _repair_integration_disabled_covco_cover(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
) -> None:
    """Enable a validated Covco cover left disabled by an older release.

    ``entity_registry_enabled_default`` applies only on first registration.
    Older releases registered this same unique ID disabled, so changing the
    default later cannot make the entity available. Only entries disabled by
    the integration are repaired; an explicit user choice remains untouched.
    """

    status = entry.runtime_data.data
    if status is None or "covco_cover" not in status.capabilities:
        return

    registry = er.async_get(hass)
    unique_id = f"{entry.data[CONF_POOL_ID]}_cover"
    entity_id = registry.async_get_entity_id("cover", DOMAIN, unique_id)
    if entity_id is None:
        return
    registry_entry = registry.async_get(entity_id)
    if (
        registry_entry is not None
        and registry_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    ):
        registry.async_update_entity(entity_id, disabled_by=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up control only for a validated, write-capable cover."""

    status = entry.runtime_data.data
    if status is None or "cover_control" not in status.capabilities:
        return
    _repair_integration_disabled_covco_cover(hass, entry)
    async_add_entities([PoolCover(entry.runtime_data)])


class PoolCover(SmartPoolConnectEntity, CoverEntity):
    _attr_translation_key = "cover"
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
    _attr_entity_registry_enabled_default = True

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

    @property
    def current_cover_position(self) -> int | None:
        """Return the validated Covco encoder position when available."""

        position = self.coordinator.data.covco_cover_position
        return round(position) if position is not None else None

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_cover_open()
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_cover_close()
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_cover_stop()
        await self.coordinator.async_request_refresh()
