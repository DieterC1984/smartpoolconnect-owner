"""Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .entity import SmartPoolConnectEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolSensorDescription(SensorEntityDescription):
    """SmartPool sensor description."""

    value_fn: Callable[[PoolStatus], float | str | None]


SENSORS = (
    SmartPoolSensorDescription(
        key="ph",
        translation_key="ph",
        icon="mdi:ph",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ph,
    ),
    SmartPoolSensorDescription(
        key="rx",
        translation_key="rx",
        icon="mdi:flash",
        native_unit_of_measurement="mV",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.rx,
    ),
    SmartPoolSensorDescription(
        key="water_temperature",
        translation_key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.water_temperature,
    ),
    SmartPoolSensorDescription(
        key="pump_speed",
        translation_key="pump_speed",
        icon="mdi:pump",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "low", "medium", "high", "maximum"],
        value_fn=lambda s: s.pump_speed,
    ),
    SmartPoolSensorDescription(
        key="cover_state",
        translation_key="cover_state",
        icon="mdi:window-shutter",
        device_class=SensorDeviceClass.ENUM,
        options=["open", "closed", "opening", "closing"],
        value_fn=lambda s: s.cover_state,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartPool sensors."""

    async_add_entities(
        SmartPoolSensor(entry.runtime_data, description)
        for description in SENSORS
    )


class SmartPoolSensor(SmartPoolConnectEntity, SensorEntity):
    """SmartPool sensor entity."""

    entity_description: SmartPoolSensorDescription

    def __init__(self, coordinator, description: SmartPoolSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = {
            "ph": "pH",
            "rx": "Redox (Rx)",
            "water_temperature": "Water Temperature",
            "pump_speed": "Pump Speed",
            "cover_state": "Cover State",
        }[description.key]

    @property
    def native_value(self):
        """Return native value."""

        if self.coordinator.data is None:
            return None

        return self.entity_description.value_fn(self.coordinator.data)