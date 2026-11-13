"""Async client for SmartPoolConnect owner portal."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
import math
import re
import secrets
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .const import DEFAULT_BASE_URL, DEFAULT_OAUTH_BASE_URL, PUMP_SPEEDS, SETTINGS_CACHE_INTERVAL
from .devalue import RemixDecodeError, UNDEFINED, decode_remix, find_dicts, route_data

_LOGGER = logging.getLogger(__name__)

RX_MIN_VALID: float = 100.0
RX_MAX_VALID: float = 1500.0
RX_MAX_DELTA: float = 300.0
_LAST_VALID_RX: float | None = None

DAYS: tuple[str, ...] = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PUMP_SPEED_OPTIONS: tuple[str, ...] = ("off", "low", "medium", "high", "maximum")
BACKWASH_PUMP_SPEED_OPTIONS: tuple[str, ...] = ("off", "low", "medium", "high", "max")
ECO_VALVE_REGULATION_OPTIONS: tuple[str, ...] = ("off", "always", "buffer_tank")


class SmartPoolConnectError(Exception):
    """Base error for SmartPoolConnect."""


class AuthenticationError(SmartPoolConnectError):
    """Credentials or session authorisation failed."""


class OAuthFlowError(SmartPoolConnectError):
    """The SmartPoolConnect OAuth flow returned an unexpected response."""


class TransientServerError(SmartPoolConnectError):
    """Temporary SmartPoolConnect backend error."""

@dataclass(slots=True)
class PoolFilterSchedule:
    """Filter schedule configuration."""
    enabled: bool | None = None
    pump_speed: str | None = None
    start_time: str | None = None
    stop_time: str | None = None
    days: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolFilterSettings:
    """Filter pump configuration."""
    always_active: bool | None = None
    pump_speed: str | None = None
    schedule_1: PoolFilterSchedule | None = None
    schedule_2: PoolFilterSchedule | None = None
    schedule_3: PoolFilterSchedule | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolStatus:
    """Normalized pool status for Home Assistant entities."""
    pool_id: str
    name: str | None = None
    online: bool | None = None
    ph: float | None = None
    ph_target: float | None = None
    ph_dosing_time: float | None = None
    ph_pausing_time: float | None = None
    rx: float | None = None
    rx_target: float | None = None
    rx_dosing_time: float | None = None
    rx_pausing_time: float | None = None
    lighting_on: bool | None = None
    lighting_always_active: bool | None = None
    lighting_cover_disabled: bool | None = None
    lighting_schedule_enabled: bool | None = None
    lighting_schedule_start_time: str | None = None
    lighting_schedule_stop_time: str | None = None
    lighting_schedule_days: tuple[str, ...] = ()
    filter_always_active: bool | None = None
    filter_pump_speed: str | None = None
    filter_schedule_1_enabled: bool | None = None
    filter_schedule_1_pump_speed: str | None = None
    filter_schedule_1_start_time: str | None = None
    filter_schedule_1_stop_time: str | None = None
    filter_schedule_1_days: tuple[str, ...] = ()
    filter_schedule_2_enabled: bool | None = None
    filter_schedule_2_pump_speed: str | None = None
    filter_schedule_2_start_time: str | None = None
    filter_schedule_2_stop_time: str | None = None
    filter_schedule_2_days: tuple[str, ...] = ()
    filter_schedule_3_enabled: bool | None = None
    filter_schedule_3_pump_speed: str | None = None
    filter_schedule_3_start_time: str | None = None
    filter_schedule_3_stop_time: str | None = None
    filter_schedule_3_days: tuple[str, ...] = ()
    backwash_interval: float | None = None
    backwash_rinse_duration: float | None = None
    backwash_duration: float | None = None
    backwash_pump_speed: str | None = None
    backwash_start_date: str | None = None
    backwash_start_time: str | None = None
    eco_valve_regulation: str | None = None
    eco_valve_start_time: str | None = None
    eco_valve_stop_time: str | None = None
    zero_e_enabled: bool | None = None
    zero_e_enable_threshold: float | None = None
    zero_e_disable_threshold: float | None = None
    zero_e_target_temperature: float | None = None
    zero_e_valid: bool = False
    temperature_target: float | None = None
    temperature_interval: float | None = None
    temperature_priority: bool | None = None
    temperature_pump_speed: str | None = None
    temperature_cooling_period: float | None = None
    temperature_offset_water: float | None = None
    temperature_offset_ambient: float | None = None
    temperature_frost_protection: bool | None = None
    temperature_schedule_start_time: str | None = None
    temperature_schedule_stop_time: str | None = None
    temperature_schedule_enabled: bool | None = None
    temperature_schedule_days: tuple[str, ...] = ()
    temperature_valid: bool = False
    water_temperature: float | None = None
    water_temperature_target: float | None = None
    outside_temperature: float | None = None
    solar_temperature: float | None = None
    pump_speed: str | None = None
    pump_status: bool | None = None
    heating_on: bool | None = None
    cover_state: str | None = None
    cover_protection: bool | None = None
    cover_pump_open: bool | None = None
    cover_pump_close: bool | None = None
    cover_pump_low_speed: bool | None = None
    covco_cover_position: float | None = None
    phnix_setpoint: float | None = None
    phnix_inlet_temperature: float | None = None
    phnix_outlet_temperature: float | None = None
    phnix_coil_temperature: float | None = None
    phnix_ambient_temperature: float | None = None
    phnix_mode: int | None = None
    phnix_sub_mode: int | None = None
    phnix_error: int | None = None
    phnix_fail_0: int | None = None
    capabilities: frozenset[str] = frozenset()
    raw_live_status: dict[str, Any] | None = None
    raw_v3_status: dict[str, Any] | None = None
    raw_pool_status: dict[str, Any] | None = None


@dataclass(slots=True)
class PoolPhSettings:
    target: float | None = None
    dosing_time: float | None = None
    pausing_time: float | None = None
    dosing_type: str | None = None
    gain: str | None = None
    offset: str | None = None
    probe_offset: str | None = None
    overdose_alert: str | None = None
    min_water_temp: str | None = None
    hysteresis: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolRxSettings:
    target: float | None = None
    dosing_time: float | None = None
    pausing_time: float | None = None
    overdose_alert: str | None = None
    min_water_temp: str | None = None
    probe: str | None = None
    offset: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolLightingSettings:
    always_active: bool | None = None
    cover_disabled: bool | None = None
    schedule_enabled: bool | None = None
    schedule_start_time: str | None = None
    schedule_stop_time: str | None = None
    schedule_days: tuple[str, ...] = ()
    dimming: str | None = None
    switch_pulse: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolCoverSettings:
    """Cover/deck configuration."""
    protection: bool | None = None
    pump_open: bool | None = None
    pump_close: bool | None = None
    pump_low_speed: bool | None = None
    longitude: str | None = None
    latitude: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolBackwashSettings:
    interval: float | None = None
    rinse_duration: float | None = None
    backwash_duration: float | None = None
    pump_speed: str | None = None
    start_date: str | None = None
    start_time: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolEcoValveSettings:
    regulation: str | None = None
    start_time: str | None = None
    stop_time: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolZeroESettings:
    """Zero-E energy-aware temperature configuration."""

    enabled: bool | None = None
    threshold_enable: float | None = None
    threshold_disable: float | None = None
    threshold_temperature: float | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolTemperatureSchedule:
    """Temperature schedule configuration."""

    start_time: str | None = None
    stop_time: str | None = None
    enabled: bool | None = None
    days: tuple[str, ...] = ()


@dataclass(slots=True)
class PoolTemperatureSettings:
    """Write-complete temperature configuration."""

    target: float | None = None
    interval: float | None = None
    priority: bool | None = None
    pump_speed: str | None = None
    cooling_period: float | None = None
    offset_water: float | None = None
    offset_ambient: float | None = None
    frost_protection: bool | None = None
    schedule: PoolTemperatureSchedule | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_finite_float(value: Any) -> float | None:
    """Return a finite numeric value, rejecting booleans, NaN, and infinity."""

    if isinstance(value, bool):
        return None
    converted = _as_float(value)
    return converted if converted is not None and math.isfinite(converted) else None


def _as_int(value: Any) -> int | None:
    """Return an integer value without accepting booleans or fractions."""

    converted = _as_finite_float(value)
    if converted is None or not converted.is_integer():
        return None
    return int(converted)


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "on", "yes", "checked"):
            return True
        if normalized in ("false", "0", "off", "no", ""):
            return False
    return None


def _find_key(obj: Any, names: set[str]) -> Any:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in names:
                return value
        for value in obj.values():
            found = _find_key(value, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, names)
            if found is not None:
                return found
    return None


def _pump_speed(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return PUMP_SPEEDS.get(numeric)


def _cover_state(value: Any) -> str | None:
    return {1: "open", 2: "closed", 3: "opening", 4: "closing", "open": "open", "closed": "closed", "opening": "opening", "closing": "closing"}.get(value)


def _find_data_block(obj: Any, name: str) -> dict[str, Any] | None:
    """Find one named controller block without confusing it with a column."""

    if isinstance(obj, dict):
        direct = obj.get(name)
        if isinstance(direct, dict):
            return direct
        for value in obj.values():
            found = _find_data_block(value, name)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_data_block(value, name)
            if found is not None:
                return found
    return None


def _column_values(block: dict[str, Any] | None) -> dict[str, Any]:
    """Convert a SmartPool ``columns`` block to a simple name/value mapping."""

    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        return {}
    values: dict[str, Any] = {}
    for column in block["columns"]:
        if not isinstance(column, dict) or not isinstance(column.get("name"), str):
            continue
        values[column["name"]] = column.get("value")
    return values


def _covco_telemetry(data: Any) -> tuple[bool, float | None, str | None]:
    """Return validated Covco presence, position percentage, and endpoint state.

    Position is derived only from the encoder endpoints supplied by the
    controller. Movement is derived from measured motor activity and the
    wished endpoint, so undocumented state/direction enums are not assumed.
    """

    values = _column_values(_find_data_block(data, "covco_data"))
    open_location = _as_finite_float(values.get("open_location"))
    close_location = _as_finite_float(values.get("close_location"))
    current_location = _as_finite_float(values.get("current_location"))
    hysteresis = _as_finite_float(values.get("hys_location"))
    if (
        open_location is None
        or close_location is None
        or current_location is None
        or hysteresis is None
        or hysteresis < 0
        or math.isclose(open_location, close_location)
    ):
        return False, None, None

    span = open_location - close_location
    position = max(0.0, min(100.0, (current_location - close_location) / span * 100.0))
    tolerance = min(hysteresis, abs(span) / 2)
    state = None
    motor_power = _as_finite_float(values.get("motor_power_w")) or 0.0
    motor_current = _as_finite_float(values.get("motor_current_a")) or 0.0
    motor_ccr = _as_finite_float(values.get("ccr_motor")) or 0.0
    wished_location = _as_finite_float(values.get("wished_location"))
    motor_active = motor_power > 0.5 or motor_current > 0.05 or motor_ccr > 0

    if motor_active and wished_location is not None:
        if abs(wished_location - open_location) <= tolerance:
            state = "opening"
        elif abs(wished_location - close_location) <= tolerance:
            state = "closing"
    elif abs(current_location - open_location) <= tolerance:
        state = "open"
    elif abs(current_location - close_location) <= tolerance:
        state = "closed"
    return True, round(position, 1), state


def _phnix_telemetry(data: Any) -> tuple[bool, dict[str, float | int | None]]:
    """Return PHNIX telemetry only when the block contains real measurements."""

    values = _column_values(_find_data_block(data, "temperature_phnx_data"))
    telemetry: dict[str, float | int | None] = {
        "setpoint": _as_finite_float(values.get("sp")),
        "inlet": _as_finite_float(values.get("inlet")),
        "outlet": _as_finite_float(values.get("outlet")),
        "coil": _as_finite_float(values.get("coil")),
        "ambient": _as_finite_float(values.get("ambient")),
        "mode": _as_int(values.get("mode")),
        "sub_mode": _as_int(values.get("sub_mode")),
        "error": _as_int(values.get("err")),
        "fail_0": _as_int(values.get("fail_0")),
    }
    temperatures = tuple(
        telemetry[key] for key in ("setpoint", "inlet", "outlet", "coil", "ambient")
    )
    valid = (
        telemetry["setpoint"] is not None
        and telemetry["inlet"] is not None
        and telemetry["outlet"] is not None
        and any(value not in (None, 0, 0.0) for value in temperatures)
    )
    return valid, telemetry if valid else {}


def _analogue_telemetry(data: Any) -> dict[str, float | None]:
    """Return calibrated analogue values exposed by the V3 controller API."""

    values = _column_values(_find_data_block(data, "analoge_data"))
    return {
        "ph": _as_finite_float(values.get("ph")),
        "rx": _as_finite_float(values.get("rx")),
        "water_temperature": _as_finite_float(values.get("water_t")),
        "ambient_temperature": _as_finite_float(values.get("ambient_t")),
    }


def _v3_filter_telemetry(data: Any) -> tuple[bool, str | None]:
    """Return pump running state and speed from a V3 filter block."""

    values = _column_values(_find_data_block(data, "filter_data"))
    actual = _as_int(values.get("actual"))
    if actual is None:
        return False, None
    return actual != 0, _pump_speed(actual)


def _v3_lighting_state(data: Any) -> bool | None:
    """Return the V3 lighting output state when its block is available."""

    values = _column_values(_find_data_block(data, "lighting_data"))
    active = _as_int(values.get("active"))
    return None if active is None else active != 0


def _decode_route_response(text: Any) -> Any | None:
    """Decode one Remix response, returning None for malformed content."""
    if not isinstance(text, str):
        return text
    try:
        return decode_remix(text)
    except RemixDecodeError:
        _LOGGER.debug("Could not decode Remix route response", exc_info=True)
        return None


def _route_entries(decoded: Any) -> list[tuple[str, Any]]:
    if not isinstance(decoded, dict):
        return []
    entries: list[tuple[str, Any]] = []
    for route_id, envelope in decoded.items():
        if not isinstance(route_id, str) or not route_id.startswith("pool/routes/"):
            continue
        data = envelope.get("data") if isinstance(envelope, dict) else None
        entries.append((route_id, data))
    return entries


def _find_pool_record(decoded: Any, pool_id: str | None = None) -> dict[str, Any] | None:
    """Find a pool by semantic fields rather than flattened slot numbers."""
    direct = route_data(decoded, "pool/routes/$pid")
    if isinstance(direct, dict):
        if pool_id is None or direct.get("pid") == pool_id:
            return direct

    for _, data in _route_entries(decoded):
        if not isinstance(data, dict):
            continue
        pools = data.get("pools")
        items = pools.get("items") if isinstance(pools, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and (pool_id is None or item.get("pid") == pool_id):
                    return item

    # Generic final pass supports route-id changes while still requiring a
    # pool-shaped record and, when supplied, an exact pool id.
    stack = [decoded]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if not isinstance(current, (dict, list)):
            continue
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if isinstance(current, dict):
            if (
                isinstance(current.get("pid"), str)
                and (pool_id is None or current.get("pid") == pool_id)
                and any(key in current for key in ("ph", "cl", "filter", "temperature"))
            ):
                return current
            stack.extend(current.values())
        else:
            stack.extend(current)
    return None


def _module_and_config(
    decoded: Any,
    module: str,
    *,
    pool_id: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Return module presence and its write-complete config candidate."""
    def module_present(payload: dict[str, Any]) -> bool:
        if isinstance(payload.get("config"), dict):
            return True
        return any(
            value not in (None, UNDEFINED, [], {})
            for key in ("status", "metrics")
            if (value := payload.get(key)) is not None
        )

    pool = _find_pool_record(decoded, pool_id)
    if isinstance(pool, dict) and module in pool:
        payload = pool.get(module)
        if isinstance(payload, dict):
            config = payload.get("config")
            return module_present(payload), config if isinstance(config, dict) else None
        return False, None

    for route_id, data in _route_entries(decoded):
        if not isinstance(data, dict):
            continue
        payload: Any | None = None
        if module in data:
            payload = data[module]
        elif module == "filter" and route_id.endswith("$pid.filter"):
            payload = data
        elif module == "backwash" and route_id.endswith("filter.backwash"):
            payload = data.get("backwash")
        elif module == "eco_valve" and route_id.endswith("filter.eco-valve"):
            # A null v1_eco_valve explicitly means the capability is absent.
            payload = data.get("v1_eco_valve")
        elif module == "lighting" and route_id.endswith("$pid.lighting"):
            payload = data.get("lighting") or data.get("v1_lighting")
        elif module == "cover" and route_id.endswith("$pid.cover"):
            payload = data.get("cover") or data.get("v1_cover")
        elif module == "ph" and route_id.endswith("$pid.ph"):
            payload = data.get("ph")
        elif module == "cl" and route_id.endswith("$pid.cl"):
            payload = data.get("cl")

        if not isinstance(payload, dict):
            continue
        config = payload.get("config")
        if isinstance(config, dict):
            return True, config
        if module == "filter" and all(key in payload for key in ("always_active", "pump_speed")):
            return True, payload
        return module_present(payload), None
    return False, None


