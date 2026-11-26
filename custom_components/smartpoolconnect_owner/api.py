"""Async client for SmartPoolConnect owner portal."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import json
import logging
import math
import re
import secrets
from time import monotonic
from typing import Any, Iterator
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
CL_SHOCK_STATUS: dict[int, str] = {
    0: "idle",
    201: "waiting_for_pump",
    205: "active",
}
_HTML_BADGE_PATTERN = re.compile(
    r'<span\b[^>]*\bdata-slot=["\']badge["\'][^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_PH_PAGE_CONTENT_PATTERN = re.compile(
    r'<(?:main|form)\b[^>]*>(.*?)</(?:main|form)>',
    re.IGNORECASE | re.DOTALL,
)
_API_VERSION_PATTERN = re.compile(r"^v?(\d+(?:\.\d+)*)$", re.IGNORECASE)
_STREAM_ENQUEUE_CALL_PATTERN = re.compile(
    r"streamController\s*\.\s*enqueue\s*\(", re.IGNORECASE
)
_STREAM_CHUNK_PATTERN = re.compile(r"^([A-Z])(\d+):(.*)$", re.DOTALL)
# Bounds apply only to API-version extraction from the streamed pool document.
# They do not change the independent 8 MiB rendered-page scan used by pH/Cl.
_MAX_POOL_DOCUMENT_SCAN_BYTES = 8 * 1024 * 1024
_MAX_INITIAL_STREAM_PAYLOAD_BYTES = 2 * 1024 * 1024
_MAX_INITIAL_STREAM_SLOTS = 50_000
_MAX_STREAM_ARGUMENT_BYTES = 2 * 1024 * 1024
_MAX_STREAM_CHUNKS = 64
_MAX_POOL_SUMMARY_CHUNK_BYTES = 256 * 1024
_MAX_POOL_SUMMARY_SLOTS = 4096
# Flow badges are rendered before the first stream continuation and can occur
# several megabytes into the pH/Cl pages. Keep this bound unchanged.
_MAX_RENDERED_PAGE_SCAN_BYTES = 8 * 1024 * 1024
HISTORICAL_CACHE_INTERVAL: float = 60 * 60
HISTORICAL_BACKFILL_WEEKS: int = 13
HISTORICAL_ROUTE_ID = "pool/routes/$pid.historical"
HISTORICAL_ROUTE_QUERY = "_routes=root%2Cpool%2Froutes%2F%24pid.historical"
LIGHTING_ROUTE_QUERY = "_routes=root%2Cpool%2Froutes%2F%24pid.lighting"

# Confirmed v3 ``lighting_config.enabled`` bitmask. Every update must use
# read-modify-write so changing the physical light does not reset either cover
# protection flag (and changing a cover flag does not switch the light).
LIGHTING_ON_BIT = 0b0010
LIGHTING_EXTERNAL_COVER_BIT = 0b0100
LIGHTING_INTERNAL_COVER_BIT = 0b1000
V3_ONLY_DIAGNOSTIC_CAPABILITIES = frozenset(
    {
        "v3_flow_paddle",
        "v3_ph_control",
        "v3_cl_control",
        "v3_carrier_version",
        "v3_filter_modbus_power",
        "v3_filter_modbus_status",
        "v3_filter_pump_error",
        "v3_filter_pump_error_code",
        "v3_ph_input_error",
        "v3_rx_input_error",
        "v3_tds_pollution",
        "v3_tds_salt",
    }
)


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
    cl_shock_status: str | None = None
    ph_dosing_flow_status: str | None = None
    cl_dosing_flow_status: str | None = None
    v3_flow_paddle_status: str | None = None
    v3_ph_control: int | None = None
    v3_cl_control: int | None = None
    carrier_version: str | None = None
    filter_modbus_power: float | None = None
    filter_modbus_status: int | None = None
    filter_pump_error: str | None = None
    filter_pump_error_code: int | None = None
    ph_input_error: int | None = None
    rx_input_error: int | None = None
    tds_pollution: float | None = None
    tds_salt: float | None = None
    lighting_on: bool | None = None
    lighting_always_active: bool | None = None
    lighting_cover_disabled: bool | None = None
    lighting_internal_cover_disabled: bool | None = None
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
    gui_version: str | None = None
    main_version: str | None = None
    io_version: str | None = None
    deck_version: str | None = None
    api_version: str | None = None
    mac_address: str | None = None
    ambient_temperature: float | None = None
    system_temperature_imx: float | None = None
    system_temperature_main: float | None = None
    last_backwash_at: datetime | None = None
    capabilities: frozenset[str] = frozenset()
    raw_live_status: dict[str, Any] | None = None
    raw_v3_status: dict[str, Any] | None = None
    raw_pool_status: dict[str, Any] | None = None


@dataclass(slots=True)
class PoolHistoricalStatus:
    """Latest values extracted from the low-frequency historical route."""

    ambient_temperature: float | None = None
    system_temperature_imx: float | None = None
    system_temperature_main: float | None = None
    last_backwash_at: datetime | None = None

    @property
    def available(self) -> bool:
        """Return whether the historical route supplied at least one value."""

        return any(
            value is not None
            for value in (
                self.ambient_temperature,
                self.system_temperature_imx,
                self.system_temperature_main,
                self.last_backwash_at,
            )
        )


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
    source: str = "legacy"


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
    source: str = "legacy"


@dataclass(slots=True)
class PoolLightingSettings:
    always_active: bool | None = None
    cover_disabled: bool | None = None
    internal_cover_disabled: bool | None = None
    schedule_enabled: bool | None = None
    schedule_start_time: str | None = None
    schedule_stop_time: str | None = None
    schedule_days: tuple[str, ...] = ()
    dimming: str | None = None
    switch_pulse: str | None = None
    detected: bool = False
    valid: bool = False
    missing_fields: tuple[str, ...] = ()
    source: str = "legacy"
    enabled_mask: int | None = None


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


def _find_config_with_keys(obj: Any, keys: set[str]) -> dict[str, Any] | None:
    """Find a nested configuration object containing one of the given keys."""

    if isinstance(obj, dict):
        if any(key in obj for key in keys):
            return obj
        for value in obj.values():
            found = _find_config_with_keys(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_config_with_keys(value, keys)
            if found is not None:
                return found
    return None


def _days_from_mask(value: Any) -> tuple[str, ...] | None:
    """Decode a Monday-first weekday bitmask."""

    mask = _as_int(value)
    if mask is None or mask < 0 or mask > 0b1111111:
        return None
    return tuple(day for index, day in enumerate(DAYS) if mask & (1 << index))


def _days_to_mask(days: tuple[str, ...]) -> int:
    """Encode weekdays as the controller's Monday-first bitmask."""

    return sum(1 << DAYS.index(day) for day in days if day in DAYS)


def _normalise_v3_duration(value: float | None) -> float | None:
    """Convert a duration from milliseconds to seconds after v3 detection."""

    if value is None:
        return None
    return value / 1000


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


def _status_value(module: Any) -> int | None:
    """Return the newest numeric status from a controller module."""

    if not isinstance(module, dict):
        return None
    raw_status = module.get("status")
    direct = _as_int(raw_status)
    if direct is not None:
        return direct
    if isinstance(raw_status, dict):
        for key in ("actual", "value", "status"):
            direct = _as_int(raw_status.get(key))
            if direct is not None:
                return direct
    if isinstance(raw_status, list):
        candidates = [
            item
            for item in raw_status
            if isinstance(item, dict) and _as_int(item.get("status")) is not None
        ]
        if candidates:
            latest = max(
                candidates,
                key=lambda item: _as_float(item.get("timestamp")) or float("-inf"),
            )
            return _as_int(latest.get("status"))
    return None


def _cl_shock_state(data: Any) -> str | None:
    """Read only confirmed Cl shock status codes from semantic Cl blocks."""

    for name in ("cl", "cl_data", "rx_data", "dosing_data"):
        block = _find_data_block(data, name)
        if not isinstance(block, dict):
            continue
        values = _column_values(block)
        candidates: tuple[Any, ...] = (
            values.get("shock_status"),
            values.get("cl_status"),
            block.get("shock_status"),
            block.get("cl_status"),
        )
        if name in ("cl", "cl_data", "rx_data"):
            candidates += (values.get("status"), _status_value(block))
        for candidate in candidates:
            status = _as_int(candidate)
            if status in CL_SHOCK_STATUS:
                return CL_SHOCK_STATUS[status]
    return None


def _extract_dosing_page_flow_status(
    document: str, ok_label: str
) -> str | None:
    """Parse only a confirmed current badge in a server-rendered dosing page.

    Translation dictionaries embedded elsewhere in the document contain both
    labels and must not be mistaken for the live badge. Restricting the parser
    to rendered ``data-slot=badge`` elements prevents that false positive.
    """

    if not isinstance(document, str) or not document.strip():
        return None
    scan_limit = min(len(document), _MAX_RENDERED_PAGE_SCAN_BYTES)
    stream_index = document.find("streamController.enqueue", 0, scan_limit)
    if stream_index < 0:
        if len(document) > _MAX_RENDERED_PAGE_SCAN_BYTES:
            return None
        stream_index = len(document)
    body = document[:stream_index]
    regions = _PH_PAGE_CONTENT_PATTERN.findall(body)
    if regions:
        body = "\n".join(regions)
    labels = []
    for raw in _HTML_BADGE_PATTERN.findall(body):
        label = unescape(_HTML_TAG_PATTERN.sub("", raw)).strip()
        if label in {ok_label, "Geen Doorstroming"}:
            labels.append(label)
    unique = set(labels)
    if unique == {ok_label}:
        return "flow_ok"
    if unique == {"Geen Doorstroming"}:
        return "no_flow"
    return None


