"""Switches."""
from __future__ import annotations
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .api import DAYS, PoolCoverSettings, PoolFilterSchedule, PoolFilterSettings, PoolLightingSettings, PoolStatus
from .entity import SmartPoolConnectEntity
PENDING_TIMEOUT_SECONDS = 45

@dataclass(frozen=True, kw_only=True)
class SmartPoolSwitchDescription(SwitchEntityDescription):
    value_fn: Callable[[PoolStatus], bool | None]
    set_fn: Callable[["SmartPoolSwitch", bool], Any]

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

def _lighting_from_data(d: PoolStatus) -> PoolLightingSettings:
    return PoolLightingSettings(
        always_active=d.lighting_always_active if d.lighting_always_active is not None else bool(d.lighting_on),
        cover_disabled=d.lighting_cover_disabled if d.lighting_cover_disabled is not None else False,
        schedule_enabled=d.lighting_schedule_enabled if d.lighting_schedule_enabled is not None else False,
        schedule_start_time=d.lighting_schedule_start_time or "20:00",
        schedule_stop_time=d.lighting_schedule_stop_time or "23:59",
        schedule_days=d.lighting_schedule_days,
    )

def _lighting(coordinator) -> PoolLightingSettings:
    pending = _store(coordinator).get("lighting")
    if pending:
        return pending["value"]
    return _lighting_from_data(coordinator.data)

async def _commit_lighting(e, settings: PoolLightingSettings) -> None:
    _save_pending(e.coordinator, "lighting", settings)
    await e.coordinator.client.async_set_lighting_settings(
        always_active=bool(settings.always_active),
        cover_disabled=bool(settings.cover_disabled),
        schedule_enabled=bool(settings.schedule_enabled),
        schedule_start_time=settings.schedule_start_time or "20:00",
        schedule_stop_time=settings.schedule_stop_time or "23:59",
        schedule_days=settings.schedule_days,
    )

async def _set_lighting_always(e, v):
    settings = _lighting(e.coordinator); settings.always_active = v
    await _commit_lighting(e, settings)
async def _set_lighting_cover_disabled(e, v):
    settings = _lighting(e.coordinator); settings.cover_disabled = v
    await _commit_lighting(e, settings)
async def _set_lighting_schedule_enabled(e, v):
    settings = _lighting(e.coordinator); settings.schedule_enabled = v
    await _commit_lighting(e, settings)
def _set_lighting_day(day):
    async def setter(e, v):
        settings = _lighting(e.coordinator); days = set(settings.schedule_days)
        days.add(day) if v else days.discard(day)
        settings.schedule_days = tuple(d for d in DAYS if d in days)
        await _commit_lighting(e, settings)
    return setter

def _filter_schedule(d: PoolStatus, idx: int) -> PoolFilterSchedule:
    return PoolFilterSchedule(
        enabled=getattr(d, f"filter_schedule_{idx}_enabled"),
        pump_speed=getattr(d, f"filter_schedule_{idx}_pump_speed"),
        start_time=getattr(d, f"filter_schedule_{idx}_start_time"),
        stop_time=getattr(d, f"filter_schedule_{idx}_stop_time"),
        days=getattr(d, f"filter_schedule_{idx}_days"),
    )

def _filter_from_data(d: PoolStatus) -> PoolFilterSettings:
    return PoolFilterSettings(
        always_active=d.filter_always_active if d.filter_always_active is not None else False,
        pump_speed=d.filter_pump_speed or d.pump_speed or "medium",
        schedule_1=_filter_schedule(d, 1),
        schedule_2=_filter_schedule(d, 2),
        schedule_3=_filter_schedule(d, 3),
    )

def _filter(coordinator) -> PoolFilterSettings:
    pending = _store(coordinator).get("filter")
    if pending:
        return pending["value"]
    return _filter_from_data(coordinator.data)

async def _commit_filter(e, settings: PoolFilterSettings) -> None:
    _save_pending(e.coordinator, "filter", settings)
    await e.coordinator.client.async_set_filter_settings(settings)

