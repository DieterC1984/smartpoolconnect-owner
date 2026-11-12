"""Select entities for SmartPoolConnect Owner."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .api import (
    BACKWASH_PUMP_SPEED_OPTIONS,
    ECO_VALVE_REGULATION_OPTIONS,
    PUMP_SPEED_OPTIONS,
    PoolStatus,
)
from .entity import SmartPoolConnectEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolSelectDescription(SelectEntityDescription):
    """Describe a SmartPool select."""

    value_fn: Callable[[PoolStatus], str | None]
    set_fn: Callable[["SmartPoolSelect", str], Any]


async def _set_filter_pump_speed(entity, value: str) -> None:
    settings = await entity.coordinator.client.async_get_filter_settings(
        force_refresh=True
    )
    settings.pump_speed = value
    await entity.coordinator.client.async_set_filter_settings(settings)


def _set_filter_schedule_pump_speed(index: int):
    async def setter(entity, value: str) -> None:
        settings = await entity.coordinator.client.async_get_filter_settings(
            force_refresh=True
        )
        schedule = getattr(settings, f"schedule_{index}")
        if schedule is None:
            raise RuntimeError("Filter settings could not be read before update")
        schedule.pump_speed = value
        await entity.coordinator.client.async_set_filter_settings(settings)

    return setter


async def _set_backwash_pump_speed(entity, value: str) -> None:
    settings = await entity.coordinator.client.async_get_backwash_settings()
    settings.pump_speed = value
    await entity.coordinator.client.async_set_backwash_settings(settings)


async def _set_eco_valve_regulation(entity, value: str) -> None:
    settings = await entity.coordinator.client.async_get_eco_valve_settings()
    settings.regulation = value
    await entity.coordinator.client.async_set_eco_valve_settings(settings)


async def _set_temperature_pump_speed(entity, value: str) -> None:
    await entity.coordinator.client.async_set_temperature_settings(pump_speed=value)


SELECTS: tuple[SmartPoolSelectDescription, ...] = (
    SmartPoolSelectDescription(
        key="filter_pump_speed",
        translation_key="filter_pump_speed",
        icon="mdi:pump",
        options=list(PUMP_SPEED_OPTIONS),
        value_fn=lambda status: status.filter_pump_speed,
        set_fn=_set_filter_pump_speed,
    ),
    SmartPoolSelectDescription(
        key="filter_schedule_1_pump_speed",
        translation_key="filter_schedule_1_pump_speed",
        icon="mdi:pump",
        options=list(PUMP_SPEED_OPTIONS),
        value_fn=lambda status: status.filter_schedule_1_pump_speed,
        set_fn=_set_filter_schedule_pump_speed(1),
    ),
    SmartPoolSelectDescription(
        key="filter_schedule_2_pump_speed",
        translation_key="filter_schedule_2_pump_speed",
        icon="mdi:pump",
        options=list(PUMP_SPEED_OPTIONS),
        value_fn=lambda status: status.filter_schedule_2_pump_speed,
        set_fn=_set_filter_schedule_pump_speed(2),
    ),
    SmartPoolSelectDescription(
        key="filter_schedule_3_pump_speed",
        translation_key="filter_schedule_3_pump_speed",
        icon="mdi:pump",
        options=list(PUMP_SPEED_OPTIONS),
        value_fn=lambda status: status.filter_schedule_3_pump_speed,
        set_fn=_set_filter_schedule_pump_speed(3),
    ),
    SmartPoolSelectDescription(
        key="backwash_pump_speed",
        translation_key="backwash_pump_speed",
        icon="mdi:pump",
        options=list(BACKWASH_PUMP_SPEED_OPTIONS),
        value_fn=lambda status: status.backwash_pump_speed,
        set_fn=_set_backwash_pump_speed,
    ),
    SmartPoolSelectDescription(
        key="eco_valve_regulation",
        translation_key="eco_valve_regulation",
        icon="mdi:valve",
        options=list(ECO_VALVE_REGULATION_OPTIONS),
        value_fn=lambda status: status.eco_valve_regulation,
        set_fn=_set_eco_valve_regulation,
    ),
    SmartPoolSelectDescription(
        key="temperature_pump_speed",
        translation_key="temperature_pump_speed",
        icon="mdi:pump",
        options=list(PUMP_SPEED_OPTIONS),
        value_fn=lambda status: status.temperature_pump_speed,
        set_fn=_set_temperature_pump_speed,
    ),
)

NAMES = {
    "filter_pump_speed": "Filter Pump Standard Speed",
    "filter_schedule_1_pump_speed": "Filter Schedule 1 Pump Speed",
    "filter_schedule_2_pump_speed": "Filter Schedule 2 Pump Speed",
    "filter_schedule_3_pump_speed": "Filter Schedule 3 Pump Speed",
    "backwash_pump_speed": "Backwash Pump Speed",
    "eco_valve_regulation": "Eco Valve Regulation",
    "temperature_pump_speed": "Temperature Pump Speed",
}

_CAPABILITY_BY_KEY = {
    "filter_pump_speed": "filter",
    "filter_schedule_1_pump_speed": "filter",
    "filter_schedule_2_pump_speed": "filter",
    "filter_schedule_3_pump_speed": "filter",
    "backwash_pump_speed": "backwash",
    "eco_valve_regulation": "eco_valve",
    "temperature_pump_speed": "temperature",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities from detected capabilities."""

    capabilities = (
        entry.runtime_data.data.capabilities if entry.runtime_data.data else frozenset()
    )
    async_add_entities(
        SmartPoolSelect(entry.runtime_data, description)
        for description in SELECTS
        if _CAPABILITY_BY_KEY[description.key] in capabilities
    )


class SmartPoolSelect(SmartPoolConnectEntity, SelectEntity):
    """Representation of a SmartPool select."""

    entity_description: SmartPoolSelectDescription

    def __init__(self, coordinator, description: SmartPoolSelectDescription) -> None:
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
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        if option not in self.entity_description.options:
            raise ValueError(f"Unsupported option: {option}")
        await self.entity_description.set_fn(self, option)
        await self.coordinator.async_request_refresh()
