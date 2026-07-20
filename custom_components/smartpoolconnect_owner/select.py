"""Select entities."""
from __future__ import annotations
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .api import BACKWASH_PUMP_SPEED_OPTIONS, ECO_VALVE_REGULATION_OPTIONS, PUMP_SPEED_OPTIONS, PoolBackwashSettings, PoolEcoValveSettings, PoolFilterSchedule, PoolFilterSettings, PoolStatus
from .entity import SmartPoolConnectEntity
PENDING_TIMEOUT_SECONDS = 45

@dataclass(frozen=True, kw_only=True)
class SmartPoolSelectDescription(SelectEntityDescription):
    value_fn: Callable[[PoolStatus], str | None]
    set_fn: Callable[["SmartPoolSelect", str], Any]

def _store(coordinator) -> dict[str, Any]:
    if not hasattr(coordinator, "_smartpool_pending_config"):
        coordinator._smartpool_pending_config = {}
    store = coordinator._smartpool_pending_config
    now = time.monotonic()
    for key in list(store):
        if store[key].get("expires", 0) < now:
            del store[key]
    return store

def _save_pending(coordinator, key: str, value: Any) -> None:
    _store(coordinator)[key] = {"value": value, "expires": time.monotonic() + PENDING_TIMEOUT_SECONDS}

def _schedule(d: PoolStatus, idx: int) -> PoolFilterSchedule:
    return PoolFilterSchedule(enabled=getattr(d, f"filter_schedule_{idx}_enabled"), pump_speed=getattr(d, f"filter_schedule_{idx}_pump_speed"), start_time=getattr(d, f"filter_schedule_{idx}_start_time"), stop_time=getattr(d, f"filter_schedule_{idx}_stop_time"), days=getattr(d, f"filter_schedule_{idx}_days"))

def _filter_from_data(d: PoolStatus) -> PoolFilterSettings:
    return PoolFilterSettings(always_active=d.filter_always_active if d.filter_always_active is not None else False, pump_speed=d.filter_pump_speed or d.pump_speed or "medium", schedule_1=_schedule(d, 1), schedule_2=_schedule(d, 2), schedule_3=_schedule(d, 3))

def _filter(coordinator) -> PoolFilterSettings:
    pending = _store(coordinator).get("filter")
    if pending:
        return pending["value"]
    return _filter_from_data(coordinator.data)

async def _commit_filter(e, settings: PoolFilterSettings) -> None:
    _save_pending(e.coordinator, "filter", settings)
    await e.coordinator.client.async_set_filter_settings(settings)

async def _set_filter_pump_speed(e, value):
    settings = _filter(e.coordinator); settings.pump_speed = value
    await _commit_filter(e, settings)

def _set_schedule_speed(idx: int):
    async def setter(e, value):
        settings = _filter(e.coordinator)
        getattr(settings, f"schedule_{idx}").pump_speed = value
        await _commit_filter(e, settings)
    return setter

def _backwash_from_data(d: PoolStatus) -> PoolBackwashSettings:
    return PoolBackwashSettings(interval=d.backwash_interval, rinse_duration=d.backwash_rinse_duration, backwash_duration=d.backwash_duration, pump_speed=d.backwash_pump_speed, start_date=d.backwash_start_date, start_time=d.backwash_start_time)

def _backwash(coordinator) -> PoolBackwashSettings:
    pending = _store(coordinator).get("backwash")
    if pending:
        return pending["value"]
    return _backwash_from_data(coordinator.data)

async def _commit_backwash(e, settings: PoolBackwashSettings) -> None:
    _save_pending(e.coordinator, "backwash", settings)
    await e.coordinator.client.async_set_backwash_settings(settings)

async def _set_backwash_pump_speed(e, value):
    settings = _backwash(e.coordinator); settings.pump_speed = value
    await _commit_backwash(e, settings)

def _eco_valve_from_data(d: PoolStatus) -> PoolEcoValveSettings:
    return PoolEcoValveSettings(regulation=d.eco_valve_regulation, start_time=d.eco_valve_start_time, stop_time=d.eco_valve_stop_time)

def _eco_valve(coordinator) -> PoolEcoValveSettings:
    pending = _store(coordinator).get("eco_valve")
    if pending:
        return pending["value"]
    return _eco_valve_from_data(coordinator.data)

async def _commit_eco_valve(e, settings: PoolEcoValveSettings) -> None:
    _save_pending(e.coordinator, "eco_valve", settings)
    await e.coordinator.client.async_set_eco_valve_settings(settings)

async def _set_eco_valve_regulation(e, value):
    settings = _eco_valve(e.coordinator); settings.regulation = value
    await _commit_eco_valve(e, settings)

SELECTS = [
    SmartPoolSelectDescription(key="eco_valve_regulation", translation_key="eco_valve_regulation", icon="mdi:valve", options=list(ECO_VALVE_REGULATION_OPTIONS), value_fn=lambda s: s.eco_valve_regulation, set_fn=_set_eco_valve_regulation),
    SmartPoolSelectDescription(key="backwash_pump_speed", translation_key="backwash_pump_speed", icon="mdi:waves", options=list(BACKWASH_PUMP_SPEED_OPTIONS), value_fn=lambda s: s.backwash_pump_speed, set_fn=_set_backwash_pump_speed),
    SmartPoolSelectDescription(key="filter_pump_speed", translation_key="filter_pump_speed", icon="mdi:pump", options=list(PUMP_SPEED_OPTIONS), value_fn=lambda s: s.filter_pump_speed or s.pump_speed, set_fn=_set_filter_pump_speed),
]
for i in (1, 2, 3):
    SELECTS.append(SmartPoolSelectDescription(key=f"filter_schedule_{i}_pump_speed", translation_key=f"filter_schedule_{i}_pump_speed", icon="mdi:pump", options=list(PUMP_SPEED_OPTIONS), value_fn=lambda s, idx=i: getattr(s, f"filter_schedule_{idx}_pump_speed"), set_fn=_set_schedule_speed(i)))

NAMES = {
    "eco_valve_regulation": "Eco Valve Regulation",
    "backwash_pump_speed": "Backwash Pump Speed",
    "filter_pump_speed": "Filter Pump Standard Speed",
}


for i in (1, 2, 3):
    NAMES[f"filter_schedule_{i}_pump_speed"] = f"Filter Schedule {i} Pump Speed"

async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmartPoolSelect(entry.runtime_data, description) for description in SELECTS)

class SmartPoolSelect(SmartPoolConnectEntity, SelectEntity):
    entity_description: SmartPoolSelectDescription
    def __init__(self, coordinator, description: SmartPoolSelectDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = NAMES[description.key]
        self._attr_options = description.options
        self._pending_option = None
        self._pending_until = None
    @property
    def current_option(self):
        actual = None if self.coordinator.data is None else self.entity_description.value_fn(self.coordinator.data)
        if self._pending_option is None:
            return actual
        if actual == self._pending_option:
            self._pending_option = None; self._pending_until = None
            return actual
        if self._pending_until is not None and time.monotonic() > self._pending_until:
            self._pending_option = None; self._pending_until = None
            return actual
        return self._pending_option
    async def async_select_option(self, option: str):
        self._pending_option = option
        self._pending_until = time.monotonic() + PENDING_TIMEOUT_SECONDS
        self.async_write_ha_state()
        try:
            await self.entity_description.set_fn(self, option)
            await self.coordinator.async_request_refresh()
        except Exception:
            self._pending_option = None; self._pending_until = None
            self.async_write_ha_state()
            raise
