"""Date entities."""
from __future__ import annotations
import time as monotonic_time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from homeassistant.components.date import DateEntity, DateEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import SmartPoolConnectConfigEntry
from .api import PoolBackwashSettings, PoolStatus
from .entity import SmartPoolConnectEntity
PENDING_TIMEOUT_SECONDS = 45
@dataclass(frozen=True, kw_only=True)
class SmartPoolDateDescription(DateEntityDescription):
    value_fn: Callable[[PoolStatus], str | None]
    set_fn: Callable[["SmartPoolDate", str], Any]
def _parse(v):
    if not v: return None
    try: return date.fromisoformat(v)
    except ValueError: return None
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
def _backwash_from_data(d: PoolStatus) -> PoolBackwashSettings:
    return PoolBackwashSettings(interval=d.backwash_interval, rinse_duration=d.backwash_rinse_duration, backwash_duration=d.backwash_duration, pump_speed=d.backwash_pump_speed, start_date=d.backwash_start_date, start_time=d.backwash_start_time)
def _backwash(coordinator) -> PoolBackwashSettings:
    pending = _store(coordinator).get("backwash")
    if pending: return pending["value"]
    return _backwash_from_data(coordinator.data)
async def _commit_backwash(e, settings: PoolBackwashSettings) -> None:
    _save_pending(e.coordinator, "backwash", settings)
    await e.coordinator.client.async_set_backwash_settings(settings)
async def _set_backwash_start_date(e, value: str):
    s = _backwash(e.coordinator); s.start_date = value
    await _commit_backwash(e, s)
DATES = (SmartPoolDateDescription(key="backwash_start_date", translation_key="backwash_start_date", value_fn=lambda s: s.backwash_start_date, set_fn=_set_backwash_start_date),)

NAMES = {
    "backwash_start_date": "Backwash Setting Start Date"
}

async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmartPoolDate(entry.runtime_data, d) for d in DATES)
class SmartPoolDate(SmartPoolConnectEntity, DateEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key); self.entity_description=description; self._attr_name=NAMES[description.key]; self._pending_value=None; self._pending_until=None
    @property
    def native_value(self):
        actual = None if self.coordinator.data is None else _parse(self.entity_description.value_fn(self.coordinator.data))
        if self._pending_value is None: return actual
        if actual == self._pending_value: self._pending_value=None; self._pending_until=None; return actual
        if self._pending_until is not None and monotonic_time.monotonic() > self._pending_until: self._pending_value=None; self._pending_until=None; return actual
        return self._pending_value
    async def async_set_value(self, value: date):
        self._pending_value=value; self._pending_until=monotonic_time.monotonic()+PENDING_TIMEOUT_SECONDS; self.async_write_ha_state()
        try: await self.entity_description.set_fn(self, value.isoformat()); await self.coordinator.async_request_refresh()
        except Exception: self._pending_value=None; self._pending_until=None; self.async_write_ha_state(); raise
