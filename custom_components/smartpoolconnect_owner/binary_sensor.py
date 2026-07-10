"""Binary sensors."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .entity import SmartPoolConnectEntity
@dataclass(frozen=True, kw_only=True)
class SmartPoolBinaryDescription(BinarySensorEntityDescription): value_fn: Callable[[PoolStatus], bool | None]
BINARY_SENSORS=(SmartPoolBinaryDescription(key="online",translation_key="online",device_class=BinarySensorDeviceClass.CONNECTIVITY,value_fn=lambda s:s.online),SmartPoolBinaryDescription(key="heating",translation_key="heating",device_class=BinarySensorDeviceClass.HEAT,icon="mdi:radiator",value_fn=lambda s:s.heating_on),SmartPoolBinaryDescription(key="pump",translation_key="pump",icon="mdi:pump",value_fn=lambda s:s.pump_status))
async def async_setup_entry(hass:HomeAssistant, entry:SmartPoolConnectConfigEntry, async_add_entities:AddEntitiesCallback)->None:
    async_add_entities(SmartPoolBinarySensor(entry.runtime_data,d) for d in BINARY_SENSORS)
class SmartPoolBinarySensor(SmartPoolConnectEntity, BinarySensorEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = {"online": "Online", "heating": "Heating", "pump": "Pump"}[description.key]
    @property
    def is_on(self): return self.entity_description.value_fn(self.coordinator.data)