def _extract_ph_page_flow_status(document: str) -> str | None:
    """Parse the confirmed ``pH OK``/``Geen Doorstroming`` page badge."""

    return _extract_dosing_page_flow_status(document, "pH OK")


def _extract_cl_page_flow_status(document: str) -> str | None:
    """Parse the confirmed ``Cl OK``/``Geen Doorstroming`` page badge."""

    return _extract_dosing_page_flow_status(document, "Cl OK")


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


def _raw_v3_column_value(
    data: Any, table: str, field: str, expected_type: str
) -> Any | None:
    """Return one typed value from a genuine raw V3 table column.

    Nexus Full Control can expose normalized/default fields with familiar names,
    and unsupported firmware tables can contain null or sentinel values. V3-only
    diagnostic capabilities must therefore be proven by the exact raw table,
    column name and firmware type rather than by a normalized ``PoolStatus``
    attribute or a recursively found default.
    """

    block = _find_data_block(data, table)
    if not isinstance(block, dict) or not isinstance(block.get("columns"), list):
        return None
    for column in block["columns"]:
        if not isinstance(column, dict) or column.get("name") != field:
            continue
        if column.get("type") != expected_type:
            return None
        return column.get("value")
    return None


def _raw_v3_int(
    data: Any,
    table: str,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    """Return a bounded raw V3 integer, rejecting booleans and sentinels."""

    value = _as_int(_raw_v3_column_value(data, table, field, "number"))
    return value if value is not None and minimum <= value <= maximum else None


def _raw_v3_float(
    data: Any,
    table: str,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    """Return a bounded raw V3 number, rejecting null/NaN/sentinel values."""

    value = _as_finite_float(_raw_v3_column_value(data, table, field, "number"))
    return value if value is not None and minimum <= value <= maximum else None


def _validated_runtime_block(
    data: Any,
    name: str,
    required_fields: set[str],
) -> dict[str, Any] | None:
    """Return a named V3 runtime block when its semantic schema is present.

    Controller ``control`` values are deliberately not interpreted here. Real
    V3 captures use negative values for working modules, so module detection is
    based on the module-specific fields instead of a generic status/control
    sentinel.
    """

    block = _find_data_block(data, name)
    values = _column_values(block)
    return values if required_fields.issubset(values) else None


def _backwash_runtime_capability(data: Any) -> bool:
    """Return whether V3 data proves a controllable backwash module exists."""

    values = _validated_runtime_block(
        data,
        "backwash_data",
        {"state", "manual_start", "manual_stop"},
    )
    if values is None:
        return False
    return all(
        values[field] is None or isinstance(values[field], bool)
        for field in ("manual_start", "manual_stop")
    )


def _lighting_runtime_capability(data: Any) -> bool:
    """Return whether V3 lighting telemetry/commands prove module presence."""

    values = _validated_runtime_block(
        data,
        "lighting_data",
        {"active", "cmd_next", "cmd_reset", "cmd_preset"},
    )
    if values is None:
        return False
    return all(
        values[field] is None or isinstance(values[field], bool)
        for field in ("cmd_next", "cmd_reset", "cmd_preset")
    )


def _covco_telemetry(data: Any) -> tuple[bool, float | None, str | None]:
    """Return proven Covco presence, position percentage, and endpoint state.

    Calibrated, distinct encoder endpoints prove that a Covco cover is
    installed. Runtime telemetry (including hysteresis and the momentary
    command columns) may legitimately be absent during an early refresh and
    must not suppress the capability or all cover entities.

    Movement is derived from the confirmed active control state/direction and
    from measured motor activity plus the wished endpoint. Undocumented
    ``position_state`` enum values are deliberately not guessed.
    """

    values = _column_values(_find_data_block(data, "covco_data"))
    open_location = _as_finite_float(values.get("open_location"))
    close_location = _as_finite_float(values.get("close_location"))
    hysteresis = _as_finite_float(values.get("hys_location"))
    if (
        open_location is None
        or close_location is None
        or (hysteresis is not None and hysteresis < 0)
        or math.isclose(open_location, close_location)
    ):
        return False, None, None

    current_location = _as_finite_float(values.get("current_location"))
    if current_location is None:
        return True, None, None

    span = open_location - close_location
    position = max(0.0, min(100.0, (current_location - close_location) / span * 100.0))
    tolerance = min(hysteresis or 0.0, abs(span) / 2)
    state = None
    control_state = _as_int(values.get("control_state"))
    control_direction = _as_int(values.get("control_direction"))
    motor_power = _as_finite_float(values.get("motor_power_w")) or 0.0
    motor_current = _as_finite_float(values.get("motor_current_a")) or 0.0
    motor_ccr = _as_finite_float(values.get("ccr_motor")) or 0.0
    wished_location = _as_finite_float(values.get("wished_location"))
    motor_active = motor_power > 0.5 or motor_current > 0.05 or motor_ccr > 0

    if control_state == 4 and control_direction in (0, 1):
        state = "opening" if control_direction == 1 else "closing"
    elif motor_active and wished_location is not None:
        if abs(wished_location - open_location) <= tolerance:
            state = "opening"
        elif abs(wished_location - close_location) <= tolerance:
            state = "closing"
    elif abs(current_location - open_location) <= tolerance:
        state = "open"
    elif abs(current_location - close_location) <= tolerance:
        state = "closed"
    return True, round(position, 1), state


def _covco_telemetry_with_fallback(
    live: Any,
    v3: Any,
    pool_route: Any,
) -> tuple[bool, float | None, str | None]:
    """Read Covco telemetry from all confirmed sources in priority order."""

    detected = False
    for source in (live, v3, pool_route):
        telemetry = _covco_telemetry(source)
        if telemetry[0]:
            detected = True
            if telemetry[1] is not None or telemetry[2] is not None:
                return telemetry
    return detected, None, None


def _phnix_telemetry(data: Any) -> tuple[bool, dict[str, float | int | None]]:
    """Return PHNIX telemetry when its schema has at least one usable value.

    Individual readings are allowed to be temporarily missing. Once the
    module is proven, Home Assistant can create all PHNIX entities and expose
    missing readings as Unknown until a later refresh supplies them.
    """

    values = _validated_runtime_block(
        data,
        "temperature_phnx_data",
        {"sp", "inlet", "outlet"},
    )
    if values is None:
        return False, {}
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
    valid = any(value is not None for value in telemetry.values())
    return valid, telemetry if valid else {}


def _phnix_telemetry_with_fallback(
    *sources: Any,
) -> tuple[bool, dict[str, float | int | None]]:
    """Merge PHNIX fields without letting one temporary null hide another source."""

    merged: dict[str, float | int | None] = {
        "setpoint": None,
        "inlet": None,
        "outlet": None,
        "coil": None,
        "ambient": None,
        "mode": None,
        "sub_mode": None,
        "error": None,
        "fail_0": None,
    }
    detected = False
    for source in sources:
        source_detected, telemetry = _phnix_telemetry(source)
        if not source_detected:
            continue
        detected = True
        for key, value in telemetry.items():
            if merged[key] is None and value is not None:
                merged[key] = value
    return detected, merged if detected else {}


def _analogue_telemetry(data: Any) -> dict[str, float | None]:
    """Return calibrated analogue values exposed by the V3 controller API."""

    values = _column_values(_find_data_block(data, "analoge_data"))
    return {
        "ph": _as_finite_float(values.get("ph")),
        "rx": _as_finite_float(values.get("rx")),
        "water_temperature": _as_finite_float(values.get("water_t")),
        "ambient_temperature": _as_finite_float(values.get("ambient_t")),
    }


def _v3_flow_telemetry(data: Any) -> dict[str, Any]:
    """Return the confirmed raw V3 flow inputs and dosing status values."""

    paddle = _raw_v3_column_value(
        data, "input_data", "flow_paddle_detect", "boolean"
    )
    carrier = _raw_v3_column_value(data, "pool_fw", "carrier_version", "text")
    carrier = carrier.strip() if isinstance(carrier, str) else None
    if carrier is not None and not re.fullmatch(
        r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", carrier
    ):
        carrier = None
    return {
        "paddle": paddle if isinstance(paddle, bool) else None,
        # Documented carrier status families occupy a small signed range. The
        # bound rejects common unsupported integer sentinels without excluding
        # the confirmed -28/-204 and positive operating states.
        "ph_control": _raw_v3_int(
            data, "dosing_data", "ph_control", minimum=-999, maximum=999
        ),
        "cl_control": _raw_v3_int(
            data, "dosing_data", "cl_control", minimum=-999, maximum=999
        ),
        "carrier_version": carrier,
    }


def _extract_v3_flow_modes(data: Any) -> tuple[int | None, int | None]:
    """Return per-channel V3 flow modes from ``dosing_config``.

    Bit 0 confirms that a dosing channel uses the shared flow-paddle input.
    Keeping this check separate prevents a disconnected or unused paddle from
    being presented as a channel-specific no-flow alarm.
    """

    config = _find_config_with_keys(data, {"ph_mode_flow", "cl_mode_flow"})
    if config is None:
        return None, None
    return _as_int(config.get("ph_mode_flow")), _as_int(config.get("cl_mode_flow"))


def _v3_channel_flow_status(
    mode: int | None, paddle: bool | None, control: int | None
) -> str | None:
    """Return a channel flow state only when its paddle mode is confirmed."""

    if mode is None or not (mode & 0x01):
        return None
    if paddle is True:
        return "flow_ok"
    if paddle is False or control in (-28, -204):
        return "no_flow"
    return None


def _v3_diagnostics(data: Any) -> dict[str, Any]:
    """Extract capability-driven, read-only diagnostics from V3 live data."""

    error_flag = _raw_v3_int(
        data, "filter_data", "mb_err_flag", minimum=0, maximum=1
    )
    error_code = _raw_v3_int(
        data, "filter_data", "mb_err_code", minimum=0, maximum=65534
    )
    # Treat the pump error pair as one contract. A lone flag or code is not
    # enough to prove that genuine V3 Modbus pump diagnostics are supported.
    error_contract_valid = error_flag is not None and error_code is not None
    return {
        "filter_modbus_power": _raw_v3_float(
            data, "filter_data", "mb_watt", minimum=0, maximum=100_000
        ),
        "filter_modbus_status": _raw_v3_int(
            data, "filter_data", "mb_status", minimum=0, maximum=65534
        ),
        "filter_pump_error": (
            "error"
            if error_contract_valid and error_flag == 1
            else "ok"
            if error_contract_valid and error_flag == 0
            else None
        ),
        "filter_pump_error_code": error_code if error_contract_valid else None,
        "ph_input_error": _raw_v3_int(
            data, "analoge_data", "ph_input_error", minimum=0, maximum=65534
        ),
        "rx_input_error": _raw_v3_int(
            data, "analoge_data", "rx_input_error", minimum=0, maximum=65534
        ),
        "tds_pollution": _raw_v3_float(
            data, "analoge_data", "tds_pollution", minimum=0, maximum=1_000_000
        ),
        "tds_salt": _raw_v3_float(
            data, "analoge_data", "tds_salt", minimum=0, maximum=1_000_000
        ),
    }


def _v3_diagnostic_capabilities(
    flow: dict[str, Any], diagnostics: dict[str, Any]
) -> set[str]:
    """Return only capabilities proven by validated raw V3 source fields."""

    capabilities = {
        f"v3_{key}" for key, value in diagnostics.items() if value is not None
    }
    capabilities.update(
        f"v3_{key}"
        for key in ("ph_control", "cl_control", "carrier_version")
        if flow.get(key) is not None
    )
    if flow.get("paddle") is not None:
        capabilities.add("v3_flow_paddle")
    return capabilities


def _v3_filter_telemetry(data: Any) -> tuple[bool | None, str | None]:
    """Return pump state and the isolated practical raw V3 speed mapping.

    This mapping applies only to raw V3 ``filter_data.actual`` semantics and is
    intentionally separate from the normalized V1/V2/public-API enum. Values 0,
    2 and 3 are confirmed; 1, 4 and 5 are provisional pending hardware tests.
    """

    raw_speed_map = {
        0: "off",
        1: "min",
        2: "low",
        3: "medium",
        4: "high",
        5: "maximum",
    }
    values = _column_values(_find_data_block(data, "filter_data"))
    actual = _as_int(values.get("actual"))
    gpio = _column_values(_find_data_block(data, "gpio_o_data"))
    pump_output = gpio.get("pump")
    pump_status = pump_output if isinstance(pump_output, bool) else None

    # speed_1 is not a reliable Min discriminator: retained Nexus II fixtures
    # show it active alongside raw 2 and 3. Only flags with consistent retained
    # semantics participate in validation/preference.
    flag_map = {
        "speed_2": "low",
        "speed_3": "medium",
        "speed_4": "high",
    }
    flag_values = {name: gpio.get(name) for name in flag_map}
    flags_available = all(isinstance(value, bool) for value in flag_values.values())
    active_flag_speeds = [
        flag_map[name] for name, value in flag_values.items() if value is True
    ]
    flagged_speed = active_flag_speeds[0] if len(active_flag_speeds) == 1 else None

    # A separately confirmed OFF output remains authoritative, including when a
    # stale raw value or speed flag is still present.
    if pump_status is False:
        return False, "off"

    if actual is None:
        if flags_available and flagged_speed is not None:
            return True, flagged_speed
        return pump_status, None

    numeric_speed = raw_speed_map.get(actual)
    if numeric_speed is None:
        # Raw values outside 0-5 are unsupported regardless of GPIO flags.
        return pump_status, None

    if actual == 0:
        # 0=Off is confirmed, but a contradictory active pump output is surfaced
        # as running with unknown speed rather than silently choosing either side.
        return (False, "off") if pump_status is not True else (True, None)

    if flags_available and active_flag_speeds:
        # Prefer one explicit flag only when it agrees with the numeric raw value.
        # Multiple or mismatching flags are contradictory and remain Unknown.
        if flagged_speed == numeric_speed:
            return True, flagged_speed
        return True if pump_status is None else pump_status, None

    return True if pump_status is None else pump_status, numeric_speed


def _v3_lighting_state(data: Any) -> bool | None:
    """Return physical V3 lighting state using confirmed active-low inputs."""

    values = _column_values(_find_data_block(data, "lighting_data"))
    control = _as_int(values.get("control"))
    if control in (0, 1):
        # Exact OFF/ON captures prove control=1 is OFF and control=0 is ON.
        return control == 0

    # GPIO is accepted only when both independently exposed active-low outputs
    # are Boolean and agree. A lone or contradictory GPIO value is not guessed.
    gpio_a = _column_values(_find_data_block(data, "gpio_a_data")).get("light")
    gpio_o = _column_values(_find_data_block(data, "gpio_o_data")).get("light")
    if isinstance(gpio_a, bool) and isinstance(gpio_o, bool) and gpio_a == gpio_o:
        return not gpio_a
    return None


def _decode_route_response(text: Any) -> Any | None:
    """Decode one Remix response, returning None for malformed content."""
    if not isinstance(text, str):
        return text
    try:
        return decode_remix(text)
    except RemixDecodeError:
        _LOGGER.debug("Could not decode Remix route response", exc_info=True)
        return None


def _normalise_api_version(raw_version: Any) -> str | None:
    """Return an API-version display value such as ``v2``."""

    if isinstance(raw_version, bool):
        return None
    if isinstance(raw_version, int):
        return f"v{raw_version}" if raw_version >= 0 else None
    if isinstance(raw_version, float):
        return (
            f"v{int(raw_version)}"
            if raw_version >= 0 and raw_version.is_integer()
            else None
        )
    if not isinstance(raw_version, str):
        return None
    match = _API_VERSION_PATTERN.fullmatch(raw_version.strip())
    return f"v{match.group(1)}" if match else None


def _count_flattened_slots(payload: str) -> int | None:
    """Count an initial flattened JSON table without decoding its values.

    Remix continuation references use the initial table's length as their
    global offset.  A string-aware structural scan supplies that offset without
    allocating the 24k-slot table or hydrating any part of the graph.
    """

    if not payload or len(payload) > _MAX_INITIAL_STREAM_PAYLOAD_BYTES:
        return None
    position = 0
    length = len(payload)
    while position < length and payload[position].isspace():
        position += 1
    if position >= length or payload[position] != "[":
        return None

    stack = ["]"]
    position += 1
    in_string = False
    escaped = False
    value_started = False
    after_comma = False
    count = 0

    while position < length:
        character = payload[position]
        position += 1
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
            if len(stack) == 1:
                value_started = True
                after_comma = False
            continue
        if character in "[{":
            stack.append("]" if character == "[" else "}")
            if len(stack) == 2:
                value_started = True
                after_comma = False
            continue
        if character in "]}":
            if not stack or character != stack[-1]:
                return None
            if len(stack) == 1:
                if after_comma:
                    return None
                if value_started:
                    count += 1
                if count > _MAX_INITIAL_STREAM_SLOTS:
                    return None
                return count if not payload[position:].strip() else None
            stack.pop()
            continue
        if len(stack) != 1:
            continue
        if character == ",":
            if not value_started:
                return None
            count += 1
            if count > _MAX_INITIAL_STREAM_SLOTS:
                return None
            value_started = False
            after_comma = True
        elif not character.isspace():
            value_started = True
            after_comma = False
    return None


def _chunk_reference(
    slots: list[Any], start_index: int, reference: Any
) -> Any | None:
    """Resolve one continuation-local reference without hydrating its graph."""

    if not isinstance(reference, int) or isinstance(reference, bool):
        return None
    local_index = reference - start_index
    if 0 <= local_index < len(slots):
        return slots[local_index]
    return None


def _chunk_object_field(
    slots: list[Any], start_index: int, record: Any, field: str
) -> Any | None:
    """Resolve one named field from a continuation-local flattened object."""

    if not isinstance(record, dict):
        return None
    # Accept literal objects as a defensive renderer compatibility path.
    if field in record:
        return record.get(field)
    for raw_key, value_reference in record.items():
        if not isinstance(raw_key, str) or not raw_key.startswith("_"):
            continue
        try:
            key_reference = int(raw_key[1:])
        except ValueError:
            continue
        if _chunk_reference(slots, start_index, key_reference) == field:
            return _chunk_reference(slots, start_index, value_reference)
    return None


def _extract_api_version_from_summary_chunk(
    slots: list[Any],
    start_index: int,
    pool_id: str,
    diagnostics: dict[str, Any] | None = None,
) -> str | None:
    """Resolve ``root.items`` and select the configured flattened pool record."""

    if not slots:
        return None
    root = slots[0]  # The continuation root is at absolute ``start_index``.
    items = _chunk_object_field(slots, start_index, root, "items")
    if isinstance(items, list):
        for item_reference in items:
            record = _chunk_reference(slots, start_index, item_reference)
            if _chunk_object_field(slots, start_index, record, "pid") != pool_id:
                continue
            if diagnostics is not None:
                diagnostics["configured_pool_found"] = True
            raw_version = _chunk_object_field(
                slots, start_index, record, "api_version"
            )
            api_version = _normalise_api_version(raw_version)
            if api_version is not None:
                return api_version

    # Accept a compact literal record if a renderer emits one.
    if isinstance(root, dict) and root.get("pid") == pool_id:
        if diagnostics is not None:
            diagnostics["configured_pool_found"] = True
        return _normalise_api_version(root.get("api_version"))
    return None


def _summary_chunk_start_candidates(
    slots: list[Any], initial_slot_count: int | None
) -> Iterator[int]:
    """Yield bounded candidate offsets for one pool-summary continuation.

    Normally the continuation starts at ``len(initial_flattened_table)``.  The
    streamed summary is also self-describing, however: its root object's key
    reference for ``items`` and the local position of the literal ``items``
    differ by exactly the continuation start.  Deriving that offset lets the
    small summary continuation be resolved even when the preceding megabyte-
    sized enqueue frame cannot be decoded in the live HTTP response.
    """

    candidates: list[int] = []
    if isinstance(initial_slot_count, int) and initial_slot_count >= 0:
        candidates.append(initial_slot_count)

    root = slots[0] if slots else None
    if isinstance(root, dict):
        item_key_positions = [
            index for index, value in enumerate(slots) if value == "items"
        ]
        for raw_key in root:
            if not isinstance(raw_key, str) or not raw_key.startswith("_"):
                continue
            try:
                key_reference = int(raw_key[1:])
            except ValueError:
                continue
            for local_index in item_key_positions:
                candidate = key_reference - local_index
                if candidate >= 0:
                    candidates.append(candidate)

    # A compact literal record does not use global references.
    candidates.append(0)
    yielded: set[int] = set()
    for candidate in candidates:
        if candidate in yielded:
            continue
        yielded.add(candidate)
        yield candidate


def _iter_pool_document_continuations(
    document: Any,
) -> Iterator[tuple[int, str, int, int, list[Any]]]:
    """Yield bounded continuations with their true append positions.

    The chunk id identifies the promise being fulfilled.  It is deliberately
    returned only as metadata and is never used as a slot offset.  Continuation
    slots append at the current flattened-table length.
    """

    if (
        not isinstance(document, str)
        or not document
        or len(document) > _MAX_POOL_DOCUMENT_SCAN_BYTES
    ):
        return

    decoder = json.JSONDecoder()
    position = 0
    initial_slot_count: int | None = None
    next_chunk_start: int | None = None
    chunk_count = 0

    while match := _STREAM_ENQUEUE_CALL_PATTERN.search(document, position):
        argument_start = match.end()
        position = argument_start
        raw_argument = document[
            argument_start : argument_start + _MAX_STREAM_ARGUMENT_BYTES
        ]
        encoded_argument = raw_argument.lstrip()
        leading_whitespace = len(raw_argument) - len(encoded_argument)
        try:
            payload, consumed = decoder.raw_decode(encoded_argument)
        except json.JSONDecodeError:
            continue
        position = argument_start + leading_whitespace + consumed
        if not isinstance(payload, str):
            continue

        stripped = payload.strip()
        if initial_slot_count is None:
            if not stripped.startswith("["):
                continue
            initial_slot_count = _count_flattened_slots(stripped)
            if initial_slot_count is None:
                return
            next_chunk_start = initial_slot_count
            continue

        chunk_match = _STREAM_CHUNK_PATTERN.fullmatch(stripped)
        if chunk_match is None or next_chunk_start is None:
            continue
        chunk_count += 1
        if chunk_count > _MAX_STREAM_CHUNKS:
            return
        kind, raw_chunk_id, body = chunk_match.groups()
        if len(body) > _MAX_POOL_SUMMARY_CHUNK_BYTES:
            return
        try:
            slots = json.loads(body)
        except json.JSONDecodeError:
            return
        if not isinstance(slots, list) or len(slots) > _MAX_POOL_SUMMARY_SLOTS:
            return

        # Append at the current table length.  For the supplied real document
        # this is 24,047 even though the promise being fulfilled is P24040.
        chunk_start = next_chunk_start
        next_chunk_start += len(slots)
        yield (
            initial_slot_count,
            kind,
            int(raw_chunk_id),
            chunk_start,
            slots,
        )


def _extract_api_version_from_pool_document(
    document: Any,
    pool_id: str,
    diagnostics: dict[str, Any] | None = None,
) -> str | None:
    """Selectively decode the configured pool's streamed API version.

    This preserves the successful semantics of the original implementation:
    locate the configured pool record by its exact ``pid`` and read that same
    record's ``api_version``.  Unlike the original, it never expands the full
    Remix graph.  It first uses the initial table length when available, then
    validates a continuation-local offset derived from the ``items`` reference
    so the small summary does not depend on decoding the large initial frame.
    """

    if diagnostics is not None:
        diagnostics.update(
            {
                "document_length": len(document) if isinstance(document, str) else 0,
                "enqueue_chunks": 0,
                "initial_flattened_slots": None,
                "continuation_label": None,
                "continuation_slots": None,
                "configured_pool_found": False,
                "resolved": False,
            }
        )
    if (
        not pool_id
        or not isinstance(document, str)
        or not document
        or len(document) > _MAX_POOL_DOCUMENT_SCAN_BYTES
    ):
        return None

    decoder = json.JSONDecoder()
    position = 0
    initial_slot_count: int | None = None
    while match := _STREAM_ENQUEUE_CALL_PATTERN.search(document, position):
        if diagnostics is not None:
            diagnostics["enqueue_chunks"] += 1
        argument_start = match.end()
        position = argument_start
        raw_argument = document[
            argument_start : argument_start + _MAX_STREAM_ARGUMENT_BYTES
        ]
        encoded_argument = raw_argument.lstrip()
        leading_whitespace = len(raw_argument) - len(encoded_argument)
        try:
            payload, consumed = decoder.raw_decode(encoded_argument)
        except json.JSONDecodeError:
            # Do not make the small continuation depend on successful decoding
            # of a preceding, much larger initial enqueue argument.
            continue
        position = argument_start + leading_whitespace + consumed
        if not isinstance(payload, str):
            continue

        stripped = payload.strip()
        if stripped.startswith("["):
            initial_slot_count = _count_flattened_slots(stripped)
            if diagnostics is not None:
                diagnostics["initial_flattened_slots"] = initial_slot_count
            continue

        chunk_match = _STREAM_CHUNK_PATTERN.fullmatch(stripped)
        if chunk_match is None:
            continue
        kind, raw_chunk_id, body = chunk_match.groups()
        if kind != "P" or len(body) > _MAX_POOL_SUMMARY_CHUNK_BYTES:
            continue
        try:
            slots = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(slots, list) or len(slots) > _MAX_POOL_SUMMARY_SLOTS:
            continue
        if diagnostics is not None:
            diagnostics["continuation_label"] = f"{kind}{raw_chunk_id}"
            diagnostics["continuation_slots"] = len(slots)

        for chunk_start in _summary_chunk_start_candidates(
            slots, initial_slot_count
        ):
            api_version = _extract_api_version_from_summary_chunk(
                slots,
                chunk_start,
                pool_id,
                diagnostics,
            )
            if api_version is not None:
                if diagnostics is not None:
                    diagnostics["resolved"] = True
                return api_version
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


def _extract_current_from_pool_data(
    text: str, pool_id: str
) -> tuple[
    str | None,
    float | None,
    float | None,
    str | None,
]:
    decoded = _decode_route_response(text)
    pool = _find_pool_record(decoded, pool_id)
    if pool is None:
        _LOGGER.warning("POOL DATA: pool_id not found: %s", pool_id)
        return None, None, None, None
    name = pool.get("name") if isinstance(pool.get("name"), str) else None
    ph = _metric_actual(pool.get("ph"))
    rx = _sanitize_rx(_metric_actual(pool.get("cl")))
    shock = _cl_shock_state({"cl": pool.get("cl")})
    return (
        name,
        round(ph, 2) if ph is not None else None,
        round(rx, 0) if rx is not None else None,
        shock,
    )


def _normalize_mac_address(value: Any) -> str | None:
    """Return a canonical MAC address when the portal exposes one."""

    if not isinstance(value, str):
        return None
    compact = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(compact) != 12:
        return None
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2)).upper()