def _is_present(value: Any) -> bool:
    return value is not None and value is not UNDEFINED


def _missing(config: dict[str, Any] | None, required: set[str]) -> tuple[str, ...]:
    if config is None:
        return tuple(sorted(required))
    return tuple(sorted(key for key in required if key not in config or not _is_present(config[key])))


def _valid_time(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) else None


def _valid_days(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    days = tuple(str(day).lower() for day in value if isinstance(day, str))
    if len(days) != len(value) or any(day not in DAYS for day in days):
        return None
    return days


def _sanitize_rx(value: Any) -> float | None:
    global _LAST_VALID_RX
    rx = _as_float(value)
    if rx is None:
        return None
    if rx < RX_MIN_VALID or rx > RX_MAX_VALID:
        _LOGGER.debug("Ignoring invalid Rx value %s, using previous valid value %s", rx, _LAST_VALID_RX)
        return _LAST_VALID_RX
    if _LAST_VALID_RX is not None and abs(rx - _LAST_VALID_RX) > RX_MAX_DELTA:
        _LOGGER.debug("Ignoring Rx spike %s -> %s, using previous valid value", _LAST_VALID_RX, rx)
        return _LAST_VALID_RX
    _LAST_VALID_RX = rx
    return rx


def _metric_actual(module: Any) -> float | None:
    if not isinstance(module, dict):
        return None
    metrics = module.get("metrics")
    if isinstance(metrics, dict):
        return _as_float(metrics.get("actual"))
    if isinstance(metrics, list):
        candidates = [
            item for item in metrics
            if isinstance(item, dict) and _as_float(item.get("actual")) is not None
        ]
        if candidates:
            latest = max(candidates, key=lambda item: _as_float(item.get("timestamp")) or float("-inf"))
            return _as_float(latest.get("actual"))
    return None


def _extract_current_from_pool_data(text: str, pool_id: str) -> tuple[str | None, float | None, float | None]:
    decoded = _decode_route_response(text)
    pool = _find_pool_record(decoded, pool_id)
    if pool is None:
        _LOGGER.warning("POOL DATA: pool_id not found: %s", pool_id)
        return None, None, None
    name = pool.get("name") if isinstance(pool.get("name"), str) else None
    ph = _metric_actual(pool.get("ph"))
    rx = _sanitize_rx(_metric_actual(pool.get("cl")))
    return name, round(ph, 2) if ph is not None else None, round(rx, 0) if rx is not None else None


def _extract_devalue_ph_settings(text: str, pool_id: str | None = None) -> PoolPhSettings:
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "ph", pool_id=pool_id)
    required = {"type", "gain", "target", "offset", "dosing_time", "pausing_time", "probe_offset", "overdose_alert", "min_water_temp", "hysteresis"}
    missing = list(_missing(config, required))
    if config is None:
        return PoolPhSettings(detected=detected, missing_fields=tuple(missing))
    numeric_keys = required - {"type"}
    numeric = {key: _as_float(config.get(key)) for key in numeric_keys}
    dosing_type = config.get("type")
    missing.extend(key for key, value in numeric.items() if value is None and key not in missing)
    if (not isinstance(dosing_type, str) or not dosing_type) and "type" not in missing:
        missing.append("type")
    missing = sorted(set(missing))
    return PoolPhSettings(
        target=numeric["target"], dosing_time=numeric["dosing_time"], pausing_time=numeric["pausing_time"],
        dosing_type=dosing_type if isinstance(dosing_type, str) and dosing_type else None,
        gain=str(config["gain"]) if _is_present(config.get("gain")) else None,
        offset=str(config["offset"]) if _is_present(config.get("offset")) else None,
        probe_offset=str(config["probe_offset"]) if _is_present(config.get("probe_offset")) else None,
        overdose_alert=str(config["overdose_alert"]) if _is_present(config.get("overdose_alert")) else None,
        min_water_temp=str(config["min_water_temp"]) if _is_present(config.get("min_water_temp")) else None,
        hysteresis=str(config["hysteresis"]) if _is_present(config.get("hysteresis")) else None,
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _extract_devalue_rx_settings(text: str, pool_id: str | None = None) -> PoolRxSettings:
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "cl", pool_id=pool_id)
    required = {"dosing_time", "pausing_time", "overdose_alert", "min_water_temp", "rx"}
    missing = list(_missing(config, required))
    rx_config = config.get("rx") if isinstance(config, dict) else None
    if not isinstance(rx_config, dict):
        rx_config = None
    else:
        missing.extend(f"rx.{key}" for key in ("target", "probe", "offset") if not _is_present(rx_config.get(key)))
    if config is None:
        return PoolRxSettings(detected=detected, missing_fields=tuple(sorted(set(missing))))
    dosing_time = _as_float(config.get("dosing_time"))
    pausing_time = _as_float(config.get("pausing_time"))
    overdose_alert = _as_float(config.get("overdose_alert"))
    min_water_temp = _as_float(config.get("min_water_temp"))
    target = _as_float(rx_config.get("target")) if rx_config else None
    probe = _as_float(rx_config.get("probe")) if rx_config else None
    offset = _as_float(rx_config.get("offset")) if rx_config else None
    for key, value in (("dosing_time", dosing_time), ("pausing_time", pausing_time), ("overdose_alert", overdose_alert), ("min_water_temp", min_water_temp), ("rx.target", target), ("rx.probe", probe), ("rx.offset", offset)):
        if value is None:
            missing.append(key)
    missing = sorted(set(missing))
    return PoolRxSettings(
        target=target, dosing_time=dosing_time, pausing_time=pausing_time,
        overdose_alert=str(config["overdose_alert"]) if _is_present(config.get("overdose_alert")) else None,
        min_water_temp=str(config["min_water_temp"]) if _is_present(config.get("min_water_temp")) else None,
        probe=str(rx_config["probe"]) if rx_config and _is_present(rx_config.get("probe")) else None,
        offset=str(rx_config["offset"]) if rx_config and _is_present(rx_config.get("offset")) else None,
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _extract_devalue_lighting_settings(text: str, pool_id: str | None = None) -> PoolLightingSettings:
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "lighting", pool_id=pool_id)
    required = {"dimming", "switch_pulse", "cover_disabled", "always_active", "schedule"}
    missing = list(_missing(config, required))
    schedule = config.get("schedule") if isinstance(config, dict) else None
    if not isinstance(schedule, dict):
        schedule = None
    else:
        missing.extend(f"schedule.{key}" for key in ("start_time", "stop_time", "enabled", "days") if not _is_present(schedule.get(key)))
    if config is None:
        return PoolLightingSettings(detected=detected, missing_fields=tuple(sorted(set(missing))))
    dimming = _as_float(config.get("dimming"))
    switch_pulse = _as_float(config.get("switch_pulse"))
    cover_disabled = _as_bool(config.get("cover_disabled"))
    always_active = _as_bool(config.get("always_active"))
    schedule_enabled = _as_bool(schedule.get("enabled")) if schedule else None
    start_time = _valid_time(schedule.get("start_time")) if schedule else None
    stop_time = _valid_time(schedule.get("stop_time")) if schedule else None
    days = _valid_days(schedule.get("days")) if schedule else None
    for key, value in (("dimming", dimming), ("switch_pulse", switch_pulse), ("cover_disabled", cover_disabled), ("always_active", always_active), ("schedule.enabled", schedule_enabled), ("schedule.start_time", start_time), ("schedule.stop_time", stop_time), ("schedule.days", days)):
        if value is None:
            missing.append(key)
    missing = sorted(set(missing))
    return PoolLightingSettings(
        always_active=always_active, cover_disabled=cover_disabled, schedule_enabled=schedule_enabled,
        schedule_start_time=start_time, schedule_stop_time=stop_time, schedule_days=days or (),
        dimming=str(config["dimming"]) if _is_present(config.get("dimming")) else None,
        switch_pulse=str(config["switch_pulse"]) if _is_present(config.get("switch_pulse")) else None,
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _decode_filter_schedule(config: Any, prefix: str) -> tuple[PoolFilterSchedule | None, list[str]]:
    required = {"pump_speed", "start_time", "stop_time", "enabled", "days"}
    missing = [f"{prefix}.{key}" for key in _missing(config if isinstance(config, dict) else None, required)]
    if not isinstance(config, dict):
        return None, missing
    enabled = _as_bool(config.get("enabled"))
    pump_speed = config.get("pump_speed") if config.get("pump_speed") in PUMP_SPEED_OPTIONS else None
    start_time = _valid_time(config.get("start_time"))
    stop_time = _valid_time(config.get("stop_time"))
    days = _valid_days(config.get("days"))
    for key, value in (("enabled", enabled), ("pump_speed", pump_speed), ("start_time", start_time), ("stop_time", stop_time), ("days", days)):
        if value is None:
            missing.append(f"{prefix}.{key}")
    if missing:
        return None, sorted(set(missing))
    return PoolFilterSchedule(enabled=enabled, pump_speed=pump_speed, start_time=start_time, stop_time=stop_time, days=days or ()), []


def _extract_devalue_filter_settings(text: str, pool_id: str | None = None) -> PoolFilterSettings:
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "filter", pool_id=pool_id)
    required = {"always_active", "pump_speed", "schedule_1", "schedule_2", "schedule_3"}
    missing = list(_missing(config, required))
    if config is None:
        return PoolFilterSettings(detected=detected, missing_fields=tuple(missing))
    always_active = _as_bool(config.get("always_active"))
    pump_speed = config.get("pump_speed") if config.get("pump_speed") in PUMP_SPEED_OPTIONS else None
    schedules: list[PoolFilterSchedule | None] = []
    for key in ("schedule_1", "schedule_2", "schedule_3"):
        schedule, schedule_missing = _decode_filter_schedule(config.get(key), key)
        schedules.append(schedule)
        missing.extend(schedule_missing)
    if always_active is None:
        missing.append("always_active")
    if pump_speed is None:
        missing.append("pump_speed")
    missing = sorted(set(missing))
    return PoolFilterSettings(
        always_active=always_active, pump_speed=pump_speed,
        schedule_1=schedules[0], schedule_2=schedules[1], schedule_3=schedules[2],
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _extract_devalue_cover_settings(text: str, pool_id: str | None = None) -> PoolCoverSettings:
    """Extract cover settings; API pump fields are crossed with portal labels."""
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "cover", pool_id=pool_id)
    required = {"protection", "pump_open", "pump_close", "pump_low_speed"}
    missing = list(_missing(config, required))
    if config is None:
        return PoolCoverSettings(detected=detected, missing_fields=tuple(missing))
    protection = _as_bool(config.get("protection"))
    api_pump_open = _as_bool(config.get("pump_open"))
    api_pump_close = _as_bool(config.get("pump_close"))
    pump_low_speed = _as_bool(config.get("pump_low_speed"))
    for key, value in (("protection", protection), ("pump_open", api_pump_open), ("pump_close", api_pump_close), ("pump_low_speed", pump_low_speed)):
        if value is None:
            missing.append(key)
    location = config.get("location") if isinstance(config.get("location"), dict) else {}
    missing = sorted(set(missing))
    return PoolCoverSettings(
        protection=protection,
        # API pump_close = portal/HA Opening Pump.
        pump_open=api_pump_close,
        # API pump_open = portal/HA Closing Pump.
        pump_close=api_pump_open,
        pump_low_speed=pump_low_speed,
        longitude=str(location["longitude"]) if _is_present(location.get("longitude")) else None,
        latitude=str(location["latitude"]) if _is_present(location.get("latitude")) else None,
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _extract_devalue_backwash_settings(text: str, pool_id: str | None = None) -> PoolBackwashSettings:
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "backwash", pool_id=pool_id)
    required = {"interval", "rinse_duration", "backwash_duration", "pump_speed", "start_date", "start_time"}
    missing = list(_missing(config, required))
    if config is None:
        return PoolBackwashSettings(detected=detected, missing_fields=tuple(missing))
    interval = _as_float(config.get("interval"))
    rinse_duration = _as_float(config.get("rinse_duration"))
    backwash_duration = _as_float(config.get("backwash_duration"))
    pump_speed = config.get("pump_speed") if config.get("pump_speed") in BACKWASH_PUMP_SPEED_OPTIONS else None
    start_date = _normalize_smartpool_date(config.get("start_date") if isinstance(config.get("start_date"), str) else None)
    start_time = _valid_time(config.get("start_time"))
    for key, value in (("interval", interval), ("rinse_duration", rinse_duration), ("backwash_duration", backwash_duration), ("pump_speed", pump_speed), ("start_date", start_date), ("start_time", start_time)):
        if value is None:
            missing.append(key)
    missing = sorted(set(missing))
    return PoolBackwashSettings(
        interval=interval, rinse_duration=rinse_duration, backwash_duration=backwash_duration,
        pump_speed=pump_speed, start_date=start_date, start_time=start_time,
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _extract_devalue_eco_valve_settings(text: str, pool_id: str | None = None) -> PoolEcoValveSettings:
    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "eco_valve", pool_id=pool_id)
    required = {"regulation", "start_time", "stop_time"}
    missing = list(_missing(config, required))
    if config is None:
        return PoolEcoValveSettings(detected=detected, missing_fields=tuple(missing) if detected else ())
    regulation = config.get("regulation") if config.get("regulation") in ECO_VALVE_REGULATION_OPTIONS else None
    start_time = _valid_time(config.get("start_time"))
    stop_time = _valid_time(config.get("stop_time"))
    for key, value in (("regulation", regulation), ("start_time", start_time), ("stop_time", stop_time)):
        if value is None:
            missing.append(key)
    missing = sorted(set(missing))
    return PoolEcoValveSettings(
        regulation=regulation, start_time=start_time, stop_time=stop_time,
        detected=detected, valid=detected and not missing, missing_fields=tuple(missing),
    )


