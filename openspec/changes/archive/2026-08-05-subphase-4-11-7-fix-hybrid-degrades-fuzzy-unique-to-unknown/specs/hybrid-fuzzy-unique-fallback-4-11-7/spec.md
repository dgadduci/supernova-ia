## ADDED Requirements

### Requirement: hybrid-fuzzy-unique-fallback-4-11-7 closes the 4 residual hybrid_recognizer_failure cases by guarding fuzzy_unique + empty_vector

The system MUST pin the single-purpose guard introduced by Subphase 4.11.7 and the closure criterion that proves the guard is necessary and sufficient. The guard MUST be a positional `if` block at the top of `_hybrid_prediction` in `backend/services/product_recognition_calibration_runner.py` that returns the fuzzy prediction verbatim when `observation.fuzzy_decision == "unique"` AND `len(observation.vector_ids) == 0`. The closure criterion MUST be: the four named cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) return the expected `unique` decision with the correct `producto_presentacion_id`; `false_positives.count` remains `0`; `incorrect_unique_decisions.count` remains `0`; the 4.11.5 `pending_product_selection_restricted` + `fuzzy_ambiguous` guard continues to fire for `ambiguous-empanada-carne`; and the complete 47-case calibration remains `eligible`.

This capability exists solely to satisfy the `spec-driven` schema's `specs` artifact and does not introduce a reusable runtime capability. There is no new module surface, no new contract, no new HTTP / persistence / orchestrator surface, and no new recognizer mode. The runner's `_hybrid_prediction` is the only file touched; the guard is a 1-block conditional return that consumes no new module-level state.

The Subphase 4.11.7 fix is the symmetric counterpart to the Subphase 4.11.5 fix:

- Subphase 4.11.5 introduced the `catalog_scope == "pending_product_selection_restricted"` AND `fuzzy_decision == "ambiguous"` guard that prevents the vector from promoting an ambiguous fuzzy to a unique hybrid at a restricted scope.
- Subphase 4.11.7 introduces the `fuzzy_decision == "unique"` AND `len(vector_ids) == 0` guard that prevents the score-threshold gating from degrading a unique fuzzy (with no vector disagreement) to an unknown hybrid at any scope.

The two guards are mutually exclusive on `fuzzy_decision`. The Subphase 4.11.5 guard handles `"ambiguous"`; the Subphase 4.11.7 guard handles `"unique"`. Both guards live in `_hybrid_prediction` as positional `if` blocks. The Subphase 4.11.5 guard is unchanged; the Subphase 4.11.7 guard is added above it.

The Subphase 4.11.7 guard is scope-independent: it does NOT inspect `catalog_scope`. It may therefore fire for `pending_product_selection_restricted` cases whenever the precondition holds (which is impossible in the current dataset, but the guard itself imposes no scope restriction). Mutual exclusion with the 4.11.5 guard is guaranteed by `fuzzy_decision`, not by scope.

The Subphase 4.11.7 fix does NOT modify any of the following:

- the `_decision` scoring formula (`policy.fuzzy_weight * fuzzy.get(value, 0.0) + policy.vector_weight * vector.get(value, 0.0)`)
- the policy dataclass (`HybridDecisionPolicy`)
- the policy grid generator (`generate_policy_grid`)
- the JSON report schema
- the diagnostic surface (`after.diagnose.json`)
- the CLI surface (`--dataset`, `--output`, `--diagnose`, `--diagnose-output`, `--commerce-id`, `--limit`)
- the eligibility verifier
- the `_exact_flags`, `_fuzzy_decision`, `_fuzzy_ids`, `_prediction`, `_strategy_metrics`, `_flag_fuzzy_boundary_violation`, `_resolve_expected_id` helpers
- the recognizer mode, the embedding client, the Ollama configuration, the vector data, the fuzzy threshold
- the calibration dataset (47 cases, no new cases, no removed cases, no renamed cases)
- the FastAPI routers, services, repositories, schemas, handlers, resolvers, recognizers, orchestrators, the pending-context chain, the seeds, the migrations, the settings, the `pyproject.toml`, the `ruff.toml`, or the `alembic.ini`