def _extract_system_details(decoded: Any, pool_id: str) -> dict[str, Any]:
    """Extract requested controller details from semantic route fields."""

    pool = _find_pool_record(decoded, pool_id)
    firmware = pool.get("firmware") if isinstance(pool, dict) else None
    firmware = firmware if isinstance(firmware, dict) else {}

    mac_address = None
    if isinstance(pool, dict):
        sources = [pool]
        sources.extend(
            value
            for key in ("controller", "gateway", "device", "hardware")
            if isinstance((value := pool.get(key)), dict)
        )
        sources.append(firmware)
        for source in sources:
            for key in (
                "mac_address",
                "mac",
                "macAddress",
                "controller_mac",
                "controllerMac",
            ):
                mac_address = _normalize_mac_address(source.get(key))
                if mac_address is not None:
                    break
            if mac_address is not None:
                break

    def version(key: str) -> str | None:
        value = firmware.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    return {
        "mac_address": mac_address,
        "gui_version": version("gui_version"),
        "main_version": version("main_version"),
        "io_version": version("io_version"),
        "deck_version": version("deck_version"),
    }


def _extract_api_version(decoded: Any, pool_id: str) -> str | None:
    """Return the pool API version as a display value such as ``v2``."""

    pool = _find_pool_record(decoded, pool_id)
    if not isinstance(pool, dict):
        return None
    return _normalise_api_version(pool.get("api_version"))