def _extract_devalue_zero_e_settings(
    text: Any,
    pool_id: str | None = None,
) -> PoolZeroESettings:
    """Extract a write-complete Zero-E configuration from decoded route data.

    The preferred source is the ``zero_e.config`` object in the pool route. A
    semantic fallback accepts the same complete four-field object if the portal
    moves it to a dedicated route in a future Remix build. Merely seeing Zero-E
    telemetry or translated labels never makes an incomplete configuration
    valid.
    """

    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "zero_e", pool_id=pool_id)
    required = {
        "enabled",
        "threshold_enable",
        "threshold_disable",
        "threshold_temperature",
    }

    if config is None:
        config = next(find_dicts(decoded, required), None)
        if config is not None:
            detected = True

    missing = list(_missing(config, required))
    if config is None:
        return PoolZeroESettings(
            detected=detected,
            missing_fields=tuple(sorted(set(missing))),
        )

    enabled = _as_bool(config.get("enabled"))
    threshold_enable = _as_finite_float(config.get("threshold_enable"))
    threshold_disable = _as_finite_float(config.get("threshold_disable"))
    threshold_temperature = _as_finite_float(config.get("threshold_temperature"))

    for key, value in (
        ("enabled", enabled),
        ("threshold_enable", threshold_enable),
        ("threshold_disable", threshold_disable),
        ("threshold_temperature", threshold_temperature),
    ):
        if value is None:
            missing.append(key)

    if (
        threshold_enable is not None
        and threshold_disable is not None
        and threshold_enable >= threshold_disable
    ):
        missing.append("threshold_order")

    missing = sorted(set(missing))
    return PoolZeroESettings(
        enabled=enabled,
        threshold_enable=threshold_enable,
        threshold_disable=threshold_disable,
        threshold_temperature=threshold_temperature,
        detected=detected,
        valid=detected and not missing,
        missing_fields=tuple(missing),
    )


