"""Number entities."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .api import PoolBackwashSettings, PoolStatus
from .entity import SmartPoolConnectEntity
@dataclass(frozen=True, kw_only=True)
class SmartPoolNumberDescription(NumberEntityDescription):
    value_fn: Callable[[PoolStatus], float | None]
    set_fn: Callable[["SmartPoolNumber", float], Any]
async def _set_ph_target(e,v):
    d=e.coordinator.data
    if d: await e.coordinator.client.async_set_ph_settings(target=v,dosing_time=d.ph_dosing_time if d.ph_dosing_time is not None else 60,pausing_time=d.ph_pausing_time if d.ph_pausing_time is not None else 5)
async def _set_ph_dosing_time(e,v):
    d=e.coordinator.data
    if d: await e.coordinator.client.async_set_ph_settings(target=d.ph_target if d.ph_target is not None else 7.2,dosing_time=v,pausing_time=d.ph_pausing_time if d.ph_pausing_time is not None else 5)
async def _set_ph_pausing_time(e,v):
    d=e.coordinator.data
    if d: await e.coordinator.client.async_set_ph_settings(target=d.ph_target if d.ph_target is not None else 7.2,dosing_time=d.ph_dosing_time if d.ph_dosing_time is not None else 60,pausing_time=v)
async def _set_rx_target(e,v):
    d=e.coordinator.data
    if d: await e.coordinator.client.async_set_rx_settings(target=v,dosing_time=d.rx_dosing_time if d.rx_dosing_time is not None else 90,pausing_time=d.rx_pausing_time if d.rx_pausing_time is not None else 5)
async def _set_rx_dosing_time(e,v):
    d=e.coordinator.data
    if d: await e.coordinator.client.async_set_rx_settings(target=d.rx_target if d.rx_target is not None else 700,dosing_time=v,pausing_time=d.rx_pausing_time if d.rx_pausing_time is not None else 5)
async def _set_rx_pausing_time(e,v):
    d=e.coordinator.data
    if d: await e.coordinator.client.async_set_rx_settings(target=d.rx_target if d.rx_target is not None else 700,dosing_time=d.rx_dosing_time if d.rx_dosing_time is not None else 90,pausing_time=v)
def _backwash_from_data(d: PoolStatus) -> PoolBackwashSettings:
    return PoolBackwashSettings(interval=d.backwash_interval, rinse_duration=d.backwash_rinse_duration, backwash_duration=d.backwash_duration, pump_speed=d.backwash_pump_speed, start_date=d.backwash_start_date, start_time=d.backwash_start_time)
def _backwash(coordinator) -> PoolBackwashSettings:
    store = getattr(coordinator, "_smartpool_pending_config", {})
    pending = store.get("backwash")
    if pending: return pending["value"]
    return _backwash_from_data(coordinator.data)
def _save_pending(coordinator, settings: PoolBackwashSettings) -> None:
    if not hasattr(coordinator, "_smartpool_pending_config"):
        coordinator._smartpool_pending_config = {}
    coordinator._smartpool_pending_config["backwash"] = {"value": settings, "expires": 10**18}
async def _commit_backwash(e, settings: PoolBackwashSettings) -> None:
    _save_pending(e.coordinator, settings)
    await e.coordinator.client.async_set_backwash_settings(settings)
async def _set_bw_interval(e,v):
    s=_backwash(e.coordinator); s.interval=v; await _commit_backwash(e,s)
async def _set_bw_rinse(e,v):
    s=_backwash(e.coordinator); s.rinse_duration=v; await _commit_backwash(e,s)
async def _set_bw_duration(e,v):
    s=_backwash(e.coordinator); s.backwash_duration=v; await _commit_backwash(e,s)
NUMBERS=(
SmartPoolNumberDescription(key="ph_target",translation_key="ph_target",native_min_value=5,native_max_value=9,native_step=0.1,mode=NumberMode.BOX,native_unit_of_measurement="pH",value_fn=lambda s:s.ph_target,set_fn=_set_ph_target),
SmartPoolNumberDescription(key="ph_dosing_time",translation_key="ph_dosing_time",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="s",value_fn=lambda s:s.ph_dosing_time,set_fn=_set_ph_dosing_time),
SmartPoolNumberDescription(key="ph_pausing_time",translation_key="ph_pausing_time",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="min",value_fn=lambda s:s.ph_pausing_time,set_fn=_set_ph_pausing_time),
SmartPoolNumberDescription(key="rx_target",translation_key="rx_target",native_min_value=0,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="mV",value_fn=lambda s:s.rx_target,set_fn=_set_rx_target),
SmartPoolNumberDescription(key="rx_dosing_time",translation_key="rx_dosing_time",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="s",value_fn=lambda s:s.rx_dosing_time,set_fn=_set_rx_dosing_time),
SmartPoolNumberDescription(key="rx_pausing_time",translation_key="rx_pausing_time",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="min",value_fn=lambda s:s.rx_pausing_time,set_fn=_set_rx_pausing_time),
SmartPoolNumberDescription(key="backwash_interval",translation_key="backwash_interval",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="d",value_fn=lambda s:s.backwash_interval,set_fn=_set_bw_interval),
SmartPoolNumberDescription(key="backwash_rinse_duration",translation_key="backwash_rinse_duration",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="s",value_fn=lambda s:s.backwash_rinse_duration,set_fn=_set_bw_rinse),
SmartPoolNumberDescription(key="backwash_duration",translation_key="backwash_duration",native_min_value=1,native_max_value=999,native_step=1,mode=NumberMode.BOX,native_unit_of_measurement="s",value_fn=lambda s:s.backwash_duration,set_fn=_set_bw_duration),
)
NAMES={"ph_target":"pH Target","ph_dosing_time":"pH Dosing Time","ph_pausing_time":"pH Pause Time","rx_target":"Rx Target","rx_dosing_time":"Rx Dosing Time","rx_pausing_time":"Rx Pause Time","backwash_interval":"Backwash 01 Interval","backwash_rinse_duration":"Backwash 02 Rinse Duration","backwash_duration":"Backwash 03 Duration"}
async def async_setup_entry(hass:HomeAssistant,entry:SmartPoolConnectConfigEntry,async_add_entities:AddEntitiesCallback)->None:
    async_add_entities(SmartPoolNumber(entry.runtime_data,d) for d in NUMBERS)
class SmartPoolNumber(SmartPoolConnectEntity,NumberEntity):
    def __init__(self,coordinator,description): super().__init__(coordinator,description.key); self.entity_description=description; self._attr_name=NAMES[description.key]
    @property
    def native_value(self): return None if self.coordinator.data is None else self.entity_description.value_fn(self.coordinator.data)
    async def async_set_native_value(self,value:float):
        if self.coordinator.data is None: return
        await self.entity_description.set_fn(self,value); await self.coordinator.async_request_refresh()
