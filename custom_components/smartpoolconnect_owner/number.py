"""Number entities."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
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
    await e.coordinator.client.async_set_ph_target(v)


async def _set_ph_dosing_time(e, v):
    await e.coordinator.client.async_set_ph_settings(dosing_time=v)


async def _set_ph_pausing_time(e, v):
    await e.coordinator.client.async_set_ph_settings(pausing_time=v)


async def _set_rx_target(e, v):
    await e.coordinator.client.async_set_rx_target(v)


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


async def _set_zero_e_enable_threshold(e, v):
    await e.coordinator.client.async_set_zero_e_settings(threshold_enable=v)


async def _set_zero_e_disable_threshold(e, v):
    await e.coordinator.client.async_set_zero_e_settings(threshold_disable=v)


async def _set_zero_e_target_temperature(e, v):
    await e.coordinator.client.async_set_zero_e_settings(threshold_temperature=v)


async def _set_temperature_target(e, v):
    await e.coordinator.client.async_set_temperature_settings(target=v)


async def _set_temperature_interval(e, v):
    await e.coordinator.client.async_set_temperature_settings(interval=v)


async def _set_temperature_cooling_period(e, v):
    await e.coordinator.client.async_set_temperature_settings(cooling_period=v)


async def _set_temperature_offset_water(e, v):
    await e.coordinator.client.async_set_temperature_settings(offset_water=v)


async def _set_temperature_offset_ambient(e, v):
    await e.coordinator.client.async_set_temperature_settings(offset_ambient=v)


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
    SmartPoolNumberDescription(key="zero_e_enable_threshold", translation_key="zero_e_enable_threshold", icon="mdi:transmission-tower-export", device_class=NumberDeviceClass.POWER, native_min_value=-100000, native_max_value=100000, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="W", value_fn=lambda s: s.zero_e_enable_threshold, set_fn=_set_zero_e_enable_threshold),
    SmartPoolNumberDescription(key="zero_e_disable_threshold", translation_key="zero_e_disable_threshold", icon="mdi:transmission-tower-import", device_class=NumberDeviceClass.POWER, native_min_value=-100000, native_max_value=100000, native_step=1, mode=NumberMode.BOX, native_unit_of_measurement="W", value_fn=lambda s: s.zero_e_disable_threshold, set_fn=_set_zero_e_disable_threshold),
    SmartPoolNumberDescription(key="zero_e_target_temperature", translation_key="zero_e_target_temperature", icon="mdi:thermometer", device_class=NumberDeviceClass.TEMPERATURE, native_min_value=0, native_max_value=50, native_step=0.5, mode=NumberMode.BOX, native_unit_of_measurement="°C", value_fn=lambda s: s.zero_e_target_temperature, set_fn=_set_zero_e_target_temperature),
    SmartPoolNumberDescription(key="temperature_target", translation_key="temperature_target", icon="mdi:thermometer-chevron-up", device_class=NumberDeviceClass.TEMPERATURE, native_min_value=0, native_max_value=50, native_step=0.1, mode=NumberMode.BOX, native_unit_of_measurement="°C", value_fn=lambda s: s.temperature_target, set_fn=_set_temperature_target),
    SmartPoolNumberDescription(key="temperature_interval", translation_key="temperature_interval", icon="mdi:delta", native_min_value=0, native_max_value=999, native_step=1, mode=NumberMode.BOX, value_fn=lambda s: s.temperature_interval, set_fn=_set_temperature_interval),
    SmartPoolNumberDescription(key="temperature_cooling_period", translation_key="temperature_cooling_period", icon="mdi:timer-outline", native_min_value=0, native_max_value=9999, native_step=1, mode=NumberMode.BOX, value_fn=lambda s: s.temperature_cooling_period, set_fn=_set_temperature_cooling_period),
    SmartPoolNumberDescription(key="temperature_offset_water", translation_key="temperature_offset_water", icon="mdi:waves-arrow-up", device_class=NumberDeviceClass.TEMPERATURE, native_min_value=-20, native_max_value=20, native_step=0.1, mode=NumberMode.BOX, native_unit_of_measurement="°C", value_fn=lambda s: s.temperature_offset_water, set_fn=_set_temperature_offset_water),
    SmartPoolNumberDescription(key="temperature_offset_ambient", translation_key="temperature_offset_ambient", icon="mdi:thermometer-lines", device_class=NumberDeviceClass.TEMPERATURE, native_min_value=-20, native_max_value=20, native_step=0.1, mode=NumberMode.BOX, native_unit_of_measurement="°C", value_fn=lambda s: s.temperature_offset_ambient, set_fn=_set_temperature_offset_ambient),
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
    "zero_e_enable_threshold": "Zero-E Enable Threshold",
    "zero_e_disable_threshold": "Zero-E Disable Threshold",
    "zero_e_target_temperature": "Zero-E Target Temperature",
    "temperature_target": "Temperature Target",
    "temperature_interval": "Temperature Interval",
    "temperature_cooling_period": "Temperature Cooling Period",
    "temperature_offset_water": "Temperature Water Temperature Offset",
    "temperature_offset_ambient": "Temperature Ambient Temperature Offset",
}


async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    capabilities = entry.runtime_data.data.capabilities if entry.runtime_data.data else frozenset()
    timing_keys = {
        "ph_dosing_time",
        "ph_pausing_time",
        "rx_dosing_time",
        "rx_pausing_time",
    }
    async_add_entities(
        SmartPoolNumber(entry.runtime_data, description)
        for description in NUMBERS
        if (
            (not description.key.startswith("zero_e_") or "zero_e" in capabilities)
            and not (
                "dosing_timing_ms" in capabilities
                and description.key in timing_keys
            )
            and (
                not description.key.startswith("temperature_")
                or "temperature" in capabilities
            )
        )
    )


class SmartPoolNumber(SmartPoolConnectEntity, NumberEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.key.startswith(("zero_e_", "temperature_")):
            self._attr_translation_key = None
        self._attr_name = NAMES[description.key]

    @property
    def available(self) -> bool:
        if self.entity_description.key.startswith("zero_e_"):
            return bool(
                super().available
                and self.coordinator.data is not None
                and self.coordinator.data.zero_e_valid
            )
        if self.entity_description.key.startswith("temperature_"):
            return bool(
                super().available
                and self.coordinator.data is not None
                and self.coordinator.data.temperature_valid
            )
        return super().available

    @property
    def native_value(self):
        return None if self.coordinator.data is None else self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float):
        if self.coordinator.data is None:
            return
        await self.entity_description.set_fn(self, value)
        await self.coordinator.async_request_refresh()