async def _set_filter_always(e, v):
    settings = _filter(e.coordinator); settings.always_active = v
    await _commit_filter(e, settings)
def _set_filter_schedule_enabled(idx: int):
    async def setter(e, v):
        settings = _filter(e.coordinator)
        getattr(settings, f"schedule_{idx}").enabled = v
        await _commit_filter(e, settings)
    return setter
def _set_filter_schedule_day(idx: int, day: str):
    async def setter(e, v):
        settings = _filter(e.coordinator); schedule = getattr(settings, f"schedule_{idx}")
        days = set(schedule.days)
        days.add(day) if v else days.discard(day)
        schedule.days = tuple(d for d in DAYS if d in days)
        await _commit_filter(e, settings)
    return setter

def _cover_from_data(d: PoolStatus) -> PoolCoverSettings:
    """Build cover settings from coordinator data, preserving observed defaults."""
    return PoolCoverSettings(
        protection=True if d.cover_protection is None else d.cover_protection,
        pump_open=False if d.cover_pump_open is None else d.cover_pump_open,
        pump_close=True if d.cover_pump_close is None else d.cover_pump_close,
        pump_low_speed=False if d.cover_pump_low_speed is None else d.cover_pump_low_speed,
    )

def _cover(coordinator) -> PoolCoverSettings:
    pending = _store(coordinator).get("cover")
    if pending:
        return pending["value"]
    return _cover_from_data(coordinator.data)

async def _commit_cover(e, settings: PoolCoverSettings) -> None:
    # Refresh optional location fields from the cover page if available.
    current = await e.coordinator.client.async_get_cover_settings()
    settings.longitude = current.longitude
    settings.latitude = current.latitude
    _save_pending(e.coordinator, "cover", settings)
    await e.coordinator.client.async_set_cover_settings(settings)

async def _set_cover_protection(e, v):
    settings = _cover(e.coordinator)
    settings.protection = v
    await _commit_cover(e, settings)

async def _set_cover_pump_open(e, v):
    settings = _cover(e.coordinator)
    settings.pump_open = v
    await _commit_cover(e, settings)

async def _set_cover_pump_close(e, v):
    settings = _cover(e.coordinator)
    settings.pump_close = v
    await _commit_cover(e, settings)

async def _set_cover_pump_low_speed(e, v):
    settings = _cover(e.coordinator)
    settings.pump_low_speed = v
    await _commit_cover(e, settings)

SWITCHES: list[SmartPoolSwitchDescription] = [
    SmartPoolSwitchDescription(key="lighting", translation_key="lighting", icon="mdi:lightbulb", device_class=SwitchDeviceClass.SWITCH, value_fn=lambda s: s.lighting_always_active if s.lighting_always_active is not None else s.lighting_on, set_fn=_set_lighting_always),
    SmartPoolSwitchDescription(key="lighting_cover_disabled", translation_key="lighting_cover_disabled", icon="mdi:window-shutter-alert", value_fn=lambda s: s.lighting_cover_disabled, set_fn=_set_lighting_cover_disabled),
    SmartPoolSwitchDescription(key="lighting_schedule_enabled", translation_key="lighting_schedule_enabled", icon="mdi:calendar-clock", value_fn=lambda s: s.lighting_schedule_enabled, set_fn=_set_lighting_schedule_enabled),
    SmartPoolSwitchDescription(key="cover_protection", translation_key="cover_protection", icon="mdi:shield-check", device_class=SwitchDeviceClass.SWITCH, value_fn=lambda s: s.cover_protection if s.cover_protection is not None else True, set_fn=_set_cover_protection),
    SmartPoolSwitchDescription(key="opening_pump", translation_key="opening_pump", icon="mdi:pump", device_class=SwitchDeviceClass.SWITCH, value_fn=lambda s: s.cover_pump_open if s.cover_pump_open is not None else False, set_fn=_set_cover_pump_open),
    SmartPoolSwitchDescription(key="closing_pump", translation_key="closing_pump", icon="mdi:pump", device_class=SwitchDeviceClass.SWITCH, value_fn=lambda s: s.cover_pump_close if s.cover_pump_close is not None else True, set_fn=_set_cover_pump_close),
    SmartPoolSwitchDescription(key="opening_pump_slow", translation_key="opening_pump_slow", icon="mdi:speedometer-slow", device_class=SwitchDeviceClass.SWITCH, value_fn=lambda s: s.cover_pump_low_speed if s.cover_pump_low_speed is not None else False, set_fn=_set_cover_pump_low_speed),
]
for day in DAYS:
    SWITCHES.append(SmartPoolSwitchDescription(key=f"lighting_schedule_{day}", translation_key=f"lighting_schedule_{day}", icon="mdi:calendar", value_fn=lambda s, d=day: d in s.lighting_schedule_days, set_fn=_set_lighting_day(day)))
