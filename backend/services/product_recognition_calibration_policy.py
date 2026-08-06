from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from typing import Any


class CalibrationDatasetError(ValueError):
    pass


@dataclass(frozen=True)
class HybridDecisionPolicy:
    fuzzy_weight: float
    vector_weight: float
    unique_threshold: float
    ambiguous_threshold: float
    minimum_score_gap: float
    vector_top_k: int

    def __post_init__(self) -> None:
        values = (
            self.fuzzy_weight,
            self.vector_weight,
            self.unique_threshold,
            self.ambiguous_threshold,
            self.minimum_score_gap,
        )
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
            raise ValueError("policy values must be finite numbers")
        if not 0 <= self.fuzzy_weight <= 1 or not 0 <= self.vector_weight <= 1:
            raise ValueError("policy weights must be between 0 and 1")
        if not math.isclose(self.fuzzy_weight + self.vector_weight, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("policy weights must sum to 1")
        if any(not 0 <= value <= 1 for value in (self.unique_threshold, self.ambiguous_threshold, self.minimum_score_gap)):
            raise ValueError("policy thresholds must be between 0 and 1")
        if self.unique_threshold < self.ambiguous_threshold:
            raise ValueError("unique_threshold must not be below ambiguous_threshold")
        if isinstance(self.vector_top_k, bool) or not isinstance(self.vector_top_k, int) or self.vector_top_k <= 0:
            raise ValueError("vector_top_k must be positive")


PROVISIONAL_DEFAULTS = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
WEIGHT_POINTS = ((0.4, 0.6), (0.5, 0.5), (0.6, 0.4))
UNIQUE_THRESHOLDS = (0.65, 0.70, 0.75)
AMBIGUOUS_THRESHOLDS = (0.35, 0.40, 0.45)
SCORE_GAPS = (0.00, 0.05, 0.10)
TOP_K_VALUES = (3, 5, 7)


def generate_policy_grid() -> list[HybridDecisionPolicy]:
    policies: list[HybridDecisionPolicy] = []
    seen: set[HybridDecisionPolicy] = set()
    for weight_pair, unique, ambiguous, gap, top_k in product(
        WEIGHT_POINTS,
        UNIQUE_THRESHOLDS,
        AMBIGUOUS_THRESHOLDS,
        SCORE_GAPS,
        TOP_K_VALUES,
    ):
        try:
            policy = HybridDecisionPolicy(
                fuzzy_weight=weight_pair[0],
                vector_weight=weight_pair[1],
                unique_threshold=unique,
                ambiguous_threshold=ambiguous,
                minimum_score_gap=gap,
                vector_top_k=top_k,
            )
        except ValueError:
            continue
        if policy not in seen:
            policies.append(policy)
            seen.add(policy)
    return policies


def policy_distance(policy: HybridDecisionPolicy) -> float:
    fields = (
        (policy.fuzzy_weight, PROVISIONAL_DEFAULTS.fuzzy_weight),
        (policy.vector_weight, PROVISIONAL_DEFAULTS.vector_weight),
        (policy.unique_threshold, PROVISIONAL_DEFAULTS.unique_threshold),
        (policy.ambiguous_threshold, PROVISIONAL_DEFAULTS.ambiguous_threshold),
        (policy.minimum_score_gap, PROVISIONAL_DEFAULTS.minimum_score_gap),
        (policy.vector_top_k / 7, PROVISIONAL_DEFAULTS.vector_top_k / 7),
    )
    return sum(abs(value - default) for value, default in fields)


def validate_dataset(dataset: Any) -> dict[str, Any]:
    if not isinstance(dataset, dict) or dataset.get("schema_version") not in {1, 2, 3}:
        raise CalibrationDatasetError("schema_version must be 1, 2, or 3")
    catalogs = dataset.get("catalogs")
    cases = dataset.get("cases")
    if not isinstance(catalogs, dict) or not isinstance(cases, list) or not cases:
        raise CalibrationDatasetError("dataset must contain non-empty catalogs and cases")
    if dataset["schema_version"] >= 3:
        _validate_eligibility(dataset.get("eligibility"))
    _validate_commerce_catalog_blocks(dataset)
    ids: set[str] = set()
    allowed_categories = {"canonical", "alias", "ambiguous", "unknown", "restricted", "commerce_isolation", "baseline"}
    for case in cases:
        if not isinstance(case, dict):
            raise CalibrationDatasetError("cases must contain objects")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise CalibrationDatasetError("case IDs must be unique non-empty strings")
        ids.add(case_id)
        required = ("id_comercio", "input_text", "expected_decision", "allowed_candidate_ids", "restricted_candidate_ids", "match_expectation", "presentation_resolution_expectation", "category", "catalog_fixture")
        if any(key not in case for key in required):
            raise CalibrationDatasetError(f"{case_id}: missing required field")
        if case["expected_decision"] not in {"unique", "ambiguous", "unknown"}:
            raise CalibrationDatasetError(f"{case_id}: invalid expected_decision")
        if not isinstance(case["id_comercio"], int) or not isinstance(case["input_text"], str):
            raise CalibrationDatasetError(f"{case_id}: invalid commerce or input")
        allowed = case["allowed_candidate_ids"]
        restricted = case["restricted_candidate_ids"]
        if not _stable_unique_ints(allowed) or not _stable_unique_ints(restricted) or set(allowed) & set(restricted):
            raise CalibrationDatasetError(f"{case_id}: invalid candidate boundaries")
        if case["match_expectation"] not in {"canonical", "alias", "neither"}:
            raise CalibrationDatasetError(f"{case_id}: invalid match expectation")
        if case["presentation_resolution_expectation"] not in {"resolved", "ambiguous", "unknown", "not_applicable"}:
            raise CalibrationDatasetError(f"{case_id}: invalid presentation expectation")
        if not isinstance(case["category"], str) or not case["category"] or case["category"] not in allowed_categories:
            raise CalibrationDatasetError(f"{case_id}: invalid category")
        if case["catalog_fixture"] not in catalogs:
            raise CalibrationDatasetError(f"{case_id}: unknown catalog fixture")
        expected_id = case.get("expected_producto_presentacion_id")
        if case["expected_decision"] == "unique" and expected_id is None and not case.get("expected_producto_presentacion_id_ref"):
            raise CalibrationDatasetError(f"{case_id}: unique case requires expected ID")
        if expected_id is not None and expected_id not in allowed:
            raise CalibrationDatasetError(f"{case_id}: expected ID must be allowed")
        correction = case.get("correction_evidence")
        if correction is not None:
            if not isinstance(correction, dict):
                raise CalibrationDatasetError(f"{case_id}: correction_evidence must be an object when present")
            for required_key in ("mismatch_category", "reason", "catalog_reference"):
                if required_key not in correction:
                    raise CalibrationDatasetError(f"{case_id}: correction_evidence missing {required_key!r}")
    return dataset


def _validate_commerce_catalog_blocks(dataset: dict[str, Any]) -> None:
    """Accept the optional ``commerce_catalog_inventory`` / ``commerce_catalog_fingerprint`` blocks.

    Both blocks are optional on ``schema_version: 3`` datasets. When
    present, the inventory block is a ``dict[str, list[dict]]`` keyed by
    the string representation of ``id_comercio``; each list carries the
    documented runtime field set, sorted by ``producto_presentacion_id``
    ascending. The fingerprint block is a ``dict[str, str]`` keyed by
    the same string. The blocks MUST NOT bump ``schema_version`` and
    the existing ``seed_refs`` / ``inventory_fingerprint`` derivation
    is unchanged.
    """
    inventory_block = dataset.get("commerce_catalog_inventory")
    if inventory_block is None:
        inventory_block = {}
    if not isinstance(inventory_block, dict):
        raise CalibrationDatasetError(
            "commerce_catalog_inventory must be an object keyed by id_comercio when present"
        )
    fingerprint_block = dataset.get("commerce_catalog_fingerprint")
    if fingerprint_block is None:
        fingerprint_block = {}
    if not isinstance(fingerprint_block, dict):
        raise CalibrationDatasetError(
            "commerce_catalog_fingerprint must be an object keyed by id_comercio when present"
        )
    for raw_key, raw_list in inventory_block.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise CalibrationDatasetError(
                "commerce_catalog_inventory keys must be non-empty strings"
            )
        try:
            id_comercio = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise CalibrationDatasetError(
                f"commerce_catalog_inventory key {raw_key!r} must parse as an int id_comercio"
            ) from exc
        if not isinstance(id_comercio, int) or isinstance(id_comercio, bool):
            raise CalibrationDatasetError(
                f"commerce_catalog_inventory key {raw_key!r} must parse as a non-bool int id_comercio"
            )
        if not isinstance(raw_list, list):
            raise CalibrationDatasetError(
                f"commerce_catalog_inventory[{raw_key!r}] must be a list"
            )
        from backend.services.product_recognition_calibration_commerce_catalog import (
            validate_commerce_catalog_inventory_shape,
        )

        validate_commerce_catalog_inventory_shape(raw_list, id_comercio)
    for raw_key, raw_value in fingerprint_block.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise CalibrationDatasetError(
                "commerce_catalog_fingerprint keys must be non-empty strings"
            )
        if not isinstance(raw_value, str) or not raw_value:
            raise CalibrationDatasetError(
                f"commerce_catalog_fingerprint[{raw_key!r}] must be a non-empty string"
            )


def _validate_eligibility(block: Any) -> None:
    """Validate the optional top-level ``eligibility`` block.

    The block is optional for ``schema_version >= 3``: when absent, the
    existing runner behaviour (``pending``) is preserved. When present,
    every required key must be present and hold a valid finite non-negative
    number (or a supported ``primary_metric`` string).
    """
    if block is None:
        return
    if not isinstance(block, dict):
        raise CalibrationDatasetError(
            "eligibility block must be an object when present"
        )
    required = (
        "primary_metric",
        "required_improvement",
        "false_positive_tolerance",
        "latency_budget_ms_p95",
    )
    for key in required:
        if key not in block:
            raise CalibrationDatasetError(f"eligibility: missing required key {key!r}")
    allowed_metrics = {
        "decision_accuracy",
        "top_1_accuracy",
        "canonical_match_accuracy",
        "alias_match_accuracy",
        "restricted_candidate_accuracy",
    }
    primary_metric = block["primary_metric"]
    if not isinstance(primary_metric, str) or primary_metric not in allowed_metrics:
        raise CalibrationDatasetError(
            f"eligibility.primary_metric must be one of {sorted(allowed_metrics)}"
        )
    for key in ("required_improvement", "false_positive_tolerance", "latency_budget_ms_p95"):
        value = block[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CalibrationDatasetError(
                f"eligibility.{key} must be a finite non-negative number"
            )
        if not math.isfinite(float(value)):
            raise CalibrationDatasetError(
                f"eligibility.{key} must be a finite non-negative number"
            )
        if float(value) < 0:
            raise CalibrationDatasetError(
                f"eligibility.{key} must be a finite non-negative number"
            )
    if not 0 <= float(block["false_positive_tolerance"]) <= 1:
        raise CalibrationDatasetError(
            "eligibility.false_positive_tolerance must be in [0, 1]"
        )


def _stable_unique_ints(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in value) and len(value) == len(set(value))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def dataset_fingerprint(dataset: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dataset)).hexdigest()


def nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    rank = max(1, min(len(ordered), math.ceil(percentile * len(ordered))))
    return ordered[rank - 1]


__all__ = [
    "AMBIGUOUS_THRESHOLDS",
    "PROVISIONAL_DEFAULTS",
    "SCORE_GAPS",
    "TOP_K_VALUES",
    "UNIQUE_THRESHOLDS",
    "WEIGHT_POINTS",
    "CalibrationDatasetError",
    "HybridDecisionPolicy",
    "canonical_json",
    "dataset_fingerprint",
    "generate_policy_grid",
    "nearest_rank",
    "policy_distance",
    "validate_dataset",
]
