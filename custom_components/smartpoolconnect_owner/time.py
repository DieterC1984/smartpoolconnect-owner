"""Time entities for SmartPoolConnect Owner."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .entity import SmartPoolConnectEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolTimeDescription(TimeEntityDescription):
    """Describe a SmartPool time entity."""

    value_fn: Callable[[PoolStatus], str | None]
    set_fn: Callable[["SmartPoolTime", str], Any]


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


async def _set_lighting_start(entity, value: str) -> None:
    await entity.coordinator.client.async_set_lighting_settings(
        schedule_start_time=value
    )


async def _set_lighting_stop(entity, value: str) -> None:
    await entity.coordinator.client.async_set_lighting_settings(
        schedule_stop_time=value
    )


def _set_filter_schedule_time(index: int, attribute: str):
    async def setter(entity, value: str) -> None:
        settings = await entity.coordinator.client.async_get_filter_settings(
            force_refresh=True
        )
        schedule = getattr(settings, f"schedule_{index}")
        if schedule is None:
            raise RuntimeError("Filter settings could not be read before update")
        setattr(schedule, attribute, value)
        await entity.coordinator.client.async_set_filter_settings(settings)

    return setter


async def _set_backwash_start(entity, value: str) -> None:
    settings = await entity.coordinator.client.async_get_backwash_settings()
    settings.start_time = value
    await entity.coordinator.client.async_set_backwash_settings(settings)


async def _set_eco_valve_start(entity, value: str) -> None:
    settings = await entity.coordinator.client.async_get_eco_valve_settings()
    settings.start_time = value
    await entity.coordinator.client.async_set_eco_valve_settings(settings)


async def _set_eco_valve_stop(entity, value: str) -> None:
    settings = await entity.coordinator.client.async_get_eco_valve_settings()
    settings.stop_time = value
    await entity.coordinator.client.async_set_eco_valve_settings(settings)


async def _set_temperature_schedule_start(entity, value: str) -> None:
    await entity.coordinator.client.async_set_temperature_settings(
        schedule_start_time=value
    )


async def _set_temperature_schedule_stop(entity, value: str) -> None:
    await entity.coordinator.client.async_set_temperature_settings(
        schedule_stop_time=value
    )


TIMES: tuple[SmartPoolTimeDescription, ...] = (
    SmartPoolTimeDescription(
        key="lighting_schedule_start_time",
        translation_key="lighting_schedule_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.lighting_schedule_start_time,
        set_fn=_set_lighting_start,
    ),
    SmartPoolTimeDescription(
        key="lighting_schedule_stop_time",
        translation_key="lighting_schedule_stop_time",
        icon="mdi:clock-end",
        value_fn=lambda status: status.lighting_schedule_stop_time,
        set_fn=_set_lighting_stop,
    ),
    SmartPoolTimeDescription(
        key="filter_schedule_1_start_time",
        translation_key="filter_schedule_1_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.filter_schedule_1_start_time,
        set_fn=_set_filter_schedule_time(1, "start_time"),
    ),
    SmartPoolTimeDescription(
        key="filter_schedule_1_stop_time",
        translation_key="filter_schedule_1_stop_time",
        icon="mdi:clock-end",
        value_fn=lambda status: status.filter_schedule_1_stop_time,
        set_fn=_set_filter_schedule_time(1, "stop_time"),
    ),
    SmartPoolTimeDescription(
        key="filter_schedule_2_start_time",
        translation_key="filter_schedule_2_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.filter_schedule_2_start_time,
        set_fn=_set_filter_schedule_time(2, "start_time"),
    ),
    SmartPoolTimeDescription(
        key="filter_schedule_2_stop_time",
        translation_key="filter_schedule_2_stop_time",
        icon="mdi:clock-end",
        value_fn=lambda status: status.filter_schedule_2_stop_time,
        set_fn=_set_filter_schedule_time(2, "stop_time"),
    ),
    SmartPoolTimeDescription(
        key="filter_schedule_3_start_time",
        translation_key="filter_schedule_3_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.filter_schedule_3_start_time,
        set_fn=_set_filter_schedule_time(3, "start_time"),
    ),
    SmartPoolTimeDescription(
        key="filter_schedule_3_stop_time",
        translation_key="filter_schedule_3_stop_time",
        icon="mdi:clock-end",
        value_fn=lambda status: status.filter_schedule_3_stop_time,
        set_fn=_set_filter_schedule_time(3, "stop_time"),
    ),
    SmartPoolTimeDescription(
        key="backwash_start_time",
        translation_key="backwash_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.backwash_start_time,
        set_fn=_set_backwash_start,
    ),
    SmartPoolTimeDescription(
        key="eco_valve_start_time",
        translation_key="eco_valve_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.eco_valve_start_time,
        set_fn=_set_eco_valve_start,
    ),
    SmartPoolTimeDescription(
        key="eco_valve_stop_time",
        translation_key="eco_valve_stop_time",
        icon="mdi:clock-end",
        value_fn=lambda status: status.eco_valve_stop_time,
        set_fn=_set_eco_valve_stop,
    ),
    SmartPoolTimeDescription(
        key="temperature_schedule_start_time",
        translation_key="temperature_schedule_start_time",
        icon="mdi:clock-start",
        value_fn=lambda status: status.temperature_schedule_start_time,
        set_fn=_set_temperature_schedule_start,
    ),
    SmartPoolTimeDescription(
        key="temperature_schedule_stop_time",
        translation_key="temperature_schedule_stop_time",
        icon="mdi:clock-end",
        value_fn=lambda status: status.temperature_schedule_stop_time,
        set_fn=_set_temperature_schedule_stop,
    ),
)

NAMES = {
    "lighting_schedule_start_time": "Lighting Schedule Start Time",
    "lighting_schedule_stop_time": "Lighting Schedule Stop Time",
    "filter_schedule_1_start_time": "Filter Schedule 1 Start Time",
    "filter_schedule_1_stop_time": "Filter Schedule 1 Stop Time",
    "filter_schedule_2_start_time": "Filter Schedule 2 Start Time",
    "filter_schedule_2_stop_time": "Filter Schedule 2 Stop Time",
    "filter_schedule_3_start_time": "Filter Schedule 3 Start Time",
    "filter_schedule_3_stop_time": "Filter Schedule 3 Stop Time",
    "backwash_start_time": "Backwash Start Time",
    "eco_valve_start_time": "Eco Valve Start Time",
    "eco_valve_stop_time": "Eco Valve Stop Time",
    "temperature_schedule_start_time": "Temperature Schedule Start Time",
    "temperature_schedule_stop_time": "Temperature Schedule Stop Time",
}

_CAPABILITY_BY_KEY = {
    "lighting_schedule_start_time": "lighting",
    "lighting_schedule_stop_time": "lighting",
    "filter_schedule_1_start_time": "filter",
    "filter_schedule_1_stop_time": "filter",
    "filter_schedule_2_start_time": "filter",
    "filter_schedule_2_stop_time": "filter",
    "filter_schedule_3_start_time": "filter",
    "filter_schedule_3_stop_time": "filter",
    "backwash_start_time": "backwash",
    "eco_valve_start_time": "eco_valve",
    "eco_valve_stop_time": "eco_valve",
    "temperature_schedule_start_time": "temperature",
    "temperature_schedule_stop_time": "temperature",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities from detected capabilities."""

    capabilities = (
        entry.runtime_data.data.capabilities if entry.runtime_data.data else frozenset()
    )
    async_add_entities(
        SmartPoolTime(entry.runtime_data, description)
        for description in TIMES
        if _CAPABILITY_BY_KEY[description.key] in capabilities
    )


class SmartPoolTime(SmartPoolConnectEntity, TimeEntity):
    """Representation of a SmartPool time setting."""

    entity_description: SmartPoolTimeDescription

    def __init__(self, coordinator, description: SmartPoolTimeDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.key.startswith("temperature_"):
            self._attr_translation_key = None
        self._attr_name = NAMES[description.key]

    @property
    def available(self) -> bool:
        if self.entity_description.key.startswith("temperature_"):
            return bool(
                super().available
                and self.coordinator.data is not None
                and self.coordinator.data.temperature_valid
            )
        return super().available

    @property
    def native_value(self) -> time | None:
        if self.coordinator.data is None:
            return None
        value = self.entity_description.value_fn(self.coordinator.data)
        if value is None:
            return None
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        await self.entity_description.set_fn(self, _format_time(value))
        await self.coordinator.async_request_refresh()
