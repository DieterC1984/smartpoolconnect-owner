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
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .entity import SmartPoolConnectEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolSensorDescription(SensorEntityDescription):
    """SmartPool sensor description."""

    value_fn: Callable[[PoolStatus], float | int | str | None]
    capabilities: tuple[str, ...] = ()
    require_value: bool = False


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
        capabilities=("cover_status", "cover", "covco_cover"),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="covco_cover_position",
        icon="mdi:window-shutter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.covco_cover_position,
        capabilities=("covco_cover",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_setpoint",
        icon="mdi:thermometer-chevron-up",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.phnix_setpoint,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_inlet_temperature",
        icon="mdi:thermometer-water",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.phnix_inlet_temperature,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_outlet_temperature",
        icon="mdi:thermometer-water",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.phnix_outlet_temperature,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_coil_temperature",
        icon="mdi:heating-coil",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.phnix_coil_temperature,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_ambient_temperature",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.phnix_ambient_temperature,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_mode",
        icon="mdi:heat-pump",
        value_fn=lambda s: s.phnix_mode,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_sub_mode",
        icon="mdi:heat-pump-outline",
        value_fn=lambda s: s.phnix_sub_mode,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_error",
        icon="mdi:alert-circle-outline",
        value_fn=lambda s: s.phnix_error,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="phnix_fail_0",
        icon="mdi:alert-decagram-outline",
        value_fn=lambda s: s.phnix_fail_0,
        capabilities=("phnix_heat_pump",),
        require_value=True,
    ),
)


def _is_supported(
    status: PoolStatus | None,
    description: SmartPoolSensorDescription,
) -> bool:
    """Return whether initial data proves this sensor is supported."""

    if status is None:
        return not description.capabilities and not description.require_value
    if description.capabilities and not any(
        capability in status.capabilities for capability in description.capabilities
    ):
        return False
    return not description.require_value or description.value_fn(status) is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartPool sensors."""

    async_add_entities(
        SmartPoolSensor(entry.runtime_data, description)
        for description in SENSORS
        if _is_supported(entry.runtime_data.data, description)
    )


class SmartPoolSensor(SmartPoolConnectEntity, SensorEntity):
    """SmartPool sensor entity."""

    entity_description: SmartPoolSensorDescription

    def __init__(self, coordinator, description: SmartPoolSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.key.startswith(("covco_", "phnix_")):
            self._attr_translation_key = None
        self._attr_name = {
            "ph": "pH",
            "rx": "Redox (Rx)",
            "water_temperature": "Water Temperature",
            "pump_speed": "Pump Speed",
            "cover_state": "Cover State",
            "covco_cover_position": "Covco Cover Position",
            "phnix_setpoint": "PHNIX Setpoint",
            "phnix_inlet_temperature": "PHNIX Inlet Temperature",
            "phnix_outlet_temperature": "PHNIX Outlet Temperature",
            "phnix_coil_temperature": "PHNIX Coil Temperature",
            "phnix_ambient_temperature": "PHNIX Ambient Temperature",
            "phnix_mode": "PHNIX Mode",
            "phnix_sub_mode": "PHNIX Sub-mode",
            "phnix_error": "PHNIX Error Code",
            "phnix_fail_0": "PHNIX Failure Register 0",
        }[description.key]

    @property
    def native_value(self):
        """Return native value."""

        if self.coordinator.data is None:
            return None

        return self.entity_description.value_fn(self.coordinator.data)