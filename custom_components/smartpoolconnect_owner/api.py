"""Async client for SmartPoolConnect owner portal."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
import re
import secrets
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .const import DEFAULT_BASE_URL, DEFAULT_OAUTH_BASE_URL, PUMP_SPEEDS, SETTINGS_CACHE_INTERVAL

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
    """Authentication failed."""

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
    valid: bool = False


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
    raw_live_status: dict[str, Any] | None = None
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
    valid: bool = False


@dataclass(slots=True)
class PoolRxSettings:
    target: float | None = None
    dosing_time: float | None = None
    pausing_time: float | None = None
    overdose_alert: str | None = None
    min_water_temp: str | None = None
    probe: str | None = None
    offset: str | None = None
    valid: bool = False


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
    valid: bool = False


@dataclass(slots=True)
class PoolCoverSettings:
    """Cover/deck configuration."""
    protection: bool | None = None
    pump_open: bool | None = None
    pump_close: bool | None = None
    pump_low_speed: bool | None = None
    longitude: str | None = None
    latitude: str | None = None
    valid: bool = False


@dataclass(slots=True)
class PoolBackwashSettings:
    interval: float | None = None
    rinse_duration: float | None = None
    backwash_duration: float | None = None
    pump_speed: str | None = None
    start_date: str | None = None
    start_time: str | None = None
    valid: bool = False


@dataclass(slots=True)
class PoolEcoValveSettings:
    regulation: str | None = None
    start_time: str | None = None
    stop_time: str | None = None
    valid: bool = False


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    return PUMP_SPEEDS.get(numeric, {0: "off", 1: "low", 2: "medium", 3: "high", 4: "maximum"}.get(numeric))


def _cover_state(value: Any) -> str | None:
    return {1: "open", 2: "closed", 3: "opening", 4: "closing", "open": "open", "closed": "closed", "opening": "opening", "closing": "closing"}.get(value)


def _extract_current_from_pool_data(text: str, pool_id: str) -> tuple[str | None, float | None, float | None]:
    idx = text.find(pool_id)
    if idx == -1:
        _LOGGER.warning("POOL DATA: pool_id not found: %s", pool_id)
        return None, None, None
    context = text[max(0, idx - 1000):idx + 5000]
    try:
        name_match = re.search(rf'"{re.escape(pool_id)}","([^"]+)"', context)
        ph_match = re.search(
            r'"metrics",\{[^{}]*\},"timestamp",[0-9]+,(-?[0-9]+(?:\.[0-9]+)?)',
            context,
        )
        rx_match = re.search(r'"cl".*?},([0-9]+(?:\.[0-9]+)?),', context, re.DOTALL)
        name = name_match.group(1) if name_match else None
        ph = _as_float(ph_match.group(1)) if ph_match else None
        global _LAST_VALID_RX
        rx = _as_float(rx_match.group(1)) if rx_match else None
        if rx is not None:
            if rx < RX_MIN_VALID or rx > RX_MAX_VALID:
                _LOGGER.debug("Ignoring invalid Rx value %s, using previous valid value %s", rx, _LAST_VALID_RX)
                rx = _LAST_VALID_RX
            elif _LAST_VALID_RX is not None and abs(rx - _LAST_VALID_RX) > RX_MAX_DELTA:
                _LOGGER.debug("Ignoring Rx spike %s -> %s, using previous valid value", _LAST_VALID_RX, rx)
                rx = _LAST_VALID_RX
            else:
                _LAST_VALID_RX = rx
        return name, round(ph, 2) if ph is not None else None, round(rx, 0) if rx is not None else None
    except Exception:
        _LOGGER.exception("Failed to extract pH/Rx from /pool.data")
        return None, None, None


def _extract_input_tag(text: str, name: str) -> str | None:
    match = re.search(rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*>', text)
    return match.group(0) if match else None


def _extract_input_value(text: str, name: str) -> str | None:
    tag = _extract_input_tag(text, name)
    if not tag:
        return None
    match = re.search(r'\bvalue="([^"]*)"', tag)
    return match.group(1) if match else None


def _extract_bool_input(text: str, name: str) -> bool | None:
    tag = _extract_input_tag(text, name)
    if not tag:
        return None
    return "checked" in tag.lower()


def _parse_days(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(day.strip().lower() for day in value.split(",") if day.strip())


def _extract_toggle_days(text: str, name: str) -> tuple[str, ...]:
    idx = text.find(f'name="{name}"')
    if idx == -1:
        return _parse_days(_extract_input_value(text, name))
    segment = text[idx:idx + 12000]
    day_map = {"Mon": "monday", "Tue": "tuesday", "Wed": "wednesday", "Thu": "thursday", "Fri": "friday", "Sat": "saturday", "Sun": "sunday"}
    selected: list[str] = []
    for match in re.finditer(r"<button\b([^>]*)>(.*?)</button>", segment, re.DOTALL):
        attrs = match.group(1)
        label = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if ("aria-pressed=\"true\"" in attrs or "data-state=\"on\"" in attrs) and label in day_map:
            selected.append(day_map[label])
    return tuple(selected)


def _extract_schedule_days(text: str) -> tuple[str, ...]:
    return _extract_toggle_days(text, "schedule.days")


def _extract_select_value(text: str, name: str) -> str | None:
    idx = text.find(f'name="{name}"')
    if idx == -1:
        return None
    segment = text[idx:idx + 5000]
    selected = re.search(r'<option\b[^>]*\bselected(?:="[^"]*")?[^>]*\bvalue="([^"]+)"', segment)
    if selected:
        return selected.group(1)
    selected = re.search(r'<option\b[^>]*\bvalue="([^"]+)"[^>]*\bselected', segment)
    if selected:
        return selected.group(1)
    return _extract_input_value(text, name)


def _extract_remix_scalar(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}",("[^"]*"|[0-9]+(?:\.[0-9]+)?|true|false)', text)
    if not match:
        return None
    value = match.group(1)
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _extract_any_bool(text: str, *keys: str) -> bool | None:
    """Extract a boolean from HTML input, JSON-like Remix data, or JS payload."""
    for key in keys:
        value = _extract_bool_input(text, key)
        if value is not None:
            return value
        value = _as_bool(_extract_remix_scalar(text, key))
        if value is not None:
            return value
        patterns = (
            rf'"{re.escape(key)}"\s*:\s*(true|false|1|0)',
            rf"'{re.escape(key)}'\s*:\s*(true|false|1|0)",
            rf'\b{re.escape(key)}\b\s*:\s*(true|false|1|0)',
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = _as_bool(match.group(1))
                if value is not None:
                    return value
    return None



def _extract_devalue_ph_settings(text: str) -> PoolPhSettings:
    """Extract complete pH controller settings from Remix/devalue route data."""
    try:
        values = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return PoolPhSettings()
    if not isinstance(values, list):
        return PoolPhSettings()
    required = {"type", "gain", "target", "offset", "dosing_time", "pausing_time", "probe_offset", "overdose_alert", "min_water_temp", "hysteresis"}
    def resolve(value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(values):
            return values[value]
        return value
    for item in values:
        if not isinstance(item, dict):
            continue
        decoded: dict[str, Any] = {}
        for raw_key, raw_value in item.items():
            if isinstance(raw_key, str) and raw_key.startswith("_") and raw_key[1:].isdigit():
                key = resolve(int(raw_key[1:]))
                if isinstance(key, str):
                    decoded[key] = resolve(raw_value)
            elif isinstance(raw_key, str):
                decoded[raw_key] = resolve(raw_value)
        if not required.issubset(decoded):
            continue
        if any(isinstance(decoded[key], (dict, list)) for key in required):
            continue
        numeric = {key: _as_float(decoded[key]) for key in required - {"type"}}
        dosing_type = decoded["type"]
        if any(value is None for value in numeric.values()) or not isinstance(dosing_type, str) or not dosing_type:
            continue
        return PoolPhSettings(target=numeric["target"], dosing_time=numeric["dosing_time"], pausing_time=numeric["pausing_time"], dosing_type=dosing_type, gain=str(decoded["gain"]), offset=str(decoded["offset"]), probe_offset=str(decoded["probe_offset"]), overdose_alert=str(decoded["overdose_alert"]), min_water_temp=str(decoded["min_water_temp"]), hysteresis=str(decoded["hysteresis"]), valid=True)
    return PoolPhSettings()

def _extract_devalue_rx_settings(text: str) -> PoolRxSettings:
    """Extract complete Rx controller settings from Remix/devalue route data."""
    try:
        values = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return PoolRxSettings()
    if not isinstance(values, list):
        return PoolRxSettings()

    def resolve(value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(values):
            return values[value]
        return value

    def decode_object(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        decoded: dict[str, Any] = {}
        for raw_key, raw_value in item.items():
            if isinstance(raw_key, str) and raw_key.startswith("_") and raw_key[1:].isdigit():
                key = resolve(int(raw_key[1:]))
                if isinstance(key, str):
                    decoded[key] = resolve(raw_value)
            elif isinstance(raw_key, str):
                decoded[raw_key] = resolve(raw_value)
        return decoded

    required = {"dosing_time", "pausing_time", "overdose_alert", "min_water_temp", "rx"}
    for item in values:
        decoded = decode_object(item)
        if not decoded or not required.issubset(decoded):
            continue
        if any(isinstance(decoded[key], list) for key in required):
            continue

        rx_config = decode_object(decoded["rx"])
        if not rx_config or not {"target", "probe", "offset"}.issubset(rx_config):
            continue

        dosing_time = _as_float(decoded["dosing_time"])
        pausing_time = _as_float(decoded["pausing_time"])
        overdose_alert = _as_float(decoded["overdose_alert"])
        min_water_temp = _as_float(decoded["min_water_temp"])
        target = _as_float(rx_config["target"])
        probe = _as_float(rx_config["probe"])
        offset = _as_float(rx_config["offset"])
        if any(value is None for value in (dosing_time, pausing_time, overdose_alert, min_water_temp, target, probe, offset)):
            continue

        return PoolRxSettings(
            target=target,
            dosing_time=dosing_time,
            pausing_time=pausing_time,
            overdose_alert=str(decoded["overdose_alert"]),
            min_water_temp=str(decoded["min_water_temp"]),
            probe=str(rx_config["probe"]),
            offset=str(rx_config["offset"]),
            valid=True,
        )

    return PoolRxSettings()


def _extract_devalue_lighting_settings(text: str) -> PoolLightingSettings:
    """Extract complete lighting settings from Remix/devalue route data."""
    try:
        values = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return PoolLightingSettings()
    if not isinstance(values, list):
        return PoolLightingSettings()

    def resolve(value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(values):
            return values[value]
        return value

    def decode_object(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        decoded: dict[str, Any] = {}
        for raw_key, raw_value in item.items():
            if isinstance(raw_key, str) and raw_key.startswith("_") and raw_key[1:].isdigit():
                key = resolve(int(raw_key[1:]))
                if isinstance(key, str):
                    decoded[key] = resolve(raw_value)
            elif isinstance(raw_key, str):
                decoded[raw_key] = resolve(raw_value)
        return decoded

    required = {"dimming", "switch_pulse", "cover_disabled", "always_active", "schedule"}
    for item in values:
        decoded = decode_object(item)
        if not decoded or not required.issubset(decoded):
            continue
        dimming = _as_float(decoded["dimming"])
        switch_pulse = _as_float(decoded["switch_pulse"])
        cover_disabled = _as_bool(decoded["cover_disabled"])
        always_active = _as_bool(decoded["always_active"])
        schedule = decode_object(decoded["schedule"])
        if not schedule or not {"start_time", "stop_time", "enabled", "days"}.issubset(schedule):
            continue
        schedule_enabled = _as_bool(schedule["enabled"])
        start_time = schedule["start_time"]
        stop_time = schedule["stop_time"]
        days = schedule["days"]
        if (
            dimming is None or switch_pulse is None
            or cover_disabled is None or always_active is None
            or schedule_enabled is None
            or not isinstance(start_time, str) or not isinstance(stop_time, str)
            or not isinstance(days, list)
        ):
            continue
        return PoolLightingSettings(
            always_active=always_active,
            cover_disabled=cover_disabled,
            schedule_enabled=schedule_enabled,
            schedule_start_time=start_time,
            schedule_stop_time=stop_time,
            schedule_days=tuple(str(day).lower() for day in days),
            dimming=str(decoded["dimming"]),
            switch_pulse=str(decoded["switch_pulse"]),
            valid=True,
        )
    return PoolLightingSettings()

def _extract_devalue_cover_settings(text: str) -> PoolCoverSettings:
    """Extract cover settings from Remix/devalue serialized route data.

    The decoded GET values and the PUT payload use crossed pump fields compared
    to the portal/Home Assistant labels:
      - API pump_close = portal/HA Opening Pump.
      - API pump_open  = portal/HA Closing Pump.
    """
    try:
        values = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return PoolCoverSettings()
    if not isinstance(values, list):
        return PoolCoverSettings()

    def resolve(value: Any) -> Any:
        if isinstance(value, int) and 0 <= value < len(values):
            return values[value]
        return value

    def decode_object(obj: Any) -> dict[str, Any] | None:
        if not isinstance(obj, dict):
            return None
        decoded: dict[str, Any] = {}
        for raw_key, raw_value in obj.items():
            if isinstance(raw_key, str) and raw_key.startswith("_") and raw_key[1:].isdigit():
                key = resolve(int(raw_key[1:]))
                value = resolve(raw_value)
                if isinstance(key, str):
                    decoded[key] = value
            elif isinstance(raw_key, str):
                decoded[raw_key] = resolve(raw_value)
        return decoded

    def from_decoded(decoded: dict[str, Any]) -> PoolCoverSettings:
        return PoolCoverSettings(
            protection=_as_bool(decoded.get("protection")),
            # API pump_close = portal/HA Opening Pump.
            pump_open=_as_bool(decoded.get("pump_close")),
            # API pump_open = portal/HA Closing Pump.
            pump_close=_as_bool(decoded.get("pump_open")),
            pump_low_speed=_as_bool(decoded.get("pump_low_speed")),
            valid=all(_as_bool(decoded.get(key)) is not None for key in required),
        )

    required = {"protection", "pump_open", "pump_close", "pump_low_speed"}
    for item in values:
        decoded = decode_object(item)
        if decoded and required.issubset(decoded):
            return from_decoded(decoded)

    key_indexes: dict[str, int] = {}
    for idx, value in enumerate(values):
        if isinstance(value, str) and value in required:
            key_indexes[value] = idx

    if required.issubset(key_indexes):
        needed_raw_keys = {f"_{idx}" for idx in key_indexes.values()}
        for item in values:
            if not isinstance(item, dict):
                continue
            if not needed_raw_keys.issubset(set(item.keys())):
                continue
            decoded = decode_object(item)
            if decoded and required.issubset(decoded):
                return from_decoded(decoded)
    return PoolCoverSettings()



def _extract_devalue_eco_valve_settings(text: str) -> PoolEcoValveSettings:
    """Extract Eco Valve settings from Remix/devalue serialized route data.

    Example observed in SmartPoolConnect route data:
        {_7089: 888, _1228: 7064, _1230: 7064}
        7089 = "regulation", 888 = "off"
        1228 = "start_time", 1230 = "stop_time", 7064 = "00:00"
    """
    try:
        values = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return PoolEcoValveSettings()

    if not isinstance(values, list):
        return PoolEcoValveSettings()

    def resolve(value: Any) -> Any:
        if isinstance(value, int) and 0 <= value < len(values):
            return values[value]
        return value

    def decode_object(obj: Any) -> dict[str, Any] | None:
        if not isinstance(obj, dict):
            return None
        decoded: dict[str, Any] = {}
        for raw_key, raw_value in obj.items():
            if isinstance(raw_key, str) and raw_key.startswith("_") and raw_key[1:].isdigit():
                key = resolve(int(raw_key[1:]))
                value = resolve(raw_value)
                if isinstance(key, str):
                    decoded[key] = value
            elif isinstance(raw_key, str):
                decoded[raw_key] = resolve(raw_value)
        return decoded

    best: PoolEcoValveSettings | None = None

    for item in values:
        decoded = decode_object(item)
        if not decoded:
            continue

        regulation = decoded.get("regulation")
        start_time = decoded.get("start_time")
        stop_time = decoded.get("stop_time")

        valid_regulation = regulation if regulation in ECO_VALVE_REGULATION_OPTIONS else None
        valid_start_time = start_time if isinstance(start_time, str) and re.match(r"^\d{2}:\d{2}$", start_time) else None
        valid_stop_time = stop_time if isinstance(stop_time, str) and re.match(r"^\d{2}:\d{2}$", stop_time) else None

        if valid_regulation is None and valid_start_time is None and valid_stop_time is None:
            continue

        candidate = PoolEcoValveSettings(
            regulation=valid_regulation,
            start_time=valid_start_time,
            stop_time=valid_stop_time,
            valid=(valid_regulation is not None and valid_start_time is not None and valid_stop_time is not None),
        )

        if candidate.regulation is not None and candidate.start_time is not None and candidate.stop_time is not None:
            return candidate

        if best is None:
            best = candidate

    return best or PoolEcoValveSettings()

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
        self._pool_route_cached_at: float = 0.0
        self._settings_bundle: tuple[Any, ...] | None = None
        self._settings_bundle_cached_at: float = 0.0

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
            if resp.status >= 400:
                raise AuthenticationError(f"OAuth login page failed: HTTP {resp.status}")
        login_data_url = self._to_login_data_url(login_page_url)
        device = base64.b64encode(str(secrets.randbelow(10_000_000_000)).encode()).decode()
        async with self._session.post(login_data_url, data={"email": self.username, "password": self.password, "device": device}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Origin": self.oauth_base_url, "Referer": login_page_url}, allow_redirects=False) as resp:
            login_text = await resp.text()
            login_location = resp.headers.get("Location")
            login_remix_redirect = resp.headers.get("X-Remix-Redirect")
            if resp.status not in (200, 202, 204, 301, 302, 303):
                raise AuthenticationError(f"OAuth login.data failed: HTTP {resp.status}")
        next_url = login_location or login_remix_redirect or self._extract_auth_redirect(login_text) or self._to_auth_data_url(login_page_url)
        if next_url.startswith("/"):
            next_url = urljoin(self.oauth_base_url, next_url)
        await self._follow_auth_redirect(next_url)

    def _to_login_data_url(self, login_page_url: str) -> str:
        if "/oauth/login?" not in login_page_url:
            raise AuthenticationError(f"Unexpected OAuth login URL: {login_page_url}")
        return login_page_url.replace("/oauth/login?", "/oauth/login.data?")

    def _to_auth_data_url(self, login_page_url: str) -> str:
        if "/oauth/login?" not in login_page_url:
            raise AuthenticationError(f"Unexpected OAuth login URL: {login_page_url}")
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
                    raise AuthenticationError("Could not discover OAuth login URL: no redirect location")
                if location.startswith("/"):
                    location = urljoin(current_url, location)
                current_url = location
                if "/oauth/login" in current_url:
                    return current_url
        raise AuthenticationError("Could not discover OAuth login URL after redirects")

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
                            raise AuthenticationError("OAuth flow ended on oauth domain without reaching www auth callback")
                        return
                    raise AuthenticationError(f"OAuth redirect failed: HTTP {resp.status}")
                if next_url.startswith("/"):
                    next_url = urljoin(current_url, next_url)
                current_url = next_url
        raise AuthenticationError("Too many OAuth redirect steps")

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
        """Validate authentication without loading all pool settings."""
        await self._request_json(
            "GET",
            f"/api/live-status/{self.pool_id}",
        )

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

    def _invalidate_settings_cache(self) -> None:
        self._pool_route_text = None
        self._pool_route_cached_at = 0.0
        self._settings_bundle = None
        self._settings_bundle_cached_at = 0.0

    async def _get_pool_route_text(self, *, force_refresh: bool = False) -> str:
        now = monotonic()
        if not force_refresh and self._pool_route_text is not None and now - self._pool_route_cached_at < SETTINGS_CACHE_INTERVAL:
            return self._pool_route_text
        text = await self._request_text_with_reauth("GET", f"/pool/{self.pool_id}.data")
        self._pool_route_text = text
        self._pool_route_cached_at = now
        return text

    async def _get_current_from_pool_data(self) -> tuple[str | None, float | None, float | None]:
        try:
            text = await self._request_text("GET", "/pool.data")
        except SmartPoolConnectError:
            _LOGGER.debug("Could not read /pool.data", exc_info=True)
            return None, None, None
        return _extract_current_from_pool_data(text, self.pool_id)

    async def async_get_ph_settings(self, *, force_refresh: bool = False) -> PoolPhSettings:
        try:
            return _extract_devalue_ph_settings(await self._get_pool_route_text(force_refresh=force_refresh))
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
            return _extract_devalue_rx_settings(await self._get_pool_route_text(force_refresh=force_refresh))
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
            return _extract_devalue_lighting_settings(await self._get_pool_route_text(force_refresh=force_refresh))
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

    async def async_get_filter_settings(self) -> PoolFilterSettings:
        text = await self._request_text_with_reauth("GET", f"/pool/{self.pool_id}/filter")
        settings = PoolFilterSettings(
            always_active=_extract_bool_input(text, "always_active"),
            pump_speed=_extract_select_value(text, "pump_speed"),
            schedule_1=PoolFilterSchedule(enabled=_extract_bool_input(text, "schedule_1.enabled"), pump_speed=_extract_select_value(text, "schedule_1.pump_speed"), start_time=_extract_input_value(text, "schedule_1.start_time"), stop_time=_extract_input_value(text, "schedule_1.stop_time"), days=_extract_toggle_days(text, "schedule_1.days")),
            schedule_2=PoolFilterSchedule(enabled=_extract_bool_input(text, "schedule_2.enabled"), pump_speed=_extract_select_value(text, "schedule_2.pump_speed"), start_time=_extract_input_value(text, "schedule_2.start_time"), stop_time=_extract_input_value(text, "schedule_2.stop_time"), days=_extract_toggle_days(text, "schedule_2.days")),
            schedule_3=PoolFilterSchedule(enabled=_extract_bool_input(text, "schedule_3.enabled"), pump_speed=_extract_select_value(text, "schedule_3.pump_speed"), start_time=_extract_input_value(text, "schedule_3.start_time"), stop_time=_extract_input_value(text, "schedule_3.stop_time"), days=_extract_toggle_days(text, "schedule_3.days")),
        )
        schedules = (settings.schedule_1, settings.schedule_2, settings.schedule_3)
        settings.valid = (
            settings.always_active is not None
            and settings.pump_speed in PUMP_SPEED_OPTIONS
            and all(schedule is not None and schedule.enabled is not None and schedule.pump_speed in PUMP_SPEED_OPTIONS and schedule.start_time is not None and schedule.stop_time is not None for schedule in schedules)
            and all(f'name="schedule_{idx}.days"' in text for idx in (1, 2, 3))
        )
        return settings

    async def async_set_filter_settings(self, settings: PoolFilterSettings) -> None:
        if not settings.valid or not all((settings.schedule_1, settings.schedule_2, settings.schedule_3)):
            raise SmartPoolConnectError("Filter settings update aborted because the current controller settings could not be read completely")
        s1, s2, s3 = settings.schedule_1, settings.schedule_2, settings.schedule_3
        await self._request_json("PUT", f"/pool/{self.pool_id}/filter.data", data={
            "always_active": "true" if settings.always_active else "false",
            "pump_speed": settings.pump_speed,
            "schedule_1.pump_speed": s1.pump_speed, "schedule_1.start_time": s1.start_time, "schedule_1.stop_time": s1.stop_time, "schedule_1.enabled": "true" if s1.enabled else "false", "schedule_1.days": ",".join(s1.days),
            "schedule_2.pump_speed": s2.pump_speed, "schedule_2.start_time": s2.start_time, "schedule_2.stop_time": s2.stop_time, "schedule_2.enabled": "true" if s2.enabled else "false", "schedule_2.days": ",".join(s2.days),
            "schedule_3.pump_speed": s3.pump_speed, "schedule_3.start_time": s3.start_time, "schedule_3.stop_time": s3.stop_time, "schedule_3.enabled": "true" if s3.enabled else "false", "schedule_3.days": ",".join(s3.days),
        }, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_get_backwash_settings(self) -> PoolBackwashSettings:
        text: str | None = None
        last_error: SmartPoolConnectError | None = None
        for path in (f"/pool/{self.pool_id}/filter/backwash", f"/pool/{self.pool_id}/filter/backwash.data"):
            try:
                text = await self._request_text_with_reauth("GET", path)
                break
            except (AuthenticationError, TransientServerError):
                raise
            except SmartPoolConnectError as err:
                last_error = err
        if text is None:
            if last_error is not None:
                raise last_error
            return PoolBackwashSettings()
        interval = _extract_input_value(text, "interval") or _extract_remix_scalar(text, "interval")
        rinse_duration = _extract_input_value(text, "rinse_duration") or _extract_remix_scalar(text, "rinse_duration")
        backwash_duration = _extract_input_value(text, "backwash_duration") or _extract_remix_scalar(text, "backwash_duration")
        pump_speed = _extract_select_value(text, "pump_speed") or _extract_input_value(text, "pump_speed") or _extract_remix_scalar(text, "pump_speed")
        start_date = _extract_input_value(text, "start_date") or _extract_remix_scalar(text, "start_date")
        start_time = _extract_input_value(text, "start_time") or _extract_remix_scalar(text, "start_time")
        settings = PoolBackwashSettings(interval=_as_float(interval), rinse_duration=_as_float(rinse_duration), backwash_duration=_as_float(backwash_duration), pump_speed=pump_speed if pump_speed in BACKWASH_PUMP_SPEED_OPTIONS else None, start_date=_normalize_smartpool_date(start_date), start_time=start_time)
        settings.valid = all(value is not None for value in (settings.interval, settings.rinse_duration, settings.backwash_duration, settings.pump_speed, settings.start_date, settings.start_time))
        return settings

    async def async_set_backwash_settings(self, settings: PoolBackwashSettings) -> None:
        if not settings.valid or any(value is None for value in (settings.interval, settings.rinse_duration, settings.backwash_duration, settings.pump_speed, settings.start_date, settings.start_time)):
            raise SmartPoolConnectError("Backwash settings update aborted because the current controller settings could not be read completely")
        await self._request_json("PUT", f"/pool/{self.pool_id}/filter/backwash.data", data={"interval": str(int(settings.interval)), "rinse_duration": str(int(settings.rinse_duration)), "backwash_duration": str(int(settings.backwash_duration)), "pump_speed": settings.pump_speed, "start_date": _format_smartpool_date(settings.start_date), "start_time": settings.start_time}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_start_backwash(self) -> None:
        await self._request_json("POST", f"/pool/{self.pool_id}/cmd.data", data={"exec": "backwash"}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_get_eco_valve_settings(self) -> PoolEcoValveSettings:
        last_error: SmartPoolConnectError | None = None
        for path in (f"/pool/{self.pool_id}/filter/eco-valve.data", f"/pool/{self.pool_id}/filter/eco-valve", f"/pool/{self.pool_id}/filter.data", f"/pool/{self.pool_id}.data", f"/pool/{self.pool_id}", "/pool.data"):
            try:
                text = await self._request_text_with_reauth("GET", path)
            except (AuthenticationError, TransientServerError):
                raise
            except SmartPoolConnectError as err:
                last_error = err
                continue
            if not text:
                continue
            settings = _extract_devalue_eco_valve_settings(text)
            if settings.valid:
                return settings
            regulation = _extract_select_value(text, "regulation") or _extract_input_value(text, "regulation") or _extract_remix_scalar(text, "regulation")
            start_time = _extract_input_value(text, "start_time") or _extract_remix_scalar(text, "start_time")
            stop_time = _extract_input_value(text, "stop_time") or _extract_remix_scalar(text, "stop_time")
            settings = PoolEcoValveSettings(regulation=regulation if regulation in ECO_VALVE_REGULATION_OPTIONS else None, start_time=start_time, stop_time=stop_time)
            settings.valid = settings.regulation is not None and settings.start_time is not None and settings.stop_time is not None
            if settings.valid:
                return settings
        if last_error is not None:
            raise last_error
        return PoolEcoValveSettings()

    async def async_set_eco_valve_settings(self, settings: PoolEcoValveSettings) -> None:
        if not settings.valid or settings.regulation not in ECO_VALVE_REGULATION_OPTIONS or settings.start_time is None or settings.stop_time is None:
            raise SmartPoolConnectError("Eco Valve settings update aborted because the current controller settings could not be read completely")
        await self._request_json("PUT", f"/pool/{self.pool_id}/filter/eco-valve.data", data={"regulation": settings.regulation, "start_time": settings.start_time, "stop_time": settings.stop_time}, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        self._invalidate_settings_cache()

    async def async_get_cover_settings(self) -> PoolCoverSettings:
        last_error: SmartPoolConnectError | None = None
        for path in (f"/pool/{self.pool_id}/cover.data?_routes=root%2Cpool%2Froutes%2F%24pid.cover", f"/pool/{self.pool_id}/cover.data", f"/pool/{self.pool_id}/cover", f"/pool/{self.pool_id}.data", f"/pool/{self.pool_id}", "/pool.data"):
            try:
                text = await self._request_text_with_reauth("GET", path)
            except (AuthenticationError, TransientServerError):
                raise
            except SmartPoolConnectError as err:
                last_error = err
                continue
            if not text:
                continue
            settings = _extract_devalue_cover_settings(text)
            if settings.valid:
                settings.longitude = _extract_input_value(text, "location.longitude") or _extract_remix_scalar(text, "location.longitude") or _extract_remix_scalar(text, "longitude")
                settings.latitude = _extract_input_value(text, "location.latitude") or _extract_remix_scalar(text, "location.latitude") or _extract_remix_scalar(text, "latitude")
                return settings
            settings = PoolCoverSettings(
                protection=_extract_any_bool(text, "protection", "cover_protection"),
                pump_open=_extract_any_bool(text, "pump_close", "opening_pump"),
                pump_close=_extract_any_bool(text, "pump_open", "closing_pump"),
                pump_low_speed=_extract_any_bool(text, "pump_low_speed", "opening_pump_slow"),
                longitude=_extract_input_value(text, "location.longitude") or _extract_remix_scalar(text, "location.longitude") or _extract_remix_scalar(text, "longitude"),
                latitude=_extract_input_value(text, "location.latitude") or _extract_remix_scalar(text, "location.latitude") or _extract_remix_scalar(text, "latitude"),
            )
            settings.valid = all(value is not None for value in (settings.protection, settings.pump_open, settings.pump_close, settings.pump_low_speed))
            if settings.valid:
                return settings
        if last_error is not None:
            raise last_error
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
            await self.async_get_cover_settings(),
        )
        self._settings_bundle_cached_at = now
        return self._settings_bundle

    async def async_get_status(self) -> PoolStatus:
        live = await self._request_json("GET", f"/api/live-status/{self.pool_id}")
        try:
            pool = await self._request_json("GET", f"/api/pool-status/{self.pool_id}")
        except SmartPoolConnectError:
            pool = {}
        pool_name, ph, rx = await self._get_current_from_pool_data()
        (ph_settings, rx_settings, lighting_settings, filter_settings, backwash_settings, eco_valve_settings, cover_settings) = await self._get_settings_bundle()
        fs1 = filter_settings.schedule_1 or PoolFilterSchedule()
        fs2 = filter_settings.schedule_2 or PoolFilterSchedule()
        fs3 = filter_settings.schedule_3 or PoolFilterSchedule()
        lighting = _find_key(live, {"lighting"})
        heating_active = _find_key(live, {"_heating_pump_active"})
        heating = _find_key(live, {"heating", "heating_on"})
        cover = _find_key(live, {"cover"})
        pump_status = _find_key(live, {"pump_status"})
        pump_speed = _find_key(live, {"pump_speed"})
        water_temperature = _as_float(_find_key(live, {"water_temp", "water_temperature", "temperature"}))
        if water_temperature is None:
            water_temperature = _as_float(_find_key(pool, {"water_temp", "water_temperature", "temperature"}))
        live_pump_speed = _pump_speed(pump_speed)
        return PoolStatus(
            pool_id=self.pool_id, name=pool_name or _find_key(pool, {"name", "pool_name"}), online=True, ph=ph,
            ph_target=ph_settings.target if ph_settings.target is not None else _as_float(_find_key(pool, {"ph_target", "target_ph"})), ph_dosing_time=ph_settings.dosing_time, ph_pausing_time=ph_settings.pausing_time,
            rx=rx, rx_target=rx_settings.target if rx_settings.target is not None else _as_float(_find_key(pool, {"rx_target", "target_rx", "orp_target"})), rx_dosing_time=rx_settings.dosing_time, rx_pausing_time=rx_settings.pausing_time,
            lighting_on=lighting_settings.always_active if lighting_settings.always_active is not None else (lighting not in (None, -1, 0)), lighting_always_active=lighting_settings.always_active, lighting_cover_disabled=lighting_settings.cover_disabled, lighting_schedule_enabled=lighting_settings.schedule_enabled, lighting_schedule_start_time=lighting_settings.schedule_start_time, lighting_schedule_stop_time=lighting_settings.schedule_stop_time, lighting_schedule_days=lighting_settings.schedule_days,
            filter_always_active=filter_settings.always_active, filter_pump_speed=filter_settings.pump_speed or live_pump_speed,
            filter_schedule_1_enabled=fs1.enabled, filter_schedule_1_pump_speed=fs1.pump_speed or "low", filter_schedule_1_start_time=fs1.start_time, filter_schedule_1_stop_time=fs1.stop_time, filter_schedule_1_days=fs1.days,
            filter_schedule_2_enabled=fs2.enabled, filter_schedule_2_pump_speed=fs2.pump_speed or "high", filter_schedule_2_start_time=fs2.start_time, filter_schedule_2_stop_time=fs2.stop_time, filter_schedule_2_days=fs2.days,
            filter_schedule_3_enabled=fs3.enabled, filter_schedule_3_pump_speed=fs3.pump_speed or "low", filter_schedule_3_start_time=fs3.start_time, filter_schedule_3_stop_time=fs3.stop_time, filter_schedule_3_days=fs3.days,
            backwash_interval=backwash_settings.interval, backwash_rinse_duration=backwash_settings.rinse_duration, backwash_duration=backwash_settings.backwash_duration, backwash_pump_speed=backwash_settings.pump_speed, backwash_start_date=backwash_settings.start_date, backwash_start_time=backwash_settings.start_time,
            eco_valve_regulation=eco_valve_settings.regulation, eco_valve_start_time=eco_valve_settings.start_time, eco_valve_stop_time=eco_valve_settings.stop_time,
            water_temperature=water_temperature, water_temperature_target=_as_float(_find_key(pool, {"water_temperature_target", "temperature_target", "setpoint"})), outside_temperature=_as_float(_find_key(pool, {"outside_temp", "outside_temperature"})), solar_temperature=_as_float(_find_key(pool, {"solar_temp", "solar_temperature"})), pump_speed=live_pump_speed, pump_status=bool(pump_status) if pump_status is not None else None, heating_on=(bool(heating_active) if heating_active is not None else (bool(heating) if heating not in (None, -1) else None)), cover_state=_cover_state(cover), cover_protection=cover_settings.protection, cover_pump_open=cover_settings.pump_open, cover_pump_close=cover_settings.pump_close, cover_pump_low_speed=cover_settings.pump_low_speed, raw_live_status=live if isinstance(live, dict) else None, raw_pool_status=pool if isinstance(pool, dict) else None)

    async def async_set_lighting(self, on: bool) -> None:
        await self.async_set_lighting_settings(always_active=on)

    async def async_set_pump_speed(self, speed: str) -> None:
        filter_settings = await self.async_get_filter_settings()
        filter_settings.pump_speed = speed
        await self.async_set_filter_settings(filter_settings)

    async def async_cover_open(self) -> None:
        await self._request_json("POST", f"/api/cmd/{self.pool_id}/cover_open", headers={"Content-Type": "application/json"})

    async def async_cover_close(self) -> None:
        await self._request_json("POST", f"/api/cmd/{self.pool_id}/cover_close", headers={"Content-Type": "application/json"})

    async def async_cover_stop(self) -> None:
        await self._request_json("POST", f"/api/cmd/{self.pool_id}/cover_stop", headers={"Content-Type": "application/json"})