The Subphase 4.11.7 fix is the smallest possible set of source changes that closes the calibration chain: 1 file touched (`backend/services/product_recognition_calibration_runner.py`) with 1 new positional `if` block and 1 new test file (`backend/tests/test_product_recognition_calibration_4_11_7.py`).

#### Scenario: closure criterion — four named cases return unique with the correct id

- **WHEN** the calibration runner is invoked end-to-end with the unchanged 47-case dataset after the Subphase 4.11.7 fix
- **THEN** the four named cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) return the expected `unique` decision with `top_id` matching the dataset's `expected_producto_presentacion_id` or `expected_producto_presentacion_id_ref`
- **AND** `false_positives.count` remains `0`
- **AND** `incorrect_unique_decisions.count` remains `0`

#### Scenario: closure criterion — 4.11.5 restricted ambiguous guard remains correct

- **WHEN** the calibration runner is invoked end-to-end with the unchanged 47-case dataset after the Subphase 4.11.7 fix
- **THEN** the 4.11.5 guard for `pending_product_selection_restricted` + `fuzzy_ambiguous` still fires (the `ambiguous-empanada-carne` case remains `correct` with `actual_hybrid_decision == "ambiguous"`)
- **AND** the 4.11.7 guard does NOT fire for `ambiguous-empanada-carne` (the fuzzy decision is `"ambiguous"`, not `"unique"`)

#### Scenario: closure criterion — complete 47-case calibration remains eligible

- **WHEN** the calibration runner is invoked end-to-end with the unchanged 47-case dataset after the Subphase 4.11.7 fix
- **THEN** `decision_accuracy.count == 45` (up from 41)
- **AND** `false_unknowns.count == 2` (down from 6)
- **AND** `false_positives.count == 0`
- **AND** `incorrect_unique_decisions.count == 0`
- **AND** the eligibility verdict is `eligible`

#### Scenario: closure criterion — guard does not modify non-guarded paths

- **WHEN** the calibration runner is invoked end-to-end with the unchanged 47-case dataset after the Subphase 4.11.7 fix
- **THEN** the 4.11.5 guard for `pending_product_selection_restricted` + `fuzzy_ambiguous` still fires (the `ambiguous-empanada-carne` case remains `correct` with `actual_hybrid_decision == "ambiguous"`)
- **AND** the scoring formula is preserved verbatim (the guard short-circuits BEFORE the scoring formula)
- **AND** the policy grid is preserved verbatim (the guard does not alter any policy threshold, weight, gap, or `vector_top_k` value)

#### Scenario: closure criterion — guard is the only source change in the runner

- **WHEN** `git diff backend/services/product_recognition_calibration_runner.py` is inspected after the Subphase 4.11.7 fix
- **THEN** the diff is exactly 1 new positional `if` block at the top of `_hybrid_prediction` (above the existing 4.11.5 guard)
- **AND** no other function in the runner is modified
- **AND** no other file in `backend/services/` is modified
- **AND** no other file in `backend/` is modified (other than the new test file `backend/tests/test_product_recognition_calibration_4_11_7.py`)

#### Scenario: closure criterion — focused regression test file pins the new behaviour

- **WHEN** the focused regression test file `backend/tests/test_product_recognition_calibration_4_11_7.py` is inspected
- **THEN** it pins (1) the four named cases return `unique` with the correct `producto_presentacion_id`; (2) the 4.11.5 `ambiguous-empanada-carne` case continues to return `ambiguous`; (3) `false_positives.count` remains `0`; (4) `incorrect_unique_decisions.count` remains `0`; (5) the complete 47-case calibration remains `eligible`
- **AND** the file is self-contained and does NOT modify any existing test file
- **AND** the file runs the runner end-to-end and inspects the per-case decisions and the eligibility verdict