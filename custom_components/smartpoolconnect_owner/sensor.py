"""Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SmartPoolConnectConfigEntry
from .api import PoolStatus
from .const import CONF_POOL_ID, DOMAIN
from .entity import SmartPoolConnectEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolSensorDescription(SensorEntityDescription):
    """SmartPool sensor description."""

    value_fn: Callable[[PoolStatus], Any]
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
        key="lighting_state",
        translation_key="lighting_state",
        icon="mdi:lightbulb",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "on"],
        value_fn=lambda s: s.lighting_state,
        capabilities=("live_lighting_state",),
    ),
    SmartPoolSensorDescription(
        key="filter_operating_mode",
        translation_key="filter_operating_mode",
        icon="mdi:pump",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "off",
            "schedule_1",
            "schedule_2",
            "schedule_3",
            "heating",
            "solar",
            "backwash",
            "cooling",
            "manual",
            "frost_protection",
            "always_active",
            "cover",
            "valve_error",
            "cover_low",
            "too_hot",
            "invalid",
        ],
        value_fn=lambda s: s.filter_operating_mode,
        capabilities=("live_filter_operating_mode",),
    ),
    SmartPoolSensorDescription(
        key="cl_shock_status",
        translation_key="cl_shock_status",
        icon="mdi:flask-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "waiting_for_pump", "active"],
        value_fn=lambda s: s.cl_shock_status,
        capabilities=("cl_shock",),
    ),
    SmartPoolSensorDescription(
        key="ph_dosing_flow_status",
        translation_key="ph_dosing_flow_status",
        icon="mdi:water-check-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["flow_ok", "no_flow"],
        value_fn=lambda s: s.ph_dosing_flow_status,
        capabilities=("ph_dosing_flow",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="cl_dosing_flow_status",
        translation_key="cl_dosing_flow_status",
        icon="mdi:water-check-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["flow_ok", "no_flow"],
        value_fn=lambda s: s.cl_dosing_flow_status,
        capabilities=("cl_dosing_flow",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="v3_flow_paddle_status",
        translation_key="v3_flow_paddle_status",
        icon="mdi:water-check-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["flow_ok", "no_flow"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.v3_flow_paddle_status,
        capabilities=("v3_flow_paddle",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="v3_ph_control",
        translation_key="v3_ph_control",
        icon="mdi:code-braces",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.v3_ph_control,
        capabilities=("v3_ph_control",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="v3_cl_control",
        translation_key="v3_cl_control",
        icon="mdi:code-braces",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.v3_cl_control,
        capabilities=("v3_cl_control",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="carrier_version",
        translation_key="carrier_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.carrier_version,
        capabilities=("v3_carrier_version",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="filter_modbus_power",
        translation_key="filter_modbus_power",
        icon="mdi:flash",
        native_unit_of_measurement="W",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.filter_modbus_power,
        capabilities=("v3_filter_modbus_power",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="filter_modbus_status",
        translation_key="filter_modbus_status",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.filter_modbus_status,
        capabilities=("v3_filter_modbus_status",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="filter_pump_error",
        translation_key="filter_pump_error",
        icon="mdi:alert-circle-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["ok", "error"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.filter_pump_error,
        capabilities=("v3_filter_pump_error",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="filter_pump_error_code",
        translation_key="filter_pump_error_code",
        icon="mdi:alert-decagram-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.filter_pump_error_code,
        capabilities=("v3_filter_pump_error_code",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="ph_input_error",
        translation_key="ph_input_error",
        icon="mdi:ph",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.ph_input_error,
        capabilities=("v3_ph_input_error",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="rx_input_error",
        translation_key="rx_input_error",
        icon="mdi:flash-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.rx_input_error,
        capabilities=("v3_rx_input_error",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="tds_pollution",
        translation_key="tds_pollution",
        icon="mdi:water-opacity",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.tds_pollution,
        capabilities=("v3_tds_pollution",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="tds_salt",
        translation_key="tds_salt",
        icon="mdi:shaker-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.tds_salt,
        capabilities=("v3_tds_salt",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="ph_dosing_time_readonly",
        icon="mdi:timer-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ph_dosing_time,
        capabilities=("dosing_timing_ms",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="ph_pausing_time_readonly",
        icon="mdi:timer-pause-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ph_pausing_time,
        capabilities=("dosing_timing_ms",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="rx_dosing_time_readonly",
        icon="mdi:timer-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.rx_dosing_time,
        capabilities=("dosing_timing_ms",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="rx_pausing_time_readonly",
        icon="mdi:timer-pause-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.rx_pausing_time,
        capabilities=("dosing_timing_ms",),
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="cover_state",
        translation_key="cover_state",
        icon="mdi:window-shutter",
        device_class=SensorDeviceClass.ENUM,
        options=["open", "closed", "opening", "closing"],
        value_fn=lambda s: s.cover_state,
        capabilities=("cover_status", "cover", "cover_control", "covco_cover"),
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
    SmartPoolSensorDescription(
        key="ambient_temperature",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ambient_temperature,
    ),
    SmartPoolSensorDescription(
        key="system_temperature_imx",
        icon="mdi:thermometer-lines",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.system_temperature_imx,
    ),
    SmartPoolSensorDescription(
        key="system_temperature_main",
        icon="mdi:thermometer-lines",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.system_temperature_main,
    ),
    SmartPoolSensorDescription(
        key="last_backwash",
        icon="mdi:history",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.last_backwash_at,
    ),
    SmartPoolSensorDescription(
        key="pool_name",
        icon="mdi:pool",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.name,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="mac_address",
        icon="mdi:network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.mac_address,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="pool_id",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.pool_id,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="gui_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.gui_version,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="main_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.main_version,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="io_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.io_version,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="deck_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.deck_version,
        require_value=True,
    ),
    SmartPoolSensorDescription(
        key="api_version",
        icon="mdi:api",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.api_version,
    ),
)


def _is_supported(
    status: PoolStatus | None,
    description: SmartPoolSensorDescription,
) -> bool:
    """Return whether initial data proves this sensor is supported."""

    if status is None:
        return not description.capabilities and not description.require_value
    if description.capabilities:
        # Capability is structural; a temporarily missing current reading must
        # not suppress entity creation. Its native value will remain None and
        # Home Assistant will report Unknown until data arrives.
        return any(
            capability in status.capabilities
            for capability in description.capabilities
        )
    return not description.require_value or description.value_fn(status) is not None


def _repair_legacy_firmware_names(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
) -> None:
    """Clear only the known legacy pool-name overrides for GUI and MAIN."""

    status = entry.runtime_data.data
    if status is None or not status.name:
        return

    pool_id = entry.data[CONF_POOL_ID]
    entity_registry = er.async_get(hass)
    for key in ("gui_version", "main_version"):
        entity_id = entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{pool_id}_{key}"
        )
        if entity_id is None:
            continue
        registry_entry = entity_registry.async_get(entity_id)
        if registry_entry is not None and registry_entry.name == status.name:
            entity_registry.async_update_entity(entity_id, name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartPool sensors."""

    _repair_legacy_firmware_names(hass, entry)
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
        if description.key.startswith(("covco_", "phnix_")) or description.key.endswith("_readonly"):
            self._attr_translation_key = None
        self._attr_name = {
            "ph": "pH",
            "rx": "Cl (Rx)",
            "water_temperature": "Water Temperature",
            "pump_speed": "Pump Speed",
            "lighting_state": "Lighting State",
            "filter_operating_mode": "Filter Operating Mode",
            "cl_shock_status": "Cl Shock Treatment Status",
            "ph_dosing_flow_status": "pH Dosing Flow Status",
            "cl_dosing_flow_status": "Cl Dosing Flow Status",
            "v3_flow_paddle_status": "V3 Flow Paddle Status",
            "v3_ph_control": "V3 pH Control Code",
            "v3_cl_control": "V3 Cl Control Code",
            "carrier_version": "Carrier Firmware Version",
            "filter_modbus_power": "Filter Modbus Power",
            "filter_modbus_status": "Filter Modbus Status",
            "filter_pump_error": "Filter Pump Error",
            "filter_pump_error_code": "Filter Pump Error Code",
            "ph_input_error": "pH Input Error",
            "rx_input_error": "Cl (Rx) Input Error",
            "tds_pollution": "TDS Pollution",
            "tds_salt": "TDS Salt",
            "ph_dosing_time_readonly": "pH Dosing Time",
            "ph_pausing_time_readonly": "pH Pause Time",
            "rx_dosing_time_readonly": "Cl (Rx) Dosing Time",
            "rx_pausing_time_readonly": "Cl (Rx) Pause Time",
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
            "ambient_temperature": "Ambient Temperature",
            "system_temperature_imx": "System Temperature IMX",
            "system_temperature_main": "System Temperature MAIN",
            "last_backwash": "Last Backwash",
            "pool_name": "Name",
            "mac_address": "MAC Address",
            "pool_id": "Pool ID",
            "gui_version": "GUI Version",
            "main_version": "MAIN Version",
            "io_version": "IO Version",
            "deck_version": "DECK Version",
            "api_version": "API Version",
        }[description.key]

    @property
    def native_value(self):
        """Return native value."""

        if self.coordinator.data is None:
            return None

        if self.entity_description.key == "last_backwash":
            value = self.coordinator.data.last_backwash_at
            if value is None:
                return None
            local_date = dt_util.as_local(value).date()
            return max(0, (dt_util.now().date() - local_date).days)

        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose useful context without changing Home Assistant-native states."""

        if self.entity_description.key == "cl_shock_status":
            if (
                self.coordinator.data is not None
                and self.coordinator.data.cl_shock_status == "waiting_for_pump"
            ):
                return {
                    "waiting_behavior": (
                        "The Cl shock treatment will start automatically when "
                        "the filter pump starts. The integration does not start "
                        "the pump."
                    )
                }
            return None

        if (
            self.entity_description.key != "last_backwash"
            or self.coordinator.data is None
            or self.coordinator.data.last_backwash_at is None
        ):
            return None
        local_date = dt_util.as_local(
            self.coordinator.data.last_backwash_at
        ).date()
        days = max(0, (dt_util.now().date() - local_date).days)
        return {
            "date": local_date.isoformat(),
            "relative": f"{days} day{'s' if days != 1 else ''} ago",
            "source": "historical",
        }