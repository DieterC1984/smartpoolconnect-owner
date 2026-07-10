"""Base entity."""
from __future__ import annotations
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import CONF_POOL_ID, DOMAIN, MANUFACTURER
from .coordinator import SmartPoolConnectCoordinator
class SmartPoolConnectEntity(CoordinatorEntity[SmartPoolConnectCoordinator]):
    _attr_has_entity_name = False
    def __init__(self, coordinator: SmartPoolConnectCoordinator, key: str) -> None:
        super().__init__(coordinator)
        pool_id = coordinator.entry.data[CONF_POOL_ID]
        self._attr_unique_id = f"{pool_id}_{key}"
        status = coordinator.data
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, pool_id)}, name=(status.name if status else None) or f"SmartPoolConnect {pool_id}", manufacturer=MANUFACTURER, model="Owner Portal", configuration_url=f"https://www.smartpoolconnect.eu/pool/{pool_id}")
