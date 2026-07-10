"""Time entities."""
from __future__ import annotations
import time as monotonic_time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from typing import Any
from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .api import PoolBackwashSettings, PoolEcoValveSettings, PoolFilterSchedule, PoolFilterSettings, PoolLightingSettings, PoolStatus
from .entity import SmartPoolConnectEntity
PENDING_TIMEOUT_SECONDS = 45

@dataclass(frozen=True, kw_only=True)
class SmartPoolTimeDescription(TimeEntityDescription):
    value_fn: Callable[[PoolStatus], str | None]
    set_fn: Callable[["SmartPoolTime", str], Any]

def _parse(v):
    if not v:
        return None
    try:
        h, m = v.split(":")[:2]
        return time(int(h), int(m))
    except (TypeError, ValueError):
        return None

def _fmt(v: time): return f"{v.hour:02d}:{v.minute:02d}"

def _store(coordinator) -> dict[str, Any]:
    if not hasattr(coordinator, "_smartpool_pending_config"):
        coordinator._smartpool_pending_config = {}
    store = coordinator._smartpool_pending_config
    now = monotonic_time.monotonic()
    for key in list(store):
        if store[key].get("expires", 0) < now:
            del store[key]
    return store

def _save_pending(coordinator, key: str, value: Any) -> None:
    _store(coordinator)[key] = {"value": value, "expires": monotonic_time.monotonic() + PENDING_TIMEOUT_SECONDS}

def _lighting_from_data(d: PoolStatus) -> PoolLightingSettings:
    return PoolLightingSettings(always_active=d.lighting_always_active if d.lighting_always_active is not None else bool(d.lighting_on), cover_disabled=d.lighting_cover_disabled if d.lighting_cover_disabled is not None else False, schedule_enabled=d.lighting_schedule_enabled if d.lighting_schedule_enabled is not None else False, schedule_start_time=d.lighting_schedule_start_time or "20:00", schedule_stop_time=d.lighting_schedule_stop_time or "23:59", schedule_days=d.lighting_schedule_days)

def _lighting(coordinator) -> PoolLightingSettings:
    pending = _store(coordinator).get("lighting")
    if pending:
        return pending["value"]
    return _lighting_from_data(coordinator.data)

async def _commit_lighting(e, settings: PoolLightingSettings) -> None:
    _save_pending(e.coordinator, "lighting", settings)
    await e.coordinator.client.async_set_lighting_settings(always_active=bool(settings.always_active), cover_disabled=bool(settings.cover_disabled), schedule_enabled=bool(settings.schedule_enabled), schedule_start_time=settings.schedule_start_time or "20:00", schedule_stop_time=settings.schedule_stop_time or "23:59", schedule_days=settings.schedule_days)

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

async def _set_light_start(e, v):
    settings = _lighting(e.coordinator); settings.schedule_start_time = v
    await _commit_lighting(e, settings)
async def _set_light_stop(e, v):
    settings = _lighting(e.coordinator); settings.schedule_stop_time = v
    await _commit_lighting(e, settings)
def _set_filter_time(idx: int, field: str):
    async def setter(e, v):
        settings = _filter(e.coordinator)
        setattr(getattr(settings, f"schedule_{idx}"), field, v)
        await _commit_filter(e, settings)
    return setter
async def _set_backwash_start_time(e, v):
    settings = _backwash(e.coordinator); settings.start_time = v
    await _commit_backwash(e, settings)
def _set_eco_valve_time(field: str):
    async def setter(e, v):
        settings = _eco_valve(e.coordinator)
        setattr(settings, field, v)
        await _commit_eco_valve(e, settings)
    return setter

TIMES = [
    SmartPoolTimeDescription(key="lighting_start_time", translation_key="lighting_start_time", value_fn=lambda s: s.lighting_schedule_start_time, set_fn=_set_light_start),
    SmartPoolTimeDescription(key="lighting_stop_time", translation_key="lighting_stop_time", value_fn=lambda s: s.lighting_schedule_stop_time, set_fn=_set_light_stop),
    SmartPoolTimeDescription(key="backwash_start_time", translation_key="backwash_start_time", value_fn=lambda s: s.backwash_start_time, set_fn=_set_backwash_start_time),
    SmartPoolTimeDescription(key="eco_valve_start_time", translation_key="eco_valve_start_time", value_fn=lambda s: s.eco_valve_start_time, set_fn=_set_eco_valve_time("start_time")),
    SmartPoolTimeDescription(key="eco_valve_stop_time", translation_key="eco_valve_stop_time", value_fn=lambda s: s.eco_valve_stop_time, set_fn=_set_eco_valve_time("stop_time")),
]
for i in (1, 2, 3):
    TIMES.append(SmartPoolTimeDescription(key=f"filter_schedule_{i}_start_time", translation_key=f"filter_schedule_{i}_start_time", value_fn=lambda s, idx=i: getattr(s, f"filter_schedule_{idx}_start_time"), set_fn=_set_filter_time(i, "start_time")))
    TIMES.append(SmartPoolTimeDescription(key=f"filter_schedule_{i}_stop_time", translation_key=f"filter_schedule_{i}_stop_time", value_fn=lambda s, idx=i: getattr(s, f"filter_schedule_{idx}_stop_time"), set_fn=_set_filter_time(i, "stop_time")))

NAMES = {"lighting_start_time": "Lighting 04 Start Time", "lighting_stop_time": "Lighting 05 Stop Time", "backwash_start_time": "Backwash 06 Start Time", "eco_valve_start_time": "Eco Valve 02 Start Time", "eco_valve_stop_time": "Eco Valve 03 Stop Time"}
for i in (1, 2, 3):
    NAMES[f"filter_schedule_{i}_start_time"] = f"Filter Schedule {i} 03 Start Time"
    NAMES[f"filter_schedule_{i}_stop_time"] = f"Filter Schedule {i} 04 Stop Time"

async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmartPoolTime(entry.runtime_data, description) for description in TIMES)

class SmartPoolTime(SmartPoolConnectEntity, TimeEntity):
    entity_description: SmartPoolTimeDescription
    def __init__(self, coordinator, description: SmartPoolTimeDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = NAMES[description.key]
        self._pending_value = None
        self._pending_until = None
    @property
    def native_value(self):
        actual = None if self.coordinator.data is None else _parse(self.entity_description.value_fn(self.coordinator.data))
        if self._pending_value is None:
            return actual
        if actual == self._pending_value:
            self._pending_value = None; self._pending_until = None
            return actual
        if self._pending_until is not None and monotonic_time.monotonic() > self._pending_until:
            self._pending_value = None; self._pending_until = None
            return actual
        return self._pending_value
    async def async_set_value(self, value: time):
        self._pending_value = value
        self._pending_until = monotonic_time.monotonic() + PENDING_TIMEOUT_SECONDS
        self.async_write_ha_state()
        try:
            await self.entity_description.set_fn(self, _fmt(value))
            await self.coordinator.async_request_refresh()
        except Exception:
            self._pending_value = None; self._pending_until = None
            self.async_write_ha_state()
            raise
