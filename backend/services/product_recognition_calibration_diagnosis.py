from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any


class MISMATCH_CATEGORY(str, Enum):
    COMMERCE_SCOPE_MISMATCH = "commerce_scope_mismatch"
    PRODUCT_ID_MISMATCH = "product_id_mismatch"
    PRESENTATION_ID_MISMATCH = "presentation_id_mismatch"
    OUTPUT_NORMALIZATION_MISMATCH = "output_normalization_mismatch"
    DECISION_MAPPING_MISMATCH = "decision_mapping_mismatch"
    INVALID_DATASET_EXPECTATION = "invalid_dataset_expectation"
    STALE_SEED_REFERENCE = "stale_seed_reference"
    REAL_FUZZY_RECOGNIZER_FAILURE = "real_fuzzy_recognizer_failure"
    REAL_HYBRID_RECOGNIZER_FAILURE = "real_hybrid_recognizer_failure"
    OTHER_WITH_EVIDENCE = "other_with_evidence"


MISMATCH_CATEGORIES = tuple(category.value for category in MISMATCH_CATEGORY)


def normalize_canonical_id(record: Any) -> int:
    if record is None:
        raise ValueError("canonical producto_presentacion.id is missing")
    if isinstance(record, bool):
        raise TypeError("canonical producto_presentacion.id must be an integer")
    if isinstance(record, int):
        return record
    if isinstance(record, (list, tuple)):
        if len(record) != 1:
            raise ValueError("canonical producto_presentacion.id candidate list is ambiguous")
        return normalize_canonical_id(record[0])
    if isinstance(record, dict):
        if any(key in record for key in ("presentacion_codigo", "presentacion_id", "presentacion_descripcion", "presentacion")) and "producto_presentacion_id" not in record:
            raise ValueError("non-canonical presentation identifier")
        if "producto_presentacion_id" not in record:
            for key in ("id_producto_presentacion", "expected_producto_presentacion_id", "resolved_producto_presentacion_id"):
                if key in record:
                    return normalize_canonical_id(record[key])
            raise ValueError("canonical producto_presentacion.id is missing")
        value = record["producto_presentacion_id"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("canonical producto_presentacion.id must be an integer")
        return value
    raise ValueError("non-canonical presentation identifier")


def classify_mismatch(case_record: dict[str, Any], inventory_entry: dict[str, Any] | None = None) -> MISMATCH_CATEGORY:
    expected = case_record.get("expected_producto_presentacion_id")
    actual_fuzzy = case_record.get("actual_fuzzy_producto_presentacion_id")
    actual_hybrid = case_record.get("actual_hybrid_producto_presentacion_id")
    if case_record.get("id_comercio") != case_record.get("actual_id_comercio") and case_record.get("actual_id_comercio") is not None:
        return MISMATCH_CATEGORY.COMMERCE_SCOPE_MISMATCH
    if (
        expected is not None
        and actual_fuzzy is not None
        and case_record.get("expected_producto_id") is not None
        and case_record.get("actual_fuzzy_producto_id") is not None
        and case_record["expected_producto_id"] != case_record["actual_fuzzy_producto_id"]
    ):
        return MISMATCH_CATEGORY.PRODUCT_ID_MISMATCH
    if (
        expected is not None
        and actual_fuzzy is not None
        and case_record.get("expected_presentacion_id") is not None
        and case_record.get("actual_fuzzy_presentacion_id") is not None
        and case_record["expected_presentacion_id"] != case_record["actual_fuzzy_presentacion_id"]
    ):
        return MISMATCH_CATEGORY.PRESENTATION_ID_MISMATCH
    if case_record.get("normalization_mismatch"):
        return MISMATCH_CATEGORY.OUTPUT_NORMALIZATION_MISMATCH
    if case_record.get("decision_mapping_mismatch"):
        return MISMATCH_CATEGORY.DECISION_MAPPING_MISMATCH
    if case_record.get("dataset_expectation_mismatch"):
        return MISMATCH_CATEGORY.INVALID_DATASET_EXPECTATION
    if case_record.get("seed_reference_mismatch"):
        return MISMATCH_CATEGORY.STALE_SEED_REFERENCE
    if expected is not None and actual_hybrid is not None and actual_hybrid != expected:
        return MISMATCH_CATEGORY.REAL_HYBRID_RECOGNIZER_FAILURE
    if expected is not None and actual_fuzzy is not None and actual_fuzzy != expected:
        return MISMATCH_CATEGORY.REAL_FUZZY_RECOGNIZER_FAILURE
    if case_record.get("actual_fuzzy_decision") == case_record.get("expected_decision") and case_record.get("actual_hybrid_decision") != case_record.get("expected_decision"):
        return MISMATCH_CATEGORY.REAL_HYBRID_RECOGNIZER_FAILURE
    if case_record.get("actual_fuzzy_decision") != case_record.get("expected_decision"):
        return MISMATCH_CATEGORY.REAL_FUZZY_RECOGNIZER_FAILURE
    return MISMATCH_CATEGORY.OTHER_WITH_EVIDENCE


def _atomic_json(value: Any, output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
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


def write_diagnostic_atomic(records: list[dict[str, Any]], output: str | Path) -> None:
    _atomic_json({"cases": records}, output)


def evidence_for(category: MISMATCH_CATEGORY, record: dict[str, Any]) -> str:
    if category is MISMATCH_CATEGORY.OTHER_WITH_EVIDENCE:
        return str(record.get("evidence") or "unclassified calibration mismatch")
    return ""


__all__ = ["MISMATCH_CATEGORIES", "MISMATCH_CATEGORY", "classify_mismatch", "evidence_for", "normalize_canonical_id", "write_diagnostic_atomic"]
