from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from backend.services.product_recognition_calibration_policy import canonical_json

FORBIDDEN_KEYS = {
    "input_text",
    "text",
    "vector",
    "vectors",
    "credentials",
    "prompt",
    "prompts",
    "source_documents",
    "stack_trace",
    "exception",
    "session",
    "connection",
}


def _safe(value: Any, key: str | None = None) -> Any:
    if key is not None and key.lower() in FORBIDDEN_KEYS:
        raise ValueError(f"forbidden report field: {key}")
    if isinstance(value, dict):
        return {str(name): _safe(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not __import__("math").isfinite(value):
        raise ValueError("report numbers must be finite")
    return value


def serialize_report(report: dict[str, Any]) -> bytes:
    return canonical_json(_safe(report))


def write_report_atomic(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_report(report)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def read_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise TypeError("report must be an object")
    return value


def write_diagnostic_atomic(records: list[dict[str, Any]], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_records: list[dict[str, Any]] = []
    for record in records:
        cleaned = {key: value for key, value in record.items() if key.lower() not in FORBIDDEN_KEYS}
        for value in cleaned.values():
            if isinstance(value, float) and not __import__("math").isfinite(value):
                raise ValueError("report numbers must be finite")
        safe_records.append(cleaned)
    payload = canonical_json({"cases": safe_records})
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


__all__ = ["read_report", "serialize_report", "write_diagnostic_atomic", "write_report_atomic"]
