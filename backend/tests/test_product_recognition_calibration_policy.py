from dataclasses import FrozenInstanceError

import pytest

from backend.services.product_recognition_calibration_policy import (
    AMBIGUOUS_THRESHOLDS,
    PROVISIONAL_DEFAULTS,
    SCORE_GAPS,
    TOP_K_VALUES,
    UNIQUE_THRESHOLDS,
    WEIGHT_POINTS,
    CalibrationDatasetError,
    HybridDecisionPolicy,
    dataset_fingerprint,
    generate_policy_grid,
    nearest_rank,
    policy_distance,
    validate_dataset,
)


def policy(**overrides):
    values = {
        "fuzzy_weight": 0.5,
        "vector_weight": 0.5,
        "unique_threshold": 0.7,
        "ambiguous_threshold": 0.4,
        "minimum_score_gap": 0.05,
        "vector_top_k": 5,
    }
    values.update(overrides)
    return HybridDecisionPolicy(**values)


def test_policy_is_frozen_and_valid():
    value = policy()
    with pytest.raises(FrozenInstanceError):
        value.fuzzy_weight = 0.4  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"fuzzy_weight": float("nan")},
        {"vector_weight": float("inf")},
        {"fuzzy_weight": 0.2, "vector_weight": 0.2},
        {"fuzzy_weight": -0.1},
        {"vector_weight": 1.1},
        {"unique_threshold": -0.1},
        {"ambiguous_threshold": 1.1},
        {"unique_threshold": 0.3, "ambiguous_threshold": 0.4},
        {"minimum_score_gap": 2.0},
        {"vector_top_k": 0},
        {"vector_top_k": True},
    ],
)
def test_policy_rejects_invalid_invariants(overrides):
    with pytest.raises(ValueError):
        policy(**overrides)


def test_policy_grid_is_repeatable_and_declared():
    first = generate_policy_grid()
    second = generate_policy_grid()
    assert first == second
    assert len(first) == 243
    assert first[0].fuzzy_weight, first[0].vector_weight == WEIGHT_POINTS[0]
    assert {item.unique_threshold for item in first} == set(UNIQUE_THRESHOLDS)
    assert {item.ambiguous_threshold for item in first} == set(AMBIGUOUS_THRESHOLDS)
    assert {item.minimum_score_gap for item in first} == set(SCORE_GAPS)
    assert {item.vector_top_k for item in first} == set(TOP_K_VALUES)


def test_grid_has_no_duplicates_and_distance_is_deterministic():
    grid = generate_policy_grid()
    assert len(grid) == len(set(grid))
    assert policy_distance(PROVISIONAL_DEFAULTS) == 0
    assert policy_distance(grid[0]) == policy_distance(grid[0])


def test_nearest_rank_is_deterministic():
    assert nearest_rank([5, 1, 3, 2, 4], 0.5) == 3
    assert nearest_rank([5, 1, 3, 2, 4], 0.95) == 5
    assert nearest_rank([], 0.5) is None


def test_dataset_fingerprint_is_canonical():
    first = {"schema_version": 1, "catalogs": {}, "cases": []}
    second = {"cases": [], "catalogs": {}, "schema_version": 1}
    assert dataset_fingerprint(first) == dataset_fingerprint(second)


def test_dataset_validation_rejects_duplicate_and_invalid_cases():
    dataset = {
        "schema_version": 1,
        "catalogs": {"fixture": {"entries": []}},
        "cases": [
            {
                "case_id": "case",
                "id_comercio": 1,
                "input_text": "x",
                "expected_decision": "unknown",
                "allowed_candidate_ids": [],
                "restricted_candidate_ids": [],
                "match_expectation": "neither",
                "presentation_resolution_expectation": "unknown",
                "category": "baseline",
                "catalog_fixture": "fixture",
            },
        ],
    }
    assert validate_dataset(dataset) is dataset
    duplicate = {**dataset, "cases": [dataset["cases"][0], dataset["cases"][0]]}
    with pytest.raises(CalibrationDatasetError):
        validate_dataset(duplicate)
