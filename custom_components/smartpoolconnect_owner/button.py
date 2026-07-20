"""Button entities."""
from __future__ import annotations
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .entity import SmartPoolConnectEntity
async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([StartBackwashButton(entry.runtime_data)])
class StartBackwashButton(SmartPoolConnectEntity, ButtonEntity):
    _attr_icon = "mdi:waves"
    _attr_name = "Backwash Trigger"
    _attr_translation_key = "start_backwash"
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "start_backwash")
    async def async_press(self) -> None:
        await self.coordinator.client.async_start_backwash()
        await self.coordinator.async_request_refresh()
