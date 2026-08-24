from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    """Convert common Python values into deterministic JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value):
        return json_safe(dataclasses.asdict(value))
    if isinstance(value, enum.Enum):
        return json_safe(value.value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((json_safe(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    if hasattr(value, "dict") and callable(value.dict):
        return json_safe(value.dict())
    return {"__type__": f"{type(value).__module__}.{type(value).__qualname__}", "__repr__": repr(value)}


def canonical_json(value: Any) -> str:
    return json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def invocation_key(tool_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return stable_hash({"tool": tool_name, "args": args, "kwargs": kwargs})
