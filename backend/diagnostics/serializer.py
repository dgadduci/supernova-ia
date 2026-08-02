from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .redaction import redact as redact_value

_MAX_DEPTH = 64
_MAX_FIELDS = 4096


def serialize(
    value: object,
    *,
    redact: bool = True,
    _seen: set[int] | None = None,
) -> object:
    seen = _seen if _seen is not None else set()
    field_count = [0]
    serialized = _serialize(value, seen, field_count, 0)
    if redact:
        return redact_value(serialized)
    return serialized


def _serialize(
    value: object,
    seen: set[int],
    field_count: list[int],
    depth: int,
) -> object:
    if isinstance(value, Enum):
        return _serialize(value.value, seen, field_count, depth + 1)
        return _serialize(value.value, seen, field_count, depth + 1)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= _MAX_DEPTH or field_count[0] >= _MAX_FIELDS:
        return _fallback(value)

    value_id = id(value)
    if value_id in seen:
        return _fallback(value)

    seen.add(value_id)
    try:
        if isinstance(value, dict):
            return _serialize_dict(value, seen, field_count, depth)
        if isinstance(value, (list, tuple)):
            return _serialize_sequence(value, seen, field_count, depth)
        if isinstance(value, (set, frozenset)):
            items = _serialize_sequence(value, seen, field_count, depth)
            return sorted(items, key=_stable_sort_key)
        if is_dataclass(value) and not isinstance(value, type):
            data = {
                field.name: getattr(value, field.name)
                for field in fields(value)
            }
            return _serialize_dict(data, seen, field_count, depth)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return _serialize(
                model_dump(mode="json"),
                seen,
                field_count,
                depth + 1,
            )
        table = getattr(type(value), "__table__", None)
        if table is not None:
            return _serialize_orm(value, table, seen, field_count, depth)
        return _fallback(value)
    finally:
        seen.remove(value_id)


def _serialize_dict(
    value: Mapping[Any, Any],
    seen: set[int],
    field_count: list[int],
    depth: int,
) -> dict[str, object]:
    indexed_items = [
        (str(key), index, item)
        for index, (key, item) in enumerate(value.items())
    ]
    result: dict[str, object] = {}
    for key, _, item in sorted(indexed_items, key=lambda entry: (entry[0], entry[1])):
        if field_count[0] >= _MAX_FIELDS:
            result[key] = _fallback(item)
            continue
        field_count[0] += 1
        result[key] = _serialize(item, seen, field_count, depth + 1)
    return result


def _serialize_sequence(
    value: Any,
    seen: set[int],
    field_count: list[int],
    depth: int,
) -> list[object]:
    result: list[object] = []
    for item in value:  # type: ignore[union-attr]
        if field_count[0] >= _MAX_FIELDS:
            result.append(_fallback(item))
            continue
        field_count[0] += 1
        result.append(_serialize(item, seen, field_count, depth + 1))
    return result


def _serialize_orm(
    value: object,
    table: Any,
    seen: set[int],
    field_count: list[int],
    depth: int,
) -> dict[str, object]:
    state = vars(value)
    data: dict[str, object] = {}
    for column in table.columns:
        name = str(getattr(column, "key", getattr(column, "name", "")))
        if name and name in state:
            data[name] = state[name]
    return _serialize_dict(data, seen, field_count, depth)


def _stable_sort_key(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fallback(value: object) -> str:
    return f"<{type(value).__name__}>"


__all__ = ["serialize"]