def _extract_devalue_temperature_settings(
    text: Any,
    pool_id: str | None = None,
) -> PoolTemperatureSettings:
    """Extract and validate every field required by the temperature PUT.

    The dedicated temperature route in the supplied capture contains telemetry
    but no configuration.  The write-complete object currently lives at
    ``temperature.config`` in the generic pool route.  A semantic fallback
    keeps the parser independent from Remix slot numbers and route placement,
    while validity still requires the entire confirmed PUT contract.
    """

    decoded = _decode_route_response(text)
    detected, config = _module_and_config(decoded, "temperature", pool_id=pool_id)
    required = {
        "target",
        "interval",
        "priority",
        "pump_speed",
        "cooling_period",
        "offset_water",
        "offset_ambient",
        "frost_protection",
        "schedule",
    }

    if config is None:
        config = next(find_dicts(decoded, required), None)
        if config is not None:
            detected = True

    missing = list(_missing(config, required))
    schedule = config.get("schedule") if isinstance(config, dict) else None
    schedule_required = {"start_time", "stop_time", "enabled", "days"}
    if not isinstance(schedule, dict):
        schedule = None
        missing.extend(f"schedule.{key}" for key in sorted(schedule_required))
    else:
        missing.extend(
            f"schedule.{key}"
            for key in _missing(schedule, schedule_required)
        )

    if config is None:
        return PoolTemperatureSettings(
            detected=detected,
            missing_fields=tuple(sorted(set(missing))),
        )

    target = _as_finite_float(config.get("target"))
    interval = _as_finite_float(config.get("interval"))
    priority = _as_bool(config.get("priority"))
    pump_speed = (
        config.get("pump_speed")
        if config.get("pump_speed") in PUMP_SPEED_OPTIONS
        else None
    )
    cooling_period = _as_finite_float(config.get("cooling_period"))
    offset_water = _as_finite_float(config.get("offset_water"))
    offset_ambient = _as_finite_float(config.get("offset_ambient"))
    frost_protection = _as_bool(config.get("frost_protection"))
    start_time = _valid_time(schedule.get("start_time")) if schedule else None
    stop_time = _valid_time(schedule.get("stop_time")) if schedule else None
    schedule_enabled = _as_bool(schedule.get("enabled")) if schedule else None
    days = _valid_days(schedule.get("days")) if schedule else None

    for key, value in (
        ("target", target),
        ("interval", interval),
        ("priority", priority),
        ("pump_speed", pump_speed),
        ("cooling_period", cooling_period),
        ("offset_water", offset_water),
        ("offset_ambient", offset_ambient),
        ("frost_protection", frost_protection),
        ("schedule.start_time", start_time),
        ("schedule.stop_time", stop_time),
        ("schedule.enabled", schedule_enabled),
        ("schedule.days", days),
    ):
        if value is None:
            missing.append(key)

    if interval is not None and interval < 0:
        missing.append("interval")
    if cooling_period is not None and cooling_period < 0:
        missing.append("cooling_period")
    if days is not None and len(set(days)) != len(days):
        missing.append("schedule.days")

    missing = sorted(set(missing))
    return PoolTemperatureSettings(
        target=target,
        interval=interval,
        priority=priority,
        pump_speed=pump_speed,
        cooling_period=cooling_period,
        offset_water=offset_water,
        offset_ambient=offset_ambient,
        frost_protection=frost_protection,
        schedule=PoolTemperatureSchedule(
            start_time=start_time,
            stop_time=stop_time,
            enabled=schedule_enabled,
            days=days or (),
        ),
        detected=detected,
        valid=detected and not missing,
        missing_fields=tuple(missing),
    )


def _format_form_number(value: float) -> str:
    """Format numeric form values without adding a needless decimal suffix."""

    return str(int(value)) if value.is_integer() else str(value)


def _format_smartpool_date(value: str | None) -> str:
    if not value:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        y, m, d = value.split("-")
        return f"{d}-{m}-{y}"
    return value


def _normalize_smartpool_date(value: str | None) -> str | None:
    if not value:
        return None
    if re.match(r"^\d{2}-\d{2}-\d{4}$", value):
        d, m, y = value.split("-")
        return f"{y}-{m}-{d}"
    return value


