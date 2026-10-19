"""Number entities."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .entity import SmartPoolConnectEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolNumberDescription(NumberEntityDescription):
    value_fn: Callable[[PoolStatus], float | None]
    set_fn: Callable[["SmartPoolNumber", float], Any]


async def _set_ph_target(e, v):
    await e.coordinator.client.async_set_ph_settings(target=v)


async def _set_ph_dosing_time(e, v):
    await e.coordinator.client.async_set_ph_settings(dosing_time=v)


async def _set_ph_pausing_time(e, v):
    await e.coordinator.client.async_set_ph_settings(pausing_time=v)


async def _set_rx_target(e, v):
    await e.coordinator.client.async_set_rx_settings(target=v)


async def _set_rx_dosing_time(e, v):
    await e.coordinator.client.async_set_rx_settings(dosing_time=v)


async def _set_rx_pausing_time(e, v):
    await e.coordinator.client.async_set_rx_settings(pausing_time=v)


async def _set_bw_interval(e, v):
    settings = await e.coordinator.client.async_get_backwash_settings()
    settings.interval = v
    await e.coordinator.client.async_set_backwash_settings(settings)


async def _set_bw_rinse(e, v):
    settings = await e.coordinator.client.async_get_backwash_settings()
    settings.rinse_duration = v
    await e.coordinator.client.async_set_backwash_settings(settings)


async def _set_bw_duration(e, v):
    settings = await e.coordinator.client.async_get_backwash_settings()
    settings.backwash_duration = v
    await e.coordinator.client.async_set_backwash_settings(settings)


NUMBERS = (
    SmartPoolNumberDescription(key="ph_target", translation_key="ph_target", native_min_value=5, native_max_value=9, native_step=0.1, mode=NumberMode.BOX, native_unit_of_measurement="pH", value_fn=lambda s: s.ph_target, set_fn=_set_ph_target),
    SmartPoolNumberDescription(key="ph_dosing_time", translation_key="ph_dosing_time", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="s", value_fn=lambda s: s.ph_dosing_time, set_fn=_set_ph_dosing_time),
    SmartPoolNumberDescription(key="ph_pausing_time", translation_key="ph_pausing_time", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="min", value_fn=lambda s: s.ph_pausing_time, set_fn=_set_ph_pausing_time),
    SmartPoolNumberDescription(key="rx_target", translation_key="rx_target", native_min_value=0, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="mV", value_fn=lambda s: s.rx_target, set_fn=_set_rx_target),
    SmartPoolNumberDescription(key="rx_dosing_time", translation_key="rx_dosing_time", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="s", value_fn=lambda s: s.rx_dosing_time, set_fn=_set_rx_dosing_time),
    SmartPoolNumberDescription(key="rx_pausing_time", translation_key="rx_pausing_time", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="min", value_fn=lambda s: s.rx_pausing_time, set_fn=_set_rx_pausing_time),
    SmartPoolNumberDescription(key="backwash_interval", translation_key="backwash_interval", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="d", value_fn=lambda s: s.backwash_interval, set_fn=_set_bw_interval),
    SmartPoolNumberDescription(key="backwash_rinse_duration", translation_key="backwash_rinse_duration", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="s", value_fn=lambda s: s.backwash_rinse_duration, set_fn=_set_bw_rinse),
    SmartPoolNumberDescription(key="backwash_duration", translation_key="backwash_duration", native_min_value=1, native_max_value=999, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="s", value_fn=lambda s: s.backwash_duration, set_fn=_set_bw_duration),
)

NAMES = {
    "ph_target": "pH Target",
    "ph_dosing_time": "pH Dosing Time",
    "ph_pausing_time": "pH Pause Time",
    "rx_target": "Rx Target",
    "rx_dosing_time": "Rx Dosing Time",
    "rx_pausing_time": "Rx Pause Time",
    "backwash_interval": "Backwash Setting Interval",
    "backwash_rinse_duration": "Backwash Setting Rinse Duration",
    "backwash_duration": "Backwash Setting Duration",
}


async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmartPoolNumber(entry.runtime_data, d) for d in NUMBERS)


class SmartPoolNumber(SmartPoolConnectEntity, NumberEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = NAMES[description.key]

    @property
    def native_value(self):
        return None if self.coordinator.data is None else self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float):
        if self.coordinator.data is None:
            return
        await self.entity_description.set_fn(self, value)
        await self.coordinator.async_request_refresh()