SWITCHES.append(SmartPoolSwitchDescription(key="filter_always_active", translation_key="filter_always_active", icon="mdi:pump", value_fn=lambda s: s.filter_always_active, set_fn=_set_filter_always))
for idx in (1, 2, 3):
    SWITCHES.append(SmartPoolSwitchDescription(key=f"filter_schedule_{idx}_enabled", translation_key=f"filter_schedule_{idx}_enabled", icon="mdi:calendar-clock", value_fn=lambda s, i=idx: getattr(s, f"filter_schedule_{i}_enabled"), set_fn=_set_filter_schedule_enabled(idx)))
    for day in DAYS:
        SWITCHES.append(SmartPoolSwitchDescription(key=f"filter_schedule_{idx}_{day}", translation_key=f"filter_schedule_{idx}_{day}", icon="mdi:calendar", value_fn=lambda s, i=idx, d=day: d in getattr(s, f"filter_schedule_{i}_days"), set_fn=_set_filter_schedule_day(idx, day)))

NAMES = {
    "lighting": "Lighting 01 Always Active",
    "lighting_cover_disabled": "Lighting 02 Disabled When Cover Closed",
    "lighting_schedule_enabled": "Lighting 03 Schedule Enabled",
    "filter_always_active": "Filter 01 Always Active",
    "cover_protection": "Cover 01 Protection",
    "opening_pump": "Cover 02 Opening Pump",
    "closing_pump": "Cover 03 Closing Pump",
    "opening_pump_slow": "Cover 04 Opening Pump Slow Mode",
}
NAMES.update({f"lighting_schedule_{d}": f"Lighting Schedule {i + 1:02d} {d.title()}" for i, d in enumerate(DAYS)})
for i in (1, 2, 3):
    NAMES[f"filter_schedule_{i}_enabled"] = f"Filter Schedule {i} 01 Enabled"
    for pos, day in enumerate(DAYS, start=5):
        NAMES[f"filter_schedule_{i}_{day}"] = f"Filter Schedule {i} {pos:02d} {day.title()}"

async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmartPoolSwitch(entry.runtime_data, description) for description in SWITCHES)

class SmartPoolSwitch(SmartPoolConnectEntity, SwitchEntity):
    entity_description: SmartPoolSwitchDescription
    def __init__(self, coordinator, description: SmartPoolSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = NAMES[description.key]
        self._pending_state = None
        self._pending_until = None
    @property
    def is_on(self):
        actual = None if self.coordinator.data is None else self.entity_description.value_fn(self.coordinator.data)
        if self._pending_state is None:
            return actual
        if actual == self._pending_state:
            self._pending_state = None; self._pending_until = None
            return actual
        if self._pending_until is not None and time.monotonic() > self._pending_until:
            self._pending_state = None; self._pending_until = None
            return actual
        return self._pending_state
    async def async_turn_on(self, **kwargs: Any):
        await self._set(True)
    async def async_turn_off(self, **kwargs: Any):
        await self._set(False)
    async def _set(self, value: bool):
        self._pending_state = value
        self._pending_until = time.monotonic() + PENDING_TIMEOUT_SECONDS
        self.async_write_ha_state()
        try:
            await self.entity_description.set_fn(self, value)
            await self.coordinator.async_request_refresh()
        except Exception:
            self._pending_state = None; self._pending_until = None
            self.async_write_ha_state()
            raise