class SmartPoolConnectClient:
    """Client for SmartPoolConnect owner portal."""

    def __init__(self, username: str | None = None, password: str | None = None, *, pool_id: str, base_url: str = DEFAULT_BASE_URL, oauth_base_url: str = DEFAULT_OAUTH_BASE_URL) -> None:
        self.username = username
        self.password = password
        self.pool_id = pool_id
        self.base_url = base_url.rstrip("/")
        self.oauth_base_url = oauth_base_url.rstrip("/")
        self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        self._pool_route_text: str | None = None
        self._pool_route_decoded: Any | None = None
        self._pool_route_cached_at: float = 0.0
        self._settings_bundle: tuple[Any, ...] | None = None
        self._settings_bundle_cached_at: float = 0.0
        self._last_capabilities: frozenset[str] = frozenset()

    async def close(self) -> None:
        await self._session.close()

    async def async_login(self) -> None:
        if not self.username or not self.password:
            raise AuthenticationError("Username and password are required")
        await self._oauth_owner_login()
        await self._dump_cookies("after oauth owner login")
        await self._validate_session()

    async def _request_text_with_reauth(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> str:
        try:
            return await self._request_text(
                method,
                path,
                **kwargs,
            )

        except AuthenticationError:
            _LOGGER.warning(
                "SmartPoolConnect session expired, attempting re-login"
            )

            await self.async_login()

            return await self._request_text(
                method,
                path,
                **kwargs,
            )

    async def _oauth_owner_login(self) -> None:
        login_page_url = await self._get_login_page_url()
        async with self._session.get(login_page_url) as resp:
            await resp.text()
            if resp.status in (502, 503, 504):
                raise TransientServerError(
                    f"OAuth login page failed: HTTP {resp.status}"
                )
            if resp.status >= 400:
                raise OAuthFlowError(
                    f"OAuth login page failed: HTTP {resp.status}"
                )

        login_data_url = self._to_login_data_url(login_page_url)
        device = base64.b64encode(
            str(secrets.randbelow(10_000_000_000)).encode()
        ).decode()
        async with self._session.post(
            login_data_url,
            data={
                "email": self.username,
                "password": self.password,
                "device": device,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Origin": self.oauth_base_url,
                "Referer": login_page_url,
            },
            allow_redirects=False,
        ) as resp:
            login_text = await resp.text()
            login_location = resp.headers.get("Location")
            login_remix_redirect = resp.headers.get("X-Remix-Redirect")
            if resp.status in (401, 403):
                raise AuthenticationError(
                    f"OAuth login.data rejected credentials: HTTP {resp.status}"
                )
            if resp.status in (502, 503, 504):
                raise TransientServerError(
                    f"OAuth login.data failed: HTTP {resp.status}"
                )
            if resp.status not in (200, 202, 204, 301, 302, 303):
                raise OAuthFlowError(
                    f"OAuth login.data returned an unexpected status: HTTP {resp.status}"
                )

        next_url = (
            login_location
            or login_remix_redirect
            or self._extract_auth_redirect(login_text)
            or self._to_auth_data_url(login_page_url)
        )
        if next_url.startswith("/"):
            next_url = urljoin(self.oauth_base_url, next_url)
        await self._follow_auth_redirect(next_url)

    def _to_login_data_url(self, login_page_url: str) -> str:
        if "/oauth/login?" not in login_page_url:
            raise OAuthFlowError(f"Unexpected OAuth login URL: {login_page_url}")
        return login_page_url.replace("/oauth/login?", "/oauth/login.data?")

    def _to_auth_data_url(self, login_page_url: str) -> str:
        if "/oauth/login?" not in login_page_url:
            raise OAuthFlowError(f"Unexpected OAuth login URL: {login_page_url}")
        return login_page_url.replace("/oauth/login?", "/oauth/auth.data?")

    async def _get_login_page_url(self) -> str:
        current_url = f"{self.base_url}/"
        for _ in range(8):
            async with self._session.get(current_url, allow_redirects=False) as resp:
                await resp.text()
                location = resp.headers.get("Location")
                if resp.status == 200 and "/oauth/login" in current_url:
                    return current_url
                if not location:
                    if "/oauth/login" in current_url:
                        return current_url
                    raise OAuthFlowError("Could not discover OAuth login URL: no redirect location")
                if location.startswith("/"):
                    location = urljoin(current_url, location)
                current_url = location
                if "/oauth/login" in current_url:
                    return current_url
        raise OAuthFlowError("Could not discover OAuth login URL after redirects")

    async def _follow_auth_redirect(self, redirect_to: str) -> None:
        current_url = redirect_to
        for step in range(10):
            async with self._session.get(current_url, allow_redirects=False) as resp:
                body = await resp.text()
                next_url = resp.headers.get("Location") or resp.headers.get("X-Remix-Redirect") or self._extract_auth_redirect(body)
                await self._dump_cookies(f"after redirect step {step}")
                if "www.smartpoolconnect.eu/auth" in current_url and resp.status in (200, 202, 204, 301, 302, 303):
                    return
                if not next_url:
                    if resp.status in (200, 202, 204):
                        if "oauth.smartpoolconnect.eu" in current_url:
                            raise OAuthFlowError("OAuth flow ended on oauth domain without reaching www auth callback")
                        return
                    if resp.status in (401, 403):
                        raise AuthenticationError(
                            f"OAuth redirect was not authorised: HTTP {resp.status}"
                        )
                    if resp.status in (502, 503, 504):
                        raise TransientServerError(
                            f"OAuth redirect failed: HTTP {resp.status}"
                        )
                    raise OAuthFlowError(
                        f"OAuth redirect returned an unexpected status: HTTP {resp.status}"
                    )
                if next_url.startswith("/"):
                    next_url = urljoin(current_url, next_url)
                current_url = next_url
        raise OAuthFlowError("Too many OAuth redirect steps")

    @staticmethod
    def _extract_auth_redirect(text: str) -> str | None:
        if not text:
            return None
        patterns = [
            r"https://www\.smartpoolconnect\.eu/auth\?[^\"'<>\s]+",
            r"https:\\/\\/www\.smartpoolconnect\.eu\\/auth\?[^\"'<>\s]+",
            r"/auth\?code=[^\"'<>\s]+",
            r'"redirect"\s*:\s*"([^"]+)"',
            r'"location"\s*:\s*"([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                result = match.group(1) if match.lastindex else match.group(0)
                return result.replace("\\/", "/")
        return None

    async def _dump_cookies(self, label: str) -> None:
        try:
            _LOGGER.debug("cookies %s: www=%s oauth=%s", label, list(self._session.cookie_jar.filter_cookies(self.base_url).keys()), list(self._session.cookie_jar.filter_cookies(self.oauth_base_url).keys()))
        except Exception:
            _LOGGER.exception("Could not dump cookie names")

    async def _validate_session(self) -> None:
        """Validate authentication against either supported live API family."""

        errors: list[SmartPoolConnectError] = []
        for path in (
            f"/api/live-status/{self.pool_id}",
            f"/api/v3-live/{self.pool_id}",
        ):
            try:
                await self._request_text("GET", path)
                return
            except SmartPoolConnectError as err:
                errors.append(err)

        auth_error = next(
            (err for err in errors if isinstance(err, AuthenticationError)),
            None,
        )
        if auth_error is not None:
            raise auth_error
        if errors:
            raise errors[0]
        raise SmartPoolConnectError("No supported SmartPoolConnect live API was found")

    async def _request_text(self, method: str, path: str, **kwargs: Any) -> str:
        url = f"{self.base_url}{path}"
        async with self._session.request(method, url, **kwargs) as resp:
            text = await resp.text()
            _LOGGER.debug("%s %s -> HTTP %s content-type=%s body_prefix=%s", method, path, resp.status, resp.headers.get("content-type"), text[:120])
            if resp.status in (401, 403):
                raise AuthenticationError(
                    f"SmartPoolConnect session is not authorized: HTTP {resp.status}"
                )

            if resp.status in (502, 503, 504):
                raise TransientServerError(
                    f"{method} {path} failed: HTTP {resp.status}"
                )

            if resp.status >= 400:
                raise SmartPoolConnectError(
                    f"{method} {path} failed: HTTP {resp.status}: {text[:300]}"
                )

            return text

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        text = await self._request_text_with_reauth(method, path, **kwargs)
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    async def _request_optional_json(
        self,
        path: str,
    ) -> tuple[dict[str, Any] | None, SmartPoolConnectError | None]:
        """Probe one optional JSON endpoint without forcing reauthentication.

        Some installations return 403 or 404 for the live API family they do
        not implement. Authentication is therefore considered failed only if
        neither supported live endpoint succeeds.
        """

        try:
            text = await self._request_text("GET", path)
        except SmartPoolConnectError as err:
            return None, err
        if not text:
            return {}, None
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as err:
            return None, SmartPoolConnectError(
                f"GET {path} returned invalid JSON: {err}"
            )
        if not isinstance(decoded, dict):
            return None, SmartPoolConnectError(
                f"GET {path} returned a non-object JSON response"
            )
        return decoded, None

    async def _get_live_sources(
        self,
        *,
        allow_reauth: bool = True,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Read both equal-status live API families, accepting either one."""

        live, live_error = await self._request_optional_json(
            f"/api/live-status/{self.pool_id}"
        )
        v3, v3_error = await self._request_optional_json(
            f"/api/v3-live/{self.pool_id}"
        )
        if live is not None or v3 is not None:
            return live, v3

        errors = [err for err in (live_error, v3_error) if err is not None]
        if allow_reauth and any(isinstance(err, AuthenticationError) for err in errors):
            _LOGGER.warning(
                "Both SmartPoolConnect live APIs failed; attempting re-login"
            )
            await self.async_login()
            return await self._get_live_sources(allow_reauth=False)

        auth_error = next(
            (err for err in errors if isinstance(err, AuthenticationError)),
            None,
        )
        if auth_error is not None:
            raise auth_error
        if errors:
            raise SmartPoolConnectError(
                "Neither /api/live-status nor /api/v3-live is available: "
                + "; ".join(str(err) for err in errors)
            )
        raise SmartPoolConnectError("No supported SmartPoolConnect live API was found")

    def _invalidate_settings_cache(self) -> None:
        self._pool_route_text = None
        self._pool_route_decoded = None
        self._pool_route_cached_at = 0.0
        self._settings_bundle = None
        self._settings_bundle_cached_at = 0.0

    async def _get_pool_route_text(self, *, force_refresh: bool = False) -> str:
        now = monotonic()
        if not force_refresh and self._pool_route_text is not None and now - self._pool_route_cached_at < SETTINGS_CACHE_INTERVAL:
            return self._pool_route_text
        text = await self._request_text_with_reauth("GET", f"/pool/{self.pool_id}.data")
        self._pool_route_text = text
        self._pool_route_decoded = None
        self._pool_route_cached_at = now
        return text

    async def _get_pool_route_decoded(self, *, force_refresh: bool = False) -> Any:
        text = await self._get_pool_route_text(force_refresh=force_refresh)
        if self._pool_route_decoded is None:
            decoded = _decode_route_response(text)
            if decoded is None:
                raise SmartPoolConnectError("SmartPoolConnect returned malformed pool route data")
            self._pool_route_decoded = decoded
        return self._pool_route_decoded

    async def _get_current_from_pool_data(self) -> tuple[str | None, float | None, float | None]:
        try:
            text = await self._request_text("GET", "/pool.data")
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read /pool.data", exc_info=True)
            return None, None, None
        return _extract_current_from_pool_data(text, self.pool_id)

    async def async_get_ph_settings(self, *, force_refresh: bool = False) -> PoolPhSettings:
        try:
            return _extract_devalue_ph_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read pH settings from pool route data", exc_info=True)
            return PoolPhSettings()

    async def async_set_ph_settings(
        self,
        *,
        target: float | None = None,
        dosing_time: float | None = None,
        pausing_time: float | None = None,
    ) -> None:
        current = await self.async_get_ph_settings(force_refresh=True)
        if not current.valid:
            raise SmartPoolConnectError(
                "pH settings update aborted because the current controller settings could not be read completely"
            )

        await self._request_json(
            "PATCH",
            f"/pool/{self.pool_id}/ph.data",
            data={
                "type": current.dosing_type,
                "gain": current.gain,
                "target": str(target if target is not None else current.target),
                "offset": current.offset,
                "dosing_time": str(int(dosing_time if dosing_time is not None else current.dosing_time)),
                "pausing_time": str(int(pausing_time if pausing_time is not None else current.pausing_time)),
                "probe_offset": current.probe_offset,
                "overdose_alert": current.overdose_alert,
                "min_water_temp": current.min_water_temp,
                "hysteresis": current.hysteresis,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        self._invalidate_settings_cache()

    async def async_get_rx_settings(self, *, force_refresh: bool = False) -> PoolRxSettings:
        try:
            return _extract_devalue_rx_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read Rx settings from pool route data", exc_info=True)
            return PoolRxSettings()

    async def async_set_rx_settings(
        self,
        *,
        target: float | None = None,
        dosing_time: float | None = None,
        pausing_time: float | None = None,
    ) -> None:
        current = await self.async_get_rx_settings(force_refresh=True)
        if not current.valid:
            raise SmartPoolConnectError(
                "Rx settings update aborted because the current controller settings could not be read completely"
            )

        await self._request_json(
            "PUT",
            f"/pool/{self.pool_id}/cl.data",
            data={
                "dosing_time": str(int(dosing_time if dosing_time is not None else current.dosing_time)),
                "pausing_time": str(int(pausing_time if pausing_time is not None else current.pausing_time)),
                "overdose_alert": current.overdose_alert,
                "min_water_temp": current.min_water_temp,
                "rx.target": str(int(target if target is not None else current.target)),
                "rx.probe": current.probe,
                "rx.offset": current.offset,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        self._invalidate_settings_cache()

    async def async_get_lighting_settings(self, *, force_refresh: bool = False) -> PoolLightingSettings:
        try:
            return _extract_devalue_lighting_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read lighting settings from pool route data", exc_info=True)
            return PoolLightingSettings()

    async def async_set_lighting_settings(
        self,
        *,
        always_active: bool | None = None,
        cover_disabled: bool | None = None,
        schedule_enabled: bool | None = None,
        schedule_start_time: str | None = None,
        schedule_stop_time: str | None = None,
        schedule_days: tuple[str, ...] | None = None,
    ) -> None:
        current = await self.async_get_lighting_settings(force_refresh=True)
        if not current.valid:
            raise SmartPoolConnectError(
                "Lighting settings update aborted because the current controller settings could not be read completely"
            )

        await self._request_json(
            "PUT",
            f"/pool/{self.pool_id}/lighting.data",
            data={
                "dimming": current.dimming,
                "switch_pulse": current.switch_pulse,
                "cover_disabled": "true" if (cover_disabled if cover_disabled is not None else current.cover_disabled) else "false",
                "always_active": "true" if (always_active if always_active is not None else current.always_active) else "false",
                "schedule.start_time": schedule_start_time if schedule_start_time is not None else current.schedule_start_time,
                "schedule.stop_time": schedule_stop_time if schedule_stop_time is not None else current.schedule_stop_time,
                "schedule.enabled": "true" if (schedule_enabled if schedule_enabled is not None else current.schedule_enabled) else "false",
                "schedule.days": ",".join(schedule_days if schedule_days is not None else current.schedule_days),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        self._invalidate_settings_cache()

    async def async_get_filter_settings(self, *, force_refresh: bool = False) -> PoolFilterSettings:
        try:
            return _extract_devalue_filter_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read filter settings from pool route data", exc_info=True)
            return PoolFilterSettings()

    async def async_set_filter_settings(self, settings: PoolFilterSettings) -> None:
        schedules = (settings.schedule_1, settings.schedule_2, settings.schedule_3)
        if (
            not settings.valid
            or settings.pump_speed not in PUMP_SPEED_OPTIONS
            or not all(schedules)
            or any(
                schedule.pump_speed not in PUMP_SPEED_OPTIONS
                or schedule.enabled is None
                or schedule.start_time is None
                or schedule.stop_time is None
                for schedule in schedules
                if schedule is not None
            )
        ):
            raise SmartPoolConnectError("Filter settings update aborted because the current controller settings could not be read completely")
        s1, s2, s3 = settings.schedule_1, settings.schedule_2, settings.schedule_3
        assert s1 is not None and s2 is not None and s3 is not None
        await self._request_json("PUT", f"/pool/{self.pool_id}/filter.data", data={
            "always_active": "true" if settings.always_active else "false",
            "pump_speed": settings.pump_speed,
            "schedule_1.pump_speed": s1.pump_speed, "schedule_1.start_time": s1.start_time, "schedule_1.stop_time": s1.stop_time, "schedule_1.enabled": "true" if s1.enabled else "false", "schedule_1.days": ",".join(s1.days),
            "schedule_2.pump_speed": s2.pump_speed, "schedule_2.start_time": s2.start_time, "schedule_2.stop_time": s2.stop_time, "schedule_2.enabled": "true" if s2.enabled else "false", "schedule_2.days": ",".join(s2.days),
            "schedule_3.pump_speed": s3.pump_speed, "schedule_3.start_time": s3.start_time, "schedule_3.stop_time": s3.stop_time, "schedule_3.enabled": "true" if s3.enabled else "false", "schedule_3.days": ",".join(s3.days),
        }, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_get_backwash_settings(self) -> PoolBackwashSettings:
        try:
            return _extract_devalue_backwash_settings(
                await self._get_pool_route_decoded(),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read backwash settings from pool route data", exc_info=True)
            return PoolBackwashSettings()

    async def async_set_backwash_settings(self, settings: PoolBackwashSettings) -> None:
        if not settings.valid or settings.pump_speed not in BACKWASH_PUMP_SPEED_OPTIONS or any(value is None for value in (settings.interval, settings.rinse_duration, settings.backwash_duration, settings.pump_speed, settings.start_date, settings.start_time)):
            raise SmartPoolConnectError("Backwash settings update aborted because the current controller settings could not be read completely")
        await self._request_json("PUT", f"/pool/{self.pool_id}/filter/backwash.data", data={"interval": str(int(settings.interval)), "rinse_duration": str(int(settings.rinse_duration)), "backwash_duration": str(int(settings.backwash_duration)), "pump_speed": settings.pump_speed, "start_date": _format_smartpool_date(settings.start_date), "start_time": settings.start_time}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_start_backwash(self) -> None:
        await self._request_json("POST", f"/pool/{self.pool_id}/cmd.data", data={"exec": "backwash"}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_get_eco_valve_settings(self) -> PoolEcoValveSettings:
        try:
            return _extract_devalue_eco_valve_settings(
                await self._get_pool_route_decoded(),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read Eco Valve settings from pool route data", exc_info=True)
            return PoolEcoValveSettings()

    async def async_set_eco_valve_settings(self, settings: PoolEcoValveSettings) -> None:
        if not settings.valid or settings.regulation not in ECO_VALVE_REGULATION_OPTIONS or settings.start_time is None or settings.stop_time is None:
            raise SmartPoolConnectError("Eco Valve settings update aborted because the current controller settings could not be read completely")
        await self._request_json("PUT", f"/pool/{self.pool_id}/filter/eco-valve.data", data={"regulation": settings.regulation, "start_time": settings.start_time, "stop_time": settings.stop_time}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_get_zero_e_settings(
        self,
        *,
        force_refresh: bool = False,
    ) -> PoolZeroESettings:
        """Read Zero-E settings from the generic decoded pool route."""

        try:
            return _extract_devalue_zero_e_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read Zero-E settings from pool route data", exc_info=True)
            return PoolZeroESettings()

    async def async_set_zero_e_settings(
        self,
        *,
        enabled: bool | None = None,
        threshold_enable: float | None = None,
        threshold_disable: float | None = None,
        threshold_temperature: float | None = None,
    ) -> None:
        """Safely update exactly one Zero-E field using a fresh complete read."""

        current = await self.async_get_zero_e_settings(force_refresh=True)
        if not current.valid:
            raise SmartPoolConnectError(
                "Zero-E settings update aborted because the current controller settings could not be read completely"
            )

        new_enabled = current.enabled if enabled is None else enabled
        new_threshold_enable = _as_finite_float(
            current.threshold_enable if threshold_enable is None else threshold_enable
        )
        new_threshold_disable = _as_finite_float(
            current.threshold_disable if threshold_disable is None else threshold_disable
        )
        new_threshold_temperature = _as_finite_float(
            current.threshold_temperature
            if threshold_temperature is None
            else threshold_temperature
        )

        if (
            not isinstance(new_enabled, bool)
            or new_threshold_enable is None
            or new_threshold_disable is None
            or new_threshold_temperature is None
        ):
            raise SmartPoolConnectError(
                "Zero-E settings update aborted because a proposed value is invalid"
            )
        if new_threshold_enable >= new_threshold_disable:
            raise SmartPoolConnectError(
                "Zero-E enable threshold must be lower than the disable threshold"
            )

        await self._request_json(
            "PUT",
            f"/pool/{self.pool_id}/temperature/zero-e.data",
            data={
                "enabled": "true" if new_enabled else "false",
                "threshold_enable": _format_form_number(new_threshold_enable),
                "threshold_disable": _format_form_number(new_threshold_disable),
                "threshold_temperature": _format_form_number(new_threshold_temperature),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        self._invalidate_settings_cache()

    async def async_get_temperature_settings(
        self,
        *,
        force_refresh: bool = False,
    ) -> PoolTemperatureSettings:
        """Read the full temperature configuration from the decoded pool route."""

        try:
            return _extract_devalue_temperature_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug(
                "Could not read temperature settings from pool route data",
                exc_info=True,
            )
            return PoolTemperatureSettings()

    async def async_set_temperature_settings(
        self,
        *,
        target: float | None = None,
        interval: float | None = None,
        priority: bool | None = None,
        pump_speed: str | None = None,
        cooling_period: float | None = None,
        offset_water: float | None = None,
        offset_ambient: float | None = None,
        frost_protection: bool | None = None,
        schedule_start_time: str | None = None,
        schedule_stop_time: str | None = None,
        schedule_enabled: bool | None = None,
        schedule_days: tuple[str, ...] | None = None,
        schedule_day: tuple[str, bool] | None = None,
    ) -> None:
        """Safely change one temperature field and PUT the complete fresh config."""

        changes = {
            "target": target,
            "interval": interval,
            "priority": priority,
            "pump_speed": pump_speed,
            "cooling_period": cooling_period,
            "offset_water": offset_water,
            "offset_ambient": offset_ambient,
            "frost_protection": frost_protection,
            "schedule_start_time": schedule_start_time,
            "schedule_stop_time": schedule_stop_time,
            "schedule_enabled": schedule_enabled,
            "schedule_days": schedule_days,
            "schedule_day": schedule_day,
        }
        changed_fields = [key for key, value in changes.items() if value is not None]
        if len(changed_fields) != 1:
            raise SmartPoolConnectError(
                "A temperature update must change exactly one entity-owned field"
            )

        current = await self.async_get_temperature_settings(force_refresh=True)
        schedule = current.schedule
        if not current.valid or schedule is None:
            raise SmartPoolConnectError(
                "Temperature settings update aborted because the current controller settings could not be read completely"
            )

        new_target = _as_finite_float(current.target if target is None else target)
        new_interval = _as_finite_float(current.interval if interval is None else interval)
        new_priority = current.priority if priority is None else priority
        new_pump_speed = current.pump_speed if pump_speed is None else pump_speed
        new_cooling_period = _as_finite_float(
            current.cooling_period if cooling_period is None else cooling_period
        )
        new_offset_water = _as_finite_float(
            current.offset_water if offset_water is None else offset_water
        )
        new_offset_ambient = _as_finite_float(
            current.offset_ambient if offset_ambient is None else offset_ambient
        )
        new_frost_protection = (
            current.frost_protection
            if frost_protection is None
            else frost_protection
        )
        new_start_time = (
            schedule.start_time
            if schedule_start_time is None
            else schedule_start_time
        )
        new_stop_time = (
            schedule.stop_time
            if schedule_stop_time is None
            else schedule_stop_time
        )
        new_schedule_enabled = (
            schedule.enabled if schedule_enabled is None else schedule_enabled
        )
        new_days = schedule.days if schedule_days is None else schedule_days
        if schedule_day is not None:
            day, included = schedule_day
            if day not in DAYS or not isinstance(included, bool):
                raise SmartPoolConnectError(
                    "Temperature settings update aborted because a proposed schedule day is invalid"
                )
            day_set = set(schedule.days)
            if included:
                day_set.add(day)
            else:
                day_set.discard(day)
            new_days = tuple(item for item in DAYS if item in day_set)

        if (
            new_target is None
            or new_interval is None
            or not isinstance(new_priority, bool)
            or new_pump_speed not in PUMP_SPEED_OPTIONS
            or new_cooling_period is None
            or new_offset_water is None
            or new_offset_ambient is None
            or not isinstance(new_frost_protection, bool)
            or _valid_time(new_start_time) is None
            or _valid_time(new_stop_time) is None
            or not isinstance(new_schedule_enabled, bool)
            or not isinstance(new_days, tuple)
            or _valid_days(list(new_days)) is None
            or len(set(new_days)) != len(new_days)
            or new_interval < 0
            or new_cooling_period < 0
        ):
            raise SmartPoolConnectError(
                "Temperature settings update aborted because a proposed value is invalid"
            )

        await self._request_json(
            "PUT",
            f"/pool/{self.pool_id}/temperature.data",
            data={
                "target": _format_form_number(new_target),
                "interval": _format_form_number(new_interval),
                "priority": "true" if new_priority else "false",
                "pump_speed": new_pump_speed,
                "cooling_period": _format_form_number(new_cooling_period),
                "offset_water": _format_form_number(new_offset_water),
                "offset_ambient": _format_form_number(new_offset_ambient),
                "frost_protection": "true" if new_frost_protection else "false",
                "schedule.start_time": new_start_time,
                "schedule.stop_time": new_stop_time,
                "schedule.enabled": "true" if new_schedule_enabled else "false",
                "schedule.days": ",".join(new_days),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        self._invalidate_settings_cache()

    async def async_get_cover_settings(self) -> PoolCoverSettings:
        try:
            return _extract_devalue_cover_settings(
                await self._get_pool_route_decoded(),
                self.pool_id,
            )
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read cover settings from pool route data", exc_info=True)
            return PoolCoverSettings()

    async def async_set_cover_settings(self, settings: PoolCoverSettings) -> None:
        if not settings.valid or any(value is None for value in (settings.protection, settings.pump_open, settings.pump_close, settings.pump_low_speed)):
            raise SmartPoolConnectError("Cover settings update aborted because the current controller settings could not be read completely")
        data: dict[str, str] = {
            "protection": "true" if settings.protection else "false",
            "pump_open": "true" if settings.pump_close else "false",
            "pump_close": "true" if settings.pump_open else "false",
            "pump_low_speed": "true" if settings.pump_low_speed else "false",
        }
        if settings.longitude is not None:
            data["location.longitude"] = str(settings.longitude)
        if settings.latitude is not None:
            data["location.latitude"] = str(settings.latitude)
        await self._request_json("PUT", f"/pool/{self.pool_id}/cover.data", data=data, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def _get_settings_bundle(self) -> tuple[Any, ...]:
        now = monotonic()
        if self._settings_bundle is not None and now - self._settings_bundle_cached_at < SETTINGS_CACHE_INTERVAL:
            return self._settings_bundle
        self._settings_bundle = (
            await self.async_get_ph_settings(),
            await self.async_get_rx_settings(),
            await self.async_get_lighting_settings(),
            await self.async_get_filter_settings(),
            await self.async_get_backwash_settings(),
            await self.async_get_eco_valve_settings(),
            await self.async_get_zero_e_settings(),
            await self.async_get_temperature_settings(),
            await self.async_get_cover_settings(),
        )
        self._settings_bundle_cached_at = now
        return self._settings_bundle

    async def async_get_status(self) -> PoolStatus:
        """Return one normalized status from either or both live API families."""

        live, v3 = await self._get_live_sources()
        pool, _pool_error = await self._request_optional_json(
            f"/api/pool-status/{self.pool_id}"
        )
        pool = pool or {}
        pool_name, portal_ph, portal_rx = await self._get_current_from_pool_data()
        (
            ph_settings,
            rx_settings,
            lighting_settings,
            filter_settings,
            backwash_settings,
            eco_valve_settings,
            zero_e_settings,
            temperature_settings,
            cover_settings,
        ) = await self._get_settings_bundle()

        capabilities = {
            name
            for name, settings in (
                ("lighting", lighting_settings),
                ("filter", filter_settings),
                ("backwash", backwash_settings),
                ("eco_valve", eco_valve_settings),
            )
            if settings.detected
        }
        if ph_settings.valid:
            capabilities.add("ph")
        if rx_settings.valid:
            capabilities.add("rx")
        # Settings entities can write to physical equipment. Expose these
        # capabilities only after the complete portal contract was validated.
        capabilities.update(
            name
            for name, settings in (
                ("zero_e", zero_e_settings),
                ("temperature", temperature_settings),
                ("cover", cover_settings),
            )
            if settings.valid
        )
        if live is not None:
            capabilities.add("live_status_api")
        if v3 is not None:
            capabilities.add("v3_live_api")

        fs1 = filter_settings.schedule_1 or PoolFilterSchedule()
        fs2 = filter_settings.schedule_2 or PoolFilterSchedule()
        fs3 = filter_settings.schedule_3 or PoolFilterSchedule()
        temperature_schedule = (
            temperature_settings.schedule or PoolTemperatureSchedule()
        )

        analogue = _analogue_telemetry(v3)
        standard_cover_state = _cover_state(
            _find_key(live, {"cover"}) if live is not None else None
        )
        covco_valid, covco_position, covco_state = _covco_telemetry(v3)
        phnix_valid, phnix = _phnix_telemetry(v3)
        v3_pump_status, v3_pump_speed = _v3_filter_telemetry(v3)
        v3_lighting = _v3_lighting_state(v3)

        if standard_cover_state is not None:
            capabilities.add("cover_status")
        if covco_valid:
            capabilities.add("covco_cover")
        if phnix_valid:
            capabilities.add("phnix_heat_pump")
        if _find_data_block(v3, "lighting_data") is not None:
            capabilities.add("v3_lighting")

        frozen_capabilities = frozenset(capabilities)
        self._last_capabilities = frozen_capabilities

        live_ph = _as_float(_find_key(live, {"ph"})) if live is not None else None
        live_rx = (
            _as_float(_find_key(live, {"rx", "orp"}))
            if live is not None
            else None
        )
        ph = portal_ph if portal_ph is not None else live_ph
        if ph is None:
            ph = analogue["ph"]
        rx = portal_rx if portal_rx is not None else live_rx
        if rx is None:
            rx = analogue["rx"]

        water_temperature = (
            _as_float(
                _find_key(live, {"water_temp", "water_temperature", "temperature"})
            )
            if live is not None
            else None
        )
        if water_temperature is None:
            water_temperature = _as_float(
                _find_key(pool, {"water_temp", "water_temperature", "temperature"})
            )
        if water_temperature is None:
            water_temperature = analogue["water_temperature"]

        live_pump_status = (
            _find_key(live, {"pump_status"}) if live is not None else None
        )
        live_pump_speed = _pump_speed(
            _find_key(live, {"pump_speed"}) if live is not None else None
        )
        pump_status = (
            bool(live_pump_status)
            if live_pump_status is not None
            else v3_pump_status if v3_pump_speed is not None else None
        )
        pump_speed = live_pump_speed or v3_pump_speed

        live_lighting = _find_key(live, {"lighting"}) if live is not None else None
        lighting_on = (
            lighting_settings.always_active
            if lighting_settings.always_active is not None
            else (live_lighting not in (None, -1, 0))
            if live_lighting is not None
            else v3_lighting
        )
        heating_active = (
            _find_key(live, {"_heating_pump_active"})
            if live is not None
            else None
        )
        heating = (
            _find_key(live, {"heating", "heating_on"})
            if live is not None
            else None
        )
        heating_on = (
            bool(heating_active)
            if heating_active is not None
            else bool(heating)
            if heating not in (None, -1)
            else None
        )
        outside_temperature = _as_float(
            _find_key(pool, {"outside_temp", "outside_temperature"})
        )
        if outside_temperature is None:
            outside_temperature = analogue["ambient_temperature"]

        return PoolStatus(
            pool_id=self.pool_id,
            name=pool_name or _find_key(pool, {"name", "pool_name"}),
            online=True,
            ph=ph,
            ph_target=(
                ph_settings.target
                if ph_settings.target is not None
                else _as_float(_find_key(pool, {"ph_target", "target_ph"}))
            ),
            ph_dosing_time=ph_settings.dosing_time,
            ph_pausing_time=ph_settings.pausing_time,
            rx=rx,
            rx_target=(
                rx_settings.target
                if rx_settings.target is not None
                else _as_float(_find_key(pool, {"rx_target", "target_rx", "orp_target"}))
            ),
            rx_dosing_time=rx_settings.dosing_time,
            rx_pausing_time=rx_settings.pausing_time,
            lighting_on=lighting_on,
            lighting_always_active=lighting_settings.always_active,
            lighting_cover_disabled=lighting_settings.cover_disabled,
            lighting_schedule_enabled=lighting_settings.schedule_enabled,
            lighting_schedule_start_time=lighting_settings.schedule_start_time,
            lighting_schedule_stop_time=lighting_settings.schedule_stop_time,
            lighting_schedule_days=lighting_settings.schedule_days,
            filter_always_active=filter_settings.always_active,
            filter_pump_speed=filter_settings.pump_speed or pump_speed,
            filter_schedule_1_enabled=fs1.enabled,
            filter_schedule_1_pump_speed=fs1.pump_speed,
            filter_schedule_1_start_time=fs1.start_time,
            filter_schedule_1_stop_time=fs1.stop_time,
            filter_schedule_1_days=fs1.days,
            filter_schedule_2_enabled=fs2.enabled,
            filter_schedule_2_pump_speed=fs2.pump_speed,
            filter_schedule_2_start_time=fs2.start_time,
            filter_schedule_2_stop_time=fs2.stop_time,
            filter_schedule_2_days=fs2.days,
            filter_schedule_3_enabled=fs3.enabled,
            filter_schedule_3_pump_speed=fs3.pump_speed,
            filter_schedule_3_start_time=fs3.start_time,
            filter_schedule_3_stop_time=fs3.stop_time,
            filter_schedule_3_days=fs3.days,
            backwash_interval=backwash_settings.interval,
            backwash_rinse_duration=backwash_settings.rinse_duration,
            backwash_duration=backwash_settings.backwash_duration,
            backwash_pump_speed=backwash_settings.pump_speed,
            backwash_start_date=backwash_settings.start_date,
            backwash_start_time=backwash_settings.start_time,
            eco_valve_regulation=eco_valve_settings.regulation,
            eco_valve_start_time=eco_valve_settings.start_time,
            eco_valve_stop_time=eco_valve_settings.stop_time,
            zero_e_enabled=zero_e_settings.enabled,
            zero_e_enable_threshold=zero_e_settings.threshold_enable,
            zero_e_disable_threshold=zero_e_settings.threshold_disable,
            zero_e_target_temperature=zero_e_settings.threshold_temperature,
            zero_e_valid=zero_e_settings.valid,
            temperature_target=temperature_settings.target,
            temperature_interval=temperature_settings.interval,
            temperature_priority=temperature_settings.priority,
            temperature_pump_speed=temperature_settings.pump_speed,
            temperature_cooling_period=temperature_settings.cooling_period,
            temperature_offset_water=temperature_settings.offset_water,
            temperature_offset_ambient=temperature_settings.offset_ambient,
            temperature_frost_protection=temperature_settings.frost_protection,
            temperature_schedule_start_time=temperature_schedule.start_time,
            temperature_schedule_stop_time=temperature_schedule.stop_time,
            temperature_schedule_enabled=temperature_schedule.enabled,
            temperature_schedule_days=temperature_schedule.days,
            temperature_valid=temperature_settings.valid,
            water_temperature=water_temperature,
            water_temperature_target=(
                temperature_settings.target
                if temperature_settings.target is not None
                else _as_float(
                    _find_key(
                        pool,
                        {"water_temperature_target", "temperature_target", "setpoint"},
                    )
                )
            ),
            outside_temperature=outside_temperature,
            solar_temperature=_as_float(
                _find_key(pool, {"solar_temp", "solar_temperature"})
            ),
            pump_speed=pump_speed,
            pump_status=pump_status,
            heating_on=heating_on,
            cover_state=standard_cover_state or covco_state,
            cover_protection=cover_settings.protection,
            cover_pump_open=cover_settings.pump_open,
            cover_pump_close=cover_settings.pump_close,
            cover_pump_low_speed=cover_settings.pump_low_speed,
            covco_cover_position=covco_position,
            phnix_setpoint=phnix.get("setpoint"),
            phnix_inlet_temperature=phnix.get("inlet"),
            phnix_outlet_temperature=phnix.get("outlet"),
            phnix_coil_temperature=phnix.get("coil"),
            phnix_ambient_temperature=phnix.get("ambient"),
            phnix_mode=phnix.get("mode"),
            phnix_sub_mode=phnix.get("sub_mode"),
            phnix_error=phnix.get("error"),
            phnix_fail_0=phnix.get("fail_0"),
            capabilities=frozen_capabilities,
            raw_live_status=live,
            raw_v3_status=v3,
            raw_pool_status=pool,
        )

    async def async_set_lighting(self, on: bool) -> None:
        if "v3_lighting" in self._last_capabilities:
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/lighting_config",
                json={"enabled": 3 if on else 1},
                headers={"Content-Type": "application/json"},
            )
            return
        await self.async_set_lighting_settings(always_active=on)

    async def async_set_pump_speed(self, speed: str) -> None:
        if speed not in PUMP_SPEED_OPTIONS:
            raise SmartPoolConnectError(f"Unsupported filter pump speed: {speed}")
        filter_settings = await self.async_get_filter_settings(force_refresh=True)
        filter_settings.pump_speed = speed
        await self.async_set_filter_settings(filter_settings)

    async def async_cover_open(self) -> None:
        if "covco_cover" in self._last_capabilities:
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/covco_data",
                json={"automatic_movement_open": True},
                headers={"Content-Type": "application/json"},
            )
            return
        if "cover" not in self._last_capabilities:
            raise SmartPoolConnectError(
                "Cover control is unavailable because no validated control contract was detected"
            )
        await self._request_json("POST", f"/api/cmd/{self.pool_id}/cover_open", headers={"Content-Type": "application/json"})

    async def async_cover_close(self) -> None:
        if "covco_cover" in self._last_capabilities:
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/covco_data",
                json={"automatic_movement_close": True},
                headers={"Content-Type": "application/json"},
            )
            return
        if "cover" not in self._last_capabilities:
            raise SmartPoolConnectError(
                "Cover control is unavailable because no validated control contract was detected"
            )
        await self._request_json("POST", f"/api/cmd/{self.pool_id}/cover_close", headers={"Content-Type": "application/json"})

    async def async_cover_stop(self) -> None:
        if "covco_cover" in self._last_capabilities:
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/covco_data",
                json={"automatic_movement_stop": True},
                headers={"Content-Type": "application/json"},
            )
            return
        if "cover" not in self._last_capabilities:
            raise SmartPoolConnectError(
                "Cover control is unavailable because no validated control contract was detected"
            )
        await self._request_json("POST", f"/api/cmd/{self.pool_id}/cover_stop", headers={"Content-Type": "application/json"})
