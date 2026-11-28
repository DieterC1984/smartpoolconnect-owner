"""Binary sensors."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .const import CONF_POOL_ID, DOMAIN, MANUFACTURER
from .coordinator import NexusCoordinator
from .entity import SmartPoolConnectEntity
@dataclass(frozen=True, kw_only=True)
class SmartPoolBinaryDescription(BinarySensorEntityDescription): value_fn: Callable[[PoolStatus], bool | None]
BINARY_SENSORS=(SmartPoolBinaryDescription(key="online",translation_key="online",device_class=BinarySensorDeviceClass.CONNECTIVITY,value_fn=lambda s:s.online),SmartPoolBinaryDescription(key="heating",translation_key="heating",device_class=BinarySensorDeviceClass.HEAT,icon="mdi:radiator",value_fn=lambda s:s.heating_on),SmartPoolBinaryDescription(key="pump",translation_key="pump",icon="mdi:pump",value_fn=lambda s:s.pump_status))
async def async_setup_entry(hass:HomeAssistant, entry:SmartPoolConnectConfigEntry, async_add_entities:AddEntitiesCallback)->None:
    entities = [SmartPoolBinarySensor(entry.runtime_data,d) for d in BINARY_SENSORS]
    nexus_coordinator = entry.runtime_data.nexus
    entities.append(NexusOnlineBinarySensor(nexus_coordinator))
    async_add_entities(entities)
class SmartPoolBinarySensor(SmartPoolConnectEntity, BinarySensorEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = {"online": "SmartPool", "heating": "Heating", "pump": "Pump"}[description.key]
    @property
    def is_on(self): return self.entity_description.value_fn(self.coordinator.data)

class NexusOnlineBinarySensor(CoordinatorEntity[NexusCoordinator], BinarySensorEntity):
    """Green/red portal pool indicator from pool route ``status``."""
    _attr_has_entity_name = False
    _attr_name = "Nexus"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, coordinator: NexusCoordinator) -> None:
        super().__init__(coordinator)
        pool_id = coordinator.entry.data[CONF_POOL_ID]
        self._attr_unique_id = f"{pool_id}_nexus_online"
        main_status = coordinator.entry.runtime_data.data
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN,pool_id)},name=(main_status.name if main_status else None) or f"SmartPoolConnect {pool_id}",manufacturer=MANUFACTURER,model="Owner Portal",configuration_url=f"https://www.smartpoolconnect.eu/pool/{pool_id}")
    @property
    def available(self) -> bool:
        status = self.coordinator.data.status
        return bool(super().available and status in {"online","offline","maintenance"})
    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.status
        return status == "online" if status in {"online","offline","maintenance"} else None