def _as_utc_datetime(value: Any) -> datetime | None:
    """Convert a SmartPoolConnect epoch or ISO timestamp to UTC."""

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(
            tzinfo=timezone.utc
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if not math.isfinite(timestamp):
            return None
        if abs(timestamp) >= 100_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return _as_utc_datetime(float(text))
            except ValueError:
                return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(
            tzinfo=timezone.utc
        )
    return None


def _historical_route(decoded: Any) -> dict[str, Any] | None:
    """Return historical route data without relying on flattened slot numbers."""

    exact = route_data(decoded, HISTORICAL_ROUTE_ID)
    if isinstance(exact, dict):
        return exact
    return next(
        (
            candidate
            for candidate in find_dicts(
                decoded, {"temperature", "backwash", "range", "interval"}
            )
            if isinstance(candidate.get("temperature"), dict)
            and isinstance(candidate.get("backwash"), dict)
        ),
        None,
    )


def _latest_historical_metric(route: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest valid temperature metric from historical data."""

    temperature = route.get("temperature")
    metrics = temperature.get("metrics") if isinstance(temperature, dict) else None
    if not isinstance(metrics, list):
        return None
    candidates = [
        item
        for item in metrics
        if isinstance(item, dict) and _as_utc_datetime(item.get("timestamp")) is not None
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: _as_utc_datetime(item.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )


def _latest_backwash_timestamp(route: dict[str, Any]) -> datetime | None:
    """Return the newest observed transition from idle to active backwash."""

    backwash = route.get("backwash")
    statuses = backwash.get("status") if isinstance(backwash, dict) else None
    if not isinstance(statuses, list):
        return None
    points = sorted(
        (
            (timestamp, int(status))
            for item in statuses
            if isinstance(item, dict)
            and (status := _as_float(item.get("status"))) is not None
            and (timestamp := _as_utc_datetime(item.get("timestamp"))) is not None
        ),
        key=lambda point: point[0],
    )
    transitions = [
        timestamp
        for index, (timestamp, status) in enumerate(points)
        if status == 1 and (index == 0 or points[index - 1][1] != 1)
    ]
    return max(transitions, default=None)


def _extract_historical_status(text: str) -> PoolHistoricalStatus:
    """Decode temperatures and the latest backwash bucket from one route page."""

    decoded = _decode_route_response(text)
    route = _historical_route(decoded)
    if route is None:
        raise SmartPoolConnectError(
            "SmartPoolConnect returned malformed historical route data"
        )

    metric = _latest_historical_metric(route)
    ambient = _as_float(metric.get("ambient_temp")) if metric else None
    imx = _as_float(metric.get("imx_temp")) if metric else None
    main_raw = _as_float(metric.get("main_temp")) if metric else None
    return PoolHistoricalStatus(
        ambient_temperature=ambient,
        system_temperature_imx=imx,
        # MAIN is exposed by SmartPoolConnect in centidegrees Celsius.
        system_temperature_main=main_raw / 100 if main_raw is not None else None,
        last_backwash_at=_latest_backwash_timestamp(route),
    )


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


def _extract_v3_lighting_settings(data: Any) -> PoolLightingSettings:
    """Extract the v3 lighting contract from flat or columnar route data."""

    columns = _column_values(_find_data_block(data, "lighting_config"))
    source = columns if columns else data
    config = _find_config_with_keys(
        source,
        {
            "enabled",
            "s1_hour_start",
            "s1_min_start",
            "s1_hour_stop",
            "s1_min_stop",
            "s1_days",
        },
    )
    if config is None:
        return PoolLightingSettings(source="v3")

    enabled = _as_int(config.get("enabled"))
    explicit_schedule_enabled = _as_bool(config.get("s1_enabled"))
    start_hour = _as_int(config.get("s1_hour_start"))
    start_minute = _as_int(config.get("s1_min_start"))
    stop_hour = _as_int(config.get("s1_hour_stop"))
    stop_minute = _as_int(config.get("s1_min_stop"))
    days = _days_from_mask(config.get("s1_days"))
    missing: list[str] = []
    for key, value in (
        ("enabled", enabled),
        ("s1_hour_start", start_hour),
        ("s1_min_start", start_minute),
        ("s1_hour_stop", stop_hour),
        ("s1_min_stop", stop_minute),
        ("s1_days", days),
    ):
        if value is None:
            missing.append(key)
    if start_hour is not None and not 0 <= start_hour <= 23:
        missing.append("s1_hour_start")
    if stop_hour is not None and not 0 <= stop_hour <= 23:
        missing.append("s1_hour_stop")
    if start_minute is not None and not 0 <= start_minute <= 59:
        missing.append("s1_min_start")
    if stop_minute is not None and not 0 <= stop_minute <= 59:
        missing.append("s1_min_stop")
    missing = sorted(set(missing))
    valid = not missing
    schedule_enabled = (
        explicit_schedule_enabled
        if explicit_schedule_enabled is not None
        else bool(days)
        if days is not None
        else None
    )
    return PoolLightingSettings(
        always_active=(
            bool(enabled & LIGHTING_ON_BIT) if enabled is not None else None
        ),
        cover_disabled=(
            bool(enabled & LIGHTING_EXTERNAL_COVER_BIT)
            if enabled is not None
            else None
        ),
        internal_cover_disabled=(
            bool(enabled & LIGHTING_INTERNAL_COVER_BIT)
            if enabled is not None
            else None
        ),
        schedule_enabled=schedule_enabled,
        schedule_start_time=(
            f"{start_hour:02d}:{start_minute:02d}"
            if start_hour is not None and start_minute is not None
            else None
        ),
        schedule_stop_time=(
            f"{stop_hour:02d}:{stop_minute:02d}"
            if stop_hour is not None and stop_minute is not None
            else None
        ),
        schedule_days=days or (),
        detected=True,
        valid=valid,
        missing_fields=tuple(missing),
        source="v3",
        enabled_mask=enabled,
    )


def _extract_v3_ph_settings(data: Any) -> PoolPhSettings:
    """Extract the confirmed pH setpoint and optional timing fields."""

    config = _find_config_with_keys(data, {"ph_setpoint"})
    if config is None or "ph_setpoint" not in config:
        return PoolPhSettings(source="v3")
    target = _as_finite_float(config.get("ph_setpoint"))
    dosing_time = _as_finite_float(config.get("ph_dosing_time"))
    pausing_time = _as_finite_float(
        config.get("ph_pausing_time", config.get("ph_pause_time"))
    )
    return PoolPhSettings(
        target=target,
        dosing_time=dosing_time,
        pausing_time=pausing_time,
        detected=True,
        # Only target writes are proven for v3; never mark the legacy full-form
        # write contract valid from this partial admin response.
        valid=False,
        missing_fields=(),
        source="v3",
    )


def _extract_v3_rx_settings(data: Any) -> PoolRxSettings:
    """Extract the confirmed Rx/ORP setpoint and optional timing fields."""

    config = _find_config_with_keys(data, {"cl_setpoint"})
    if config is None or "cl_setpoint" not in config:
        return PoolRxSettings(source="v3")
    target = _as_finite_float(config.get("cl_setpoint"))
    dosing_time = _as_finite_float(
        config.get("rx_dosing_time", config.get("cl_dosing_time"))
    )
    pausing_time = _as_finite_float(
        config.get(
            "rx_pausing_time",
            config.get("rx_pause_time", config.get("cl_pausing_time")),
        )
    )
    return PoolRxSettings(
        target=target,
        dosing_time=dosing_time,
        pausing_time=pausing_time,
        detected=True,
        valid=False,
        missing_fields=(),
        source="v3",
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
        self._pool_route_fetch_lock = asyncio.Lock()
        self._pool_route_decode_lock = asyncio.Lock()
        # Keep the last valid value independently from route freshness.  API
        # Version is resolved from the already-fetched pool route; no separate
        # rendered HTML document request is needed.
        self._pool_route_api_version: str | None = None
        self._current_pool_data: tuple[
            str | None,
            float | None,
            float | None,
            str | None,
        ] = (None, None, None, None)
        self._current_pool_data_generation = 0
        self._current_pool_data_lock = asyncio.Lock()
        self._ph_page_flow_status: str | None = None
        self._ph_page_flow_detected = False
        self._ph_page_flow_generation = 0
        self._ph_page_flow_lock = asyncio.Lock()
        self._cl_page_flow_status: str | None = None
        self._cl_page_flow_detected = False
        self._cl_page_flow_generation = 0
        self._cl_page_flow_lock = asyncio.Lock()
        self._settings_bundle: tuple[Any, ...] | None = None
        self._settings_bundle_cached_at: float = 0.0
        self._admin_settings_cache: dict[str, tuple[float, Any]] = {}
        self._last_capabilities: frozenset[str] = frozenset()
        self._historical_cached_at: float = 0.0
        self._historical_backfill_complete = False
        self._historical_status = PoolHistoricalStatus()
        self._historical_lock = asyncio.Lock()

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
        """Probe one optional JSON endpoint without treating absence as fatal."""

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
        """Read both live API families while accepting either one by itself."""

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
        self._admin_settings_cache.clear()

    async def _get_admin_config(
        self,
        name: str,
        *,
        force_refresh: bool = False,
    ) -> Any | None:
        """Read one optional v3 admin-settings contract with a short cache."""

        now = monotonic()
        cached = self._admin_settings_cache.get(name)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < SETTINGS_CACHE_INTERVAL
        ):
            return cached[1]
        try:
            data = await self._request_json(
                "GET", f"/api/admin-settings/{self.pool_id}/{name}"
            )
        except SmartPoolConnectError:
            _LOGGER.debug("v3 admin settings %s are unavailable", name, exc_info=True)
            return None
        self._admin_settings_cache[name] = (now, data)
        return data

    async def _get_pool_route_text(self, *, force_refresh: bool = False) -> str:
        now = monotonic()
        if not force_refresh and self._pool_route_text is not None and now - self._pool_route_cached_at < SETTINGS_CACHE_INTERVAL:
            return self._pool_route_text
        async with self._pool_route_fetch_lock:
            now = monotonic()
            if (
                not force_refresh
                and self._pool_route_text is not None
                and now - self._pool_route_cached_at < SETTINGS_CACHE_INTERVAL
            ):
                return self._pool_route_text
            text = await self._request_text_with_reauth(
                "GET", f"/pool/{self.pool_id}.data"
            )
            self._pool_route_text = text
            self._pool_route_decoded = None
            self._pool_route_cached_at = now
            return text

    async def _get_pool_route_decoded(self, *, force_refresh: bool = False) -> Any:
        text = await self._get_pool_route_text(force_refresh=force_refresh)
        if self._pool_route_decoded is None:
            async with self._pool_route_decode_lock:
                if self._pool_route_decoded is None:
                    decoded = await asyncio.to_thread(_decode_route_response, text)
                    if decoded is None:
                        raise SmartPoolConnectError(
                            "SmartPoolConnect returned malformed pool route data"
                        )
                    self._pool_route_decoded = decoded
        return self._pool_route_decoded

    async def _get_v3_lighting_route_settings(self) -> PoolLightingSettings:
        """Read current V3 lighting settings from the dedicated portal route."""

        text = await self._request_text_with_reauth(
            "GET",
            f"/pool/{self.pool_id}/lighting.data?{LIGHTING_ROUTE_QUERY}",
        )
        decoded = await asyncio.to_thread(_decode_route_response, text)
        if decoded is None:
            return PoolLightingSettings(source="v3")
        return _extract_v3_lighting_settings(decoded)

    def restore_last_backwash(self, value: str | None) -> None:
        """Restore the persistent backwash cache maintained by the coordinator."""

        restored = _as_utc_datetime(value)
        if restored is None:
            return
        self._historical_status.last_backwash_at = restored
        self._historical_backfill_complete = True

    def _merge_historical_status(self, update: PoolHistoricalStatus) -> None:
        """Merge non-null historical values while preserving the last good cache."""

        if update.ambient_temperature is not None:
            self._historical_status.ambient_temperature = update.ambient_temperature
        if update.system_temperature_imx is not None:
            self._historical_status.system_temperature_imx = (
                update.system_temperature_imx
            )
        if update.system_temperature_main is not None:
            self._historical_status.system_temperature_main = (
                update.system_temperature_main
            )
        if update.last_backwash_at is not None and (
            self._historical_status.last_backwash_at is None
            or update.last_backwash_at > self._historical_status.last_backwash_at
        ):
            self._historical_status.last_backwash_at = update.last_backwash_at

    async def async_get_historical_status(
        self, *, force_refresh: bool = False
    ) -> PoolHistoricalStatus:
        """Read low-frequency historical values without affecting live telemetry."""

        now = monotonic()
        if (
            not force_refresh
            and self._historical_cached_at
            and now - self._historical_cached_at < HISTORICAL_CACHE_INTERVAL
        ):
            return self._historical_status

        async with self._historical_lock:
            now = monotonic()
            if (
                not force_refresh
                and self._historical_cached_at
                and now - self._historical_cached_at < HISTORICAL_CACHE_INTERVAL
            ):
                return self._historical_status

            current_path = (
                f"/pool/{self.pool_id}/historical.data?{HISTORICAL_ROUTE_QUERY}"
            )
            try:
                current_text = await self._request_text_with_reauth(
                    "GET", current_path
                )
                current = await asyncio.to_thread(
                    _extract_historical_status, current_text
                )
            except SmartPoolConnectError:
                _LOGGER.debug(
                    "Could not refresh SmartPoolConnect historical data; keeping cache",
                    exc_info=True,
                )
                return self._historical_status

            self._merge_historical_status(current)

            # The current week has no page parameter. Only a missing cached date
            # triggers a bounded backwards scan: page=1 is one week ago, etc.
            if (
                self._historical_status.last_backwash_at is None
                and not self._historical_backfill_complete
            ):
                for page in range(1, HISTORICAL_BACKFILL_WEEKS + 1):
                    path = (
                        f"/pool/{self.pool_id}/historical.data?range=week"
                        f"&interval=1h&page={page}&{HISTORICAL_ROUTE_QUERY}"
                    )
                    try:
                        older_text = await self._request_text_with_reauth("GET", path)
                        older = await asyncio.to_thread(
                            _extract_historical_status, older_text
                        )
                    except SmartPoolConnectError:
                        _LOGGER.debug(
                            "Historical backwash scan stopped at week page %s", page,
                            exc_info=True,
                        )
                        break
                    if older.last_backwash_at is not None:
                        self._merge_historical_status(
                            PoolHistoricalStatus(
                                last_backwash_at=older.last_backwash_at
                            )
                        )
                        break
                self._historical_backfill_complete = True

            self._historical_cached_at = now
            return self._historical_status

    async def _get_current_from_pool_data(
        self,
    ) -> tuple[
        str | None,
        float | None,
        float | None,
        str | None,
    ]:
        generation = self._current_pool_data_generation
        async with self._current_pool_data_lock:
            if generation != self._current_pool_data_generation:
                return self._current_pool_data
            try:
                text = await self._request_text("GET", "/pool.data")
                update = await asyncio.to_thread(
                    _extract_current_from_pool_data, text, self.pool_id
                )
                self._current_pool_data = tuple(
                    new if new is not None else old
                    for new, old in zip(update, self._current_pool_data, strict=True)
                )
            except SmartPoolConnectError:
                _LOGGER.debug("Could not read /pool.data; keeping cache", exc_info=True)
            except Exception:
                _LOGGER.debug("Could not parse /pool.data; keeping cache", exc_info=True)
            finally:
                self._current_pool_data_generation += 1
            return self._current_pool_data

    async def _get_ph_page_flow_status(self) -> str | None:
        """Read the current pH flow badge from the full server-rendered page."""

        generation = self._ph_page_flow_generation
        async with self._ph_page_flow_lock:
            if generation != self._ph_page_flow_generation:
                return self._ph_page_flow_status
            try:
                document = await self._request_text_with_reauth(
                    "GET", f"/pool/{self.pool_id}/ph"
                )
                update = await asyncio.to_thread(
                    _extract_ph_page_flow_status, document
                )
                # A successful authenticated module page proves capability even
                # when its first rendered live badge is temporarily absent.
                self._ph_page_flow_detected = True
                if update is not None:
                    self._ph_page_flow_status = update
            except SmartPoolConnectError:
                _LOGGER.debug(
                    "Could not read the full pH page document; keeping cache",
                    exc_info=True,
                )
            except Exception:
                _LOGGER.debug(
                    "Could not parse the full pH page document; keeping cache",
                    exc_info=True,
                )
            finally:
                self._ph_page_flow_generation += 1
            return self._ph_page_flow_status

    async def _get_cl_page_flow_status(self) -> str | None:
        """Read the current Cl flow badge from the full server-rendered page."""

        generation = self._cl_page_flow_generation
        async with self._cl_page_flow_lock:
            if generation != self._cl_page_flow_generation:
                return self._cl_page_flow_status
            try:
                document = await self._request_text_with_reauth(
                    "GET", f"/pool/{self.pool_id}/cl"
                )
                update = await asyncio.to_thread(
                    _extract_cl_page_flow_status, document
                )
                self._cl_page_flow_detected = True
                if update is not None:
                    self._cl_page_flow_status = update
            except SmartPoolConnectError:
                _LOGGER.debug(
                    "Could not read the full Cl page document; keeping cache",
                    exc_info=True,
                )
            except Exception:
                _LOGGER.debug(
                    "Could not parse the full Cl page document; keeping cache",
                    exc_info=True,
                )
            finally:
                self._cl_page_flow_generation += 1
            return self._cl_page_flow_status

    async def async_get_ph_settings(self, *, force_refresh: bool = False) -> PoolPhSettings:
        try:
            legacy = _extract_devalue_ph_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
            if legacy.valid:
                return legacy
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read pH settings from pool route data", exc_info=True)
            legacy = PoolPhSettings()
        v3 = _extract_v3_ph_settings(
            await self._get_admin_config(
                "dosing_config", force_refresh=force_refresh
            )
        )
        return v3 if v3.detected else legacy

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
            legacy = _extract_devalue_rx_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
            if legacy.valid:
                return legacy
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read Rx settings from pool route data", exc_info=True)
            legacy = PoolRxSettings()
        v3 = _extract_v3_rx_settings(
            await self._get_admin_config(
                "dosing_config", force_refresh=force_refresh
            )
        )
        return v3 if v3.detected else legacy

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

    async def async_set_ph_target(self, target: float) -> None:
        """Set pH target through the v3 contract, with legacy fallback."""

        dosing_data = await self._get_admin_config(
            "dosing_config", force_refresh=True
        )
        config = _find_config_with_keys(dosing_data, {"ph_setpoint"})
        if config is not None and "ph_setpoint" in config:
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/dosing_config",
                json={"ph_setpoint": target},
                headers={"Content-Type": "application/json"},
            )
            self._invalidate_settings_cache()
            return
        await self.async_set_ph_settings(target=target)

    async def async_set_rx_target(self, target: float) -> None:
        """Set Rx/ORP target through ``cl_setpoint`` on v3 controllers."""

        dosing_data = await self._get_admin_config(
            "dosing_config", force_refresh=True
        )
        config = _find_config_with_keys(dosing_data, {"cl_setpoint"})
        if config is not None and "cl_setpoint" in config:
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/dosing_config",
                json={"cl_setpoint": int(round(target))},
                headers={"Content-Type": "application/json"},
            )
            self._invalidate_settings_cache()
            return
        await self.async_set_rx_settings(target=target)

    async def async_get_lighting_settings(self, *, force_refresh: bool = False) -> PoolLightingSettings:
        try:
            legacy = _extract_devalue_lighting_settings(
                await self._get_pool_route_decoded(force_refresh=force_refresh),
                self.pool_id,
            )
            if legacy.valid:
                return legacy
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read lighting settings from pool route data", exc_info=True)
            legacy = PoolLightingSettings()

        v3 = _extract_v3_lighting_settings(
            await self._get_admin_config(
                "lighting_config", force_refresh=force_refresh
            )
        )
        return v3 if v3.detected else legacy

    async def _async_set_v3_lighting_settings(
        self,
        *,
        always_active: bool | None = None,
        cover_disabled: bool | None = None,
        internal_cover_disabled: bool | None = None,
        schedule_enabled: bool | None = None,
        schedule_start_time: str | None = None,
        schedule_stop_time: str | None = None,
        schedule_days: tuple[str, ...] | None = None,
    ) -> bool:
        """Patch only requested V3 lighting fields after field-local validation.

        Physical-light and cover-option writes require only a fresh, reliable
        ``enabled`` mask. Schedule writes independently require only the current
        schedule field(s) they modify. No virtual mask or full-config validity
        is used, and every unrequested field is preserved by omission.

        Return ``False`` only when the V3 endpoint is absent on a controller not
        already known as V3, allowing the unchanged legacy full-form path.
        """

        mask_requested = any(
            requested is not None
            for requested in (
                always_active,
                cover_disabled,
                internal_cover_disabled,
            )
        )
        data = await self._get_admin_config(
            "lighting_config", force_refresh=True
        )
        if data is None:
            if "lighting_v3" in getattr(
                self, "_last_capabilities", frozenset()
            ):
                message = (
                    "Lighting update aborted because the current enabled bitmask is unavailable"
                    if mask_requested
                    else "Lighting update aborted because the current V3 settings are unavailable"
                )
                raise SmartPoolConnectError(message)
            return False

        config = _find_config_with_keys(
            data,
            {
                "enabled",
                "s1_enabled",
                "s1_hour_start",
                "s1_min_start",
                "s1_hour_stop",
                "s1_min_stop",
                "s1_days",
            },
        )
        if config is None:
            message = (
                "Lighting update aborted because the current enabled bitmask is unavailable"
                if mask_requested
                else "Lighting update aborted because the requested V3 settings are unavailable"
            )
            raise SmartPoolConnectError(message)

        payload: dict[str, Any] = {}
        if mask_requested:
            enabled = _as_int(config.get("enabled"))
            if enabled is None or enabled < 0:
                raise SmartPoolConnectError(
                    "Lighting update aborted because the current enabled bitmask is unavailable"
                )
            for requested, bit in (
                (always_active, LIGHTING_ON_BIT),
                (cover_disabled, LIGHTING_EXTERNAL_COVER_BIT),
                (internal_cover_disabled, LIGHTING_INTERNAL_COVER_BIT),
            ):
                if requested is True:
                    enabled |= bit
                elif requested is False:
                    enabled &= ~bit
            payload["enabled"] = enabled

        if schedule_enabled is not None:
            if _as_bool(config.get("s1_enabled")) is None:
                raise SmartPoolConnectError(
                    "Lighting update aborted because s1_enabled is unavailable"
                )
            payload["s1_enabled"] = schedule_enabled

        if schedule_start_time is not None:
            current_hour = _as_int(config.get("s1_hour_start"))
            current_minute = _as_int(config.get("s1_min_start"))
            if (
                current_hour is None
                or current_minute is None
                or not 0 <= current_hour <= 23
                or not 0 <= current_minute <= 59
            ):
                raise SmartPoolConnectError(
                    "Lighting update aborted because the current schedule start time is unavailable"
                )
            if _valid_time(schedule_start_time) is None:
                raise SmartPoolConnectError(
                    "Lighting update aborted because the schedule start time is invalid"
                )
            start_hour, start_minute = (
                int(part) for part in schedule_start_time.split(":")
            )
            payload["s1_hour_start"] = start_hour
            payload["s1_min_start"] = start_minute

        if schedule_stop_time is not None:
            current_hour = _as_int(config.get("s1_hour_stop"))
            current_minute = _as_int(config.get("s1_min_stop"))
            if (
                current_hour is None
                or current_minute is None
                or not 0 <= current_hour <= 23
                or not 0 <= current_minute <= 59
            ):
                raise SmartPoolConnectError(
                    "Lighting update aborted because the current schedule stop time is unavailable"
                )
            if _valid_time(schedule_stop_time) is None:
                raise SmartPoolConnectError(
                    "Lighting update aborted because the schedule stop time is invalid"
                )
            stop_hour, stop_minute = (
                int(part) for part in schedule_stop_time.split(":")
            )
            payload["s1_hour_stop"] = stop_hour
            payload["s1_min_stop"] = stop_minute

        if schedule_days is not None:
            if _days_from_mask(config.get("s1_days")) is None:
                raise SmartPoolConnectError(
                    "Lighting update aborted because s1_days is unavailable"
                )
            if any(day not in DAYS for day in schedule_days):
                raise SmartPoolConnectError(
                    "Lighting schedule contains an invalid weekday"
                )
            payload["s1_days"] = _days_to_mask(schedule_days)

        if not payload:
            return True
        await self._request_json(
            "PATCH",
            f"/api/admin-settings/{self.pool_id}/lighting_config",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        self._invalidate_settings_cache()
        return True

    async def async_set_lighting_settings(
        self,
        *,
        always_active: bool | None = None,
        cover_disabled: bool | None = None,
        internal_cover_disabled: bool | None = None,
        schedule_enabled: bool | None = None,
        schedule_start_time: str | None = None,
        schedule_stop_time: str | None = None,
        schedule_days: tuple[str, ...] | None = None,
    ) -> None:
        if await self._async_set_v3_lighting_settings(
            always_active=always_active,
            cover_disabled=cover_disabled,
            internal_cover_disabled=internal_cover_disabled,
            schedule_enabled=schedule_enabled,
            schedule_start_time=schedule_start_time,
            schedule_stop_time=schedule_stop_time,
            schedule_days=schedule_days,
        ):
            return

        current = await self.async_get_lighting_settings(force_refresh=True)
        if not current.valid:
            raise SmartPoolConnectError(
                "Lighting settings update aborted because the current controller settings could not be read completely"
            )

        if current.source == "v3":
            if current.enabled_mask is None:
                raise SmartPoolConnectError(
                    "Lighting update aborted because the current enabled bitmask is unavailable"
                )
            enabled = current.enabled_mask
            if always_active is True:
                enabled |= LIGHTING_ON_BIT
            elif always_active is False:
                enabled &= ~LIGHTING_ON_BIT
            for requested, bit in (
                (cover_disabled, LIGHTING_EXTERNAL_COVER_BIT),
                (internal_cover_disabled, LIGHTING_INTERNAL_COVER_BIT),
            ):
                if requested is True:
                    enabled |= bit
                elif requested is False:
                    enabled &= ~bit

            days = current.schedule_days if schedule_days is None else schedule_days
            if any(day not in DAYS for day in days):
                raise SmartPoolConnectError("Lighting schedule contains an invalid weekday")

            payload: dict[str, Any] = {}
            if (
                always_active is not None
                or cover_disabled is not None
                or internal_cover_disabled is not None
            ):
                payload["enabled"] = enabled
            if schedule_enabled is not None:
                # Confirmed independent weekly-schedule enable write.  Do not
                # clear or rewrite s1_days when this switch is turned off.
                payload["s1_enabled"] = schedule_enabled
            if schedule_start_time is not None:
                if _valid_time(schedule_start_time) is None:
                    raise SmartPoolConnectError(
                        "Lighting update aborted because the schedule start time is invalid"
                    )
                start_hour, start_minute = (
                    int(part) for part in schedule_start_time.split(":")
                )
                payload["s1_hour_start"] = start_hour
                payload["s1_min_start"] = start_minute
            if schedule_stop_time is not None:
                if _valid_time(schedule_stop_time) is None:
                    raise SmartPoolConnectError(
                        "Lighting update aborted because the schedule stop time is invalid"
                    )
                stop_hour, stop_minute = (
                    int(part) for part in schedule_stop_time.split(":")
                )
                payload["s1_hour_stop"] = stop_hour
                payload["s1_min_stop"] = stop_minute
            if schedule_days is not None:
                payload["s1_days"] = _days_to_mask(days)
            if not payload:
                return
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/lighting_config",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            self._invalidate_settings_cache()
            return

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

    async def async_start_cl_shock(self) -> None:
        """Request Cl shock treatment without changing the filter pump state."""

        await self._request_json(
            "POST",
            f"/pool/{self.pool_id}/cmd.data",
            data={"exec": "shock_start"},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )

    async def async_stop_cl_shock(self) -> None:
        """Stop a running or pump-waiting Cl shock treatment."""

        await self._request_json(
            "POST",
            f"/pool/{self.pool_id}/cmd.data",
            data={"exec": "shock_stop"},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )

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
        (
            pool_name,
            portal_ph,
            portal_rx,
            portal_cl_shock_status,
        ) = await self._get_current_from_pool_data()
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

        # The decoded pool route is also the generic source for firmware
        # diagnostics and the final Covco fallback. It is cached with the other
        # settings reads, so this does not add a request to each polling cycle.
        try:
            pool_route = await self._get_pool_route_decoded()
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read pool route diagnostics", exc_info=True)
            pool_route = None
        system_details = _extract_system_details(pool_route, self.pool_id)
        route_api_version = _extract_api_version(pool_route, self.pool_id)
        if route_api_version is not None:
            self._pool_route_api_version = route_api_version
        api_version = self._pool_route_api_version
        historical = await self.async_get_historical_status()
        ph_dosing_flow_status = await self._get_ph_page_flow_status()
        cl_dosing_flow_status = await self._get_cl_page_flow_status()
        v3_flow = _v3_flow_telemetry(v3)
        v3_diagnostics = _v3_diagnostics(v3)
        current_v3_diagnostic_capabilities = _v3_diagnostic_capabilities(
            v3_flow, v3_diagnostics
        )
        dosing_config = (
            await self._get_admin_config("dosing_config") if v3 is not None else None
        )
        ph_mode_flow, cl_mode_flow = _extract_v3_flow_modes(dosing_config)

        # The paddle is authoritative only for channels whose mode explicitly
        # enables it. If the live paddle is temporarily missing, the confirmed
        # V3 no-flow status codes remain a safe one-way fallback.
        paddle = v3_flow["paddle"]
        for mode, control, channel in (
            (ph_mode_flow, v3_flow["ph_control"], "ph"),
            (cl_mode_flow, v3_flow["cl_control"], "cl"),
        ):
            native_status = _v3_channel_flow_status(mode, paddle, control)
            if native_status is None:
                continue
            if channel == "ph":
                ph_dosing_flow_status = native_status
            else:
                cl_dosing_flow_status = native_status
        cl_shock_status = (
            _cl_shock_state(live)
            or _cl_shock_state(v3)
            or _cl_shock_state(pool_route)
            or portal_cl_shock_status
        )

        capabilities = {
            name
            for name, settings in (
                ("ph", ph_settings),
                ("rx", rx_settings),
                ("lighting", lighting_settings),
                ("filter", filter_settings),
                ("backwash", backwash_settings),
            )
            if settings.detected
        }
        # Eco Valve route payloads can contain an empty/default configuration
        # even when no physical valve is installed.  Only a complete, writable
        # contract proves the capability and may create setting entities.
        if eco_valve_settings.valid:
            capabilities.add("eco_valve")
        # Settings entities can write to physical equipment. Expose those
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
        if historical.available:
            capabilities.add("historical_data")
        if rx_settings.detected or cl_shock_status is not None:
            capabilities.add("cl_shock")
        if self._ph_page_flow_detected and ph_settings.detected:
            capabilities.add("ph_dosing_flow")
        if self._cl_page_flow_detected and rx_settings.detected:
            capabilities.add("cl_dosing_flow")
        if ph_mode_flow is not None and ph_mode_flow & 0x01:
            capabilities.add("ph_dosing_flow")
        if cl_mode_flow is not None and cl_mode_flow & 0x01:
            capabilities.add("cl_dosing_flow")
        capabilities.update(current_v3_diagnostic_capabilities)

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
        covco_detected, covco_position, covco_state = _covco_telemetry_with_fallback(
            live,
            v3,
            pool_route,
        )
        phnix_valid, phnix = _phnix_telemetry_with_fallback(v3, live)
        v3_pump_status, v3_pump_speed = _v3_filter_telemetry(v3)
        v3_lighting = _v3_lighting_state(v3)
        backwash_runtime_detected = any(
            _backwash_runtime_capability(source)
            for source in (v3, live, pool_route)
        )
        lighting_runtime_detected = any(
            _lighting_runtime_capability(source)
            for source in (v3, live, pool_route)
        )

        if standard_cover_state is not None:
            capabilities.add("cover_status")
        if covco_detected:
            capabilities.add("covco_cover")
        if cover_settings.valid or covco_detected:
            capabilities.add("cover_control")
        if phnix_valid:
            capabilities.add("phnix_heat_pump")
        if backwash_runtime_detected:
            capabilities.add("backwash")
        if lighting_runtime_detected:
            capabilities.add("lighting")
        if lighting_settings.source == "v3":
            capabilities.add("lighting_v3")
        if lighting_runtime_detected:
            capabilities.add("v3_lighting")

        raw_dosing_durations = (
            ph_settings.dosing_time,
            ph_settings.pausing_time,
            rx_settings.dosing_time,
            rx_settings.pausing_time,
        )
        dosing_timings_ms = any(
            value is not None and abs(value) >= 1000
            for value in raw_dosing_durations
        )
        if dosing_timings_ms:
            capabilities.add("dosing_timing_ms")

        # Hardware capabilities do not disappear because one later refresh has
        # a temporary null runtime value. Keep everything once proven by a
        # module-specific contract.
        capabilities.update(
            self._last_capabilities - V3_ONLY_DIAGNOSTIC_CAPABILITIES
        )
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
            else v3_pump_status
        )
        pump_speed = live_pump_speed or v3_pump_speed

        live_lighting = _find_key(live, {"lighting"}) if live is not None else None
        lighting_on = (
            v3_lighting
            if v3_lighting is not None
            else (live_lighting not in (None, -1, 0))
            if live_lighting is not None
            else lighting_settings.always_active
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
            mac_address=system_details["mac_address"],
            online=True,
            ph=ph,
            ph_target=(
                ph_settings.target
                if ph_settings.target is not None
                else _as_float(_find_key(pool, {"ph_target", "target_ph"}))
            ),
            ph_dosing_time=(
                _normalise_v3_duration(ph_settings.dosing_time)
                if dosing_timings_ms
                else ph_settings.dosing_time
            ),
            ph_pausing_time=(
                _normalise_v3_duration(ph_settings.pausing_time)
                if dosing_timings_ms
                else ph_settings.pausing_time
            ),
            rx=rx,
            rx_target=(
                rx_settings.target
                if rx_settings.target is not None
                else _as_float(
                    _find_key(pool, {"rx_target", "target_rx", "orp_target"})
                )
            ),
            rx_dosing_time=(
                _normalise_v3_duration(rx_settings.dosing_time)
                if dosing_timings_ms
                else rx_settings.dosing_time
            ),
            rx_pausing_time=(
                _normalise_v3_duration(rx_settings.pausing_time)
                if dosing_timings_ms
                else rx_settings.pausing_time
            ),
            cl_shock_status=cl_shock_status,
            ph_dosing_flow_status=ph_dosing_flow_status,
            cl_dosing_flow_status=cl_dosing_flow_status,
            v3_flow_paddle_status=(
                "flow_ok"
                if paddle is True
                else "no_flow"
                if paddle is False
                else None
            ),
            v3_ph_control=v3_flow["ph_control"],
            v3_cl_control=v3_flow["cl_control"],
            carrier_version=v3_flow["carrier_version"],
            filter_modbus_power=v3_diagnostics["filter_modbus_power"],
            filter_modbus_status=v3_diagnostics["filter_modbus_status"],
            filter_pump_error=v3_diagnostics["filter_pump_error"],
            filter_pump_error_code=v3_diagnostics["filter_pump_error_code"],
            ph_input_error=v3_diagnostics["ph_input_error"],
            rx_input_error=v3_diagnostics["rx_input_error"],
            tds_pollution=v3_diagnostics["tds_pollution"],
            tds_salt=v3_diagnostics["tds_salt"],
            lighting_on=lighting_on,
            lighting_always_active=lighting_settings.always_active,
            lighting_cover_disabled=lighting_settings.cover_disabled,
            lighting_internal_cover_disabled=lighting_settings.internal_cover_disabled,
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
                        {
                            "water_temperature_target",
                            "temperature_target",
                            "setpoint",
                        },
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
            gui_version=system_details["gui_version"],
            main_version=system_details["main_version"],
            io_version=system_details["io_version"],
            deck_version=system_details["deck_version"],
            api_version=api_version,
            ambient_temperature=historical.ambient_temperature,
            system_temperature_imx=historical.system_temperature_imx,
            system_temperature_main=historical.system_temperature_main,
            last_backwash_at=historical.last_backwash_at,
            capabilities=frozen_capabilities,
            raw_live_status=live,
            raw_v3_status=v3,
            raw_pool_status=pool,
        )

    async def async_set_lighting(self, on: bool) -> None:
        """Set physical lighting through the V3 mask or unchanged legacy path."""

        if {
            "v3_lighting",
            "lighting_v3",
        }.intersection(self._last_capabilities):
            current = await self._get_v3_lighting_route_settings()
            enabled = current.enabled_mask
            if enabled is None or enabled < 0:
                raise SmartPoolConnectError(
                    "Lighting update aborted because the current enabled bitmask is unavailable"
                )
            updated = (
                enabled | LIGHTING_ON_BIT
                if on
                else enabled & ~LIGHTING_ON_BIT
            )
            await self._request_json(
                "PATCH",
                f"/api/admin-settings/{self.pool_id}/lighting_config",
                json={"enabled": updated},
                headers={"Content-Type": "application/json"},
            )
            self._invalidate_settings_cache()
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
