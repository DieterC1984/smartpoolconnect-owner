"""Decoder for SmartPoolConnect Remix/turbo-stream route responses.

SmartPoolConnect ``*.data`` endpoints return a flattened JSON graph.  Object
keys are usually encoded as ``_<slot>`` and integer container values point at
other slots.  Some responses also append promise chunks (``P<id>:<json>``).
This module expands that representation without depending on installation-
specific slot numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
from typing import Any, Final, Iterator, Mapping, Sequence


class RemixDecodeError(ValueError):
    """The response is not a supported Remix/turbo-stream payload."""


class _Undefined:
    __slots__ = ()

    def __repr__(self) -> str:
        return "undefined"

    def __bool__(self) -> bool:
        return False


UNDEFINED: Final = _Undefined()


@dataclass(frozen=True, slots=True)
class RemixRegExp:
    """JavaScript regular expression preserved by the decoder."""

    pattern: str
    flags: str = ""


@dataclass(frozen=True, slots=True)
class RemixSymbol:
    """JavaScript symbol preserved by the decoder."""

    description: str | None


@dataclass(frozen=True, slots=True)
class RemixError:
    """Serialized JavaScript error preserved as data."""

    name: str
    message: str
    stack: str | None = None


@dataclass(frozen=True, slots=True)
class UnresolvedPromise:
    """Promise marker for a response whose continuation was not captured."""

    promise_id: int


# Sentinels used by turbo-stream 2.x.  The two values present in the supplied
# SmartPoolConnect captures are NULL (-5) and UNDEFINED (-7).  Other special
# numbers are accepted as a defensive compatibility measure.
_SENTINELS: Final[dict[int, Any]] = {
    -1: UNDEFINED,
    -2: math.nan,
    -3: math.inf,
    -4: -math.inf,
    -5: None,
    -6: -0.0,
    -7: UNDEFINED,
}
_KEY_REFERENCE = re.compile(r"^_(\d+)$")
_CHUNK_LINE = re.compile(r"^([A-Z])(\d+):(.*)$", re.DOTALL)
_SKIP = object()
_IN_PROGRESS = object()


@dataclass(frozen=True, slots=True)
class _Chunk:
    kind: str
    chunk_id: int
    start_index: int


class _FlatGraphDecoder:
    def __init__(self, values: list[Any], chunks: Mapping[int, _Chunk]) -> None:
        self._values = values
        self._chunks = chunks
        self._memo: list[Any] = [_SKIP] * len(values)
        self._chunk_cache: dict[int, Any] = {}

    def decode(self) -> Any:
        if not self._values:
            raise RemixDecodeError("The flattened value table is empty")
        return self._hydrate(0)

    def _reference(self, reference: Any) -> Any:
        if isinstance(reference, bool):
            raise RemixDecodeError("Boolean used as a flattened graph reference")
        if not isinstance(reference, int):
            raise RemixDecodeError(f"Invalid flattened graph reference: {reference!r}")
        if reference < 0:
            if reference not in _SENTINELS:
                raise RemixDecodeError(f"Unknown flattened graph sentinel: {reference}")
            return _SENTINELS[reference]
        return self._hydrate(reference)

    def _hydrate(self, index: int) -> Any:
        if index < 0 or index >= len(self._values):
            raise RemixDecodeError(f"Flattened graph reference {index} is out of range")
        cached = self._memo[index]
        if cached is _IN_PROGRESS:
            # Mutable containers are stored in the memo before their children,
            # so this is only reached for an impossible primitive cycle.
            raise RemixDecodeError(f"Invalid cycle through scalar slot {index}")
        if cached is not _SKIP:
            return cached

        raw = self._values[index]
        if isinstance(raw, dict):
            decoded: dict[str, Any] = {}
            self._memo[index] = decoded
            for raw_key, raw_value in raw.items():
                key = self._decode_key(raw_key)
                value = self._reference(raw_value)
                # JavaScript undefined is kept as a value.  Callers that need
                # field-presence semantics can distinguish it from None.
                decoded[key] = value
            return decoded

        if isinstance(raw, list):
            return self._hydrate_list(index, raw)

        # Scalars in the table are literal values, including negative numbers.
        self._memo[index] = raw
        return raw

    def _decode_key(self, raw_key: Any) -> str:
        if not isinstance(raw_key, str):
            raise RemixDecodeError(f"Object key is not a string: {raw_key!r}")
        match = _KEY_REFERENCE.fullmatch(raw_key)
        if not match:
            if raw_key == "__proto__":
                raise RemixDecodeError("Refusing unsafe __proto__ object key")
            return raw_key
        key = self._hydrate(int(match.group(1)))
        if not isinstance(key, str):
            raise RemixDecodeError(f"Decoded object key is not a string: {key!r}")
        if key == "__proto__":
            raise RemixDecodeError("Refusing unsafe __proto__ object key")
        return key

    def _hydrate_list(self, index: int, raw: list[Any]) -> Any:
        tag = raw[0] if raw and isinstance(raw[0], str) else None
        if tag in {
            "P", "Promise", "Date", "D", "BigInt", "n", "RegExp", "R",
            "Symbol", "Y", "URL", "U", "Set", "S", "Map", "M", "Error", "E",
            "Object", "null",
        }:
            self._memo[index] = _IN_PROGRESS
            decoded = self._decode_tagged(tag, raw[1:])
            self._memo[index] = decoded
            return decoded

        decoded_list: list[Any] = []
        self._memo[index] = decoded_list
        for reference in raw:
            decoded_list.append(self._reference(reference))
        return decoded_list

    def _tag_arg(self, args: Sequence[Any], position: int) -> Any:
        if position >= len(args):
            raise RemixDecodeError("Tagged value is missing an argument")
        value = args[position]
        # Protocol tags may carry literal strings/numbers as well as references.
        if isinstance(value, int) and not isinstance(value, bool):
            if value < 0 or value < len(self._values):
                return self._reference(value)
        return value

    def _decode_tagged(self, tag: str, args: Sequence[Any]) -> Any:
        if tag in {"P", "Promise"}:
            if not args or not isinstance(args[0], int):
                raise RemixDecodeError("Promise tag does not contain a numeric id")
            return self._decode_promise(args[0])
        if tag in {"Date", "D"}:
            value = self._tag_arg(args, 0)
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return value
            return value
        if tag in {"BigInt", "n"}:
            return int(str(self._tag_arg(args, 0)))
        if tag in {"RegExp", "R"}:
            pattern = str(self._tag_arg(args, 0))
            flags = str(self._tag_arg(args, 1)) if len(args) > 1 else ""
            return RemixRegExp(pattern, flags)
        if tag in {"Symbol", "Y"}:
            value = self._tag_arg(args, 0) if args else None
            return RemixSymbol(None if value is None else str(value))
        if tag in {"URL", "U"}:
            return str(self._tag_arg(args, 0))
        if tag in {"Set", "S"}:
            return {self._tag_arg(args, i) for i in range(len(args))}
        if tag in {"Map", "M"}:
            if len(args) % 2:
                raise RemixDecodeError("Map tag has an odd number of arguments")
            return {
                self._tag_arg(args, i): self._tag_arg(args, i + 1)
                for i in range(0, len(args), 2)
            }
        if tag in {"Error", "E"}:
            name = str(self._tag_arg(args, 0)) if args else "Error"
            message = str(self._tag_arg(args, 1)) if len(args) > 1 else ""
            stack = str(self._tag_arg(args, 2)) if len(args) > 2 else None
            return RemixError(name, message, stack)
        if tag in {"Object", "null"}:
            if not args:
                return {}
            value = self._tag_arg(args, 0)
            return value if isinstance(value, dict) else {"value": value}
        raise RemixDecodeError(f"Unsupported tagged value: {tag}")

    def _decode_promise(self, promise_id: int) -> Any:
        if promise_id in self._chunk_cache:
            return self._chunk_cache[promise_id]
        chunk = self._chunks.get(promise_id)
        if chunk is None:
            unresolved = UnresolvedPromise(promise_id)
            self._chunk_cache[promise_id] = unresolved
            return unresolved
        if chunk.kind == "E":
            error = RemixError("PromiseRejection", "Serialized promise was rejected")
            self._chunk_cache[promise_id] = error
            return error
        # Continuation slots are appended to the initial flattened table and
        # retain their global reference numbers.
        value = self._hydrate(chunk.start_index)
        self._chunk_cache[promise_id] = value
        return value


def _parse_payload(text: str) -> tuple[list[Any], dict[int, _Chunk]]:
    if not isinstance(text, str) or not text.strip():
        raise RemixDecodeError("The response body is empty")
    lines = text.splitlines()
    try:
        initial = json.loads(lines[0])
    except json.JSONDecodeError as err:
        raise RemixDecodeError(f"Invalid initial JSON payload: {err}") from err
    if not isinstance(initial, list):
        raise RemixDecodeError("The initial payload is not a flattened value table")

    chunks: dict[int, _Chunk] = {}
    combined = list(initial)
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        match = _CHUNK_LINE.fullmatch(line)
        if not match:
            raise RemixDecodeError(f"Malformed continuation at line {line_number}")
        kind, raw_id, body = match.groups()
        try:
            values = json.loads(body)
        except json.JSONDecodeError as err:
            raise RemixDecodeError(f"Invalid continuation JSON at line {line_number}: {err}") from err
        if not isinstance(values, list):
            raise RemixDecodeError(f"Continuation at line {line_number} is not a value table")
        chunk_id = int(raw_id)
        start_index = len(combined)
        combined.extend(values)
        chunks[chunk_id] = _Chunk(kind, chunk_id, start_index)
    return combined, chunks


def decode_remix(text: str) -> Any:
    """Decode a complete Remix/turbo-stream response into Python values."""

    values, chunks = _parse_payload(text)
    return _FlatGraphDecoder(values, chunks).decode()


def walk(value: Any) -> Iterator[Any]:
    """Yield every dict/list node in a decoded graph, cycle-safe."""

    stack = [value]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, (dict, list, tuple, set)):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            yield current
            if isinstance(current, dict):
                stack.extend(reversed(list(current.values())))
            else:
                stack.extend(reversed(list(current)))


def find_dicts(value: Any, required_keys: set[str] | frozenset[str]) -> Iterator[dict[str, Any]]:
    """Yield decoded objects containing all ``required_keys``."""

    for current in walk(value):
        if isinstance(current, dict) and required_keys.issubset(current):
            yield current


def route_data(decoded: Any, route_id: str) -> Any | None:
    """Return the ``data`` value for an exact decoded Remix route id."""

    if not isinstance(decoded, dict):
        return None
    route = decoded.get(route_id)
    if isinstance(route, dict) and "data" in route:
        return route["data"]
    return None
