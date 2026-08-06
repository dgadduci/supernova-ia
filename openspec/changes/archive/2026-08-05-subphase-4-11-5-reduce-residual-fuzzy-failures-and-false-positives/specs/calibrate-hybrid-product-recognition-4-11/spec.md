## ADDED Requirements

### Requirement: hybrid guard preserves fuzzy ambiguity for pending_product_selection_restricted cases (including category-level ambiguity)

The hybrid decision produced by the runner (`backend/services/product_recognition_calibration_runner.py`) SHALL return `"ambiguous"` when the case's `catalog_scope == "pending_product_selection_restricted"` AND the fuzzy decision is explicitly `ambiguous`. The fuzzy decision is `"ambiguous"` when EITHER (a) `len(fuzzy_ids) > 1` on the stored `CaseObservation.fuzzy_ids` (i.e. the fuzzy recognizer returned multiple product-level candidates via `encontrados` / `encontrados_posibles[].productos[]`), OR (b) the recognizer result contains a category-level `encontrados_posibles` group with `kind: "category"` detected by the `_fuzzy_decision(result)` helper. The guard is a single positional tag in the existing `_decision` path (or its equivalent in `_prediction` / `_hybrid_prediction`) that fires before the scoring rule consults `policy.fuzzy_weight`, `policy.vector_weight`, `policy.unique_threshold`, `policy.ambiguous_threshold`, `policy.minimum_score_gap`, `policy.vector_top_k`, the canonical/alias promotion in `_exact_flags`, the vector's top-1, or the score combination. The guard does not modify `_hybrid_prediction`'s scoring formula, the policy grid, the JSON report schema, the diagnostic surface, or the CLI surface.

The fuzzy decision is threaded into `_decision` (or its equivalent) as a derived parameter from the existing `CaseObservation.fuzzy_ids` and the category discriminator (computed once in `_hybrid_prediction` via `_fuzzy_decision(fuzzy_result)`, where `_fuzzy_decision(result)` returns `"ambiguous"` whenever a category-level `encontrados_posibles` group carries `kind: "category"`; otherwise it falls back to the existing id-based logic `"unique" if len(fuzzy_ids) == 1 else "ambiguous" if len(fuzzy_ids) > 1 else "unknown" if len(fuzzy_ids) == 0`). The guard SHALL inspect the fuzzy decision explicitly and SHALL NOT infer fuzzy ambiguity from the combined hybrid `ranking` — the combined hybrid ranking is the union of `observation.fuzzy_ids` and `observation.vector_ids`, so a fuzzy-`unique` + vector-`unique(other)` case produces a multi-candidate hybrid ranking even though the fuzzy was not ambiguous. Inferring fuzzy ambiguity from the combined hybrid `ranking` (e.g. via `len(ranking) > 1`) is unsafe and is explicitly forbidden by this requirement.

The guard fires only when both conditions are met:
- `case.get("catalog_scope") == "pending_product_selection_restricted"`
- the fuzzy decision is `"ambiguous"` (the direct evidence being EITHER `len(fuzzy_ids) > 1` on `CaseObservation.fuzzy_ids`, OR a category-level `encontrados_posibles` group with `kind: "category"` detected by `_fuzzy_decision(result)`)

The guard depends ONLY on `catalog_scope` and `fuzzy_decision`. Case origin (in-memory vs database) is irrelevant to the guard; `in_memory` is NOT a disabling condition; `commerce_dynamic_database` is NOT a disabling condition by origin alone. Cases of either origin remain unaffected unless both guard conditions are satisfied. The case `ambiguous-empanada-carne` IS an `in_memory` case (its catalog is loaded from the in-memory fixture `empanada_carne_restricted`) and the guard MUST fire for it because its `catalog_scope == "pending_product_selection_restricted"` AND its `fuzzy_decision == "ambiguous"`; the fact that the case is `in_memory` (uses an in-memory catalog fixture) is irrelevant to whether the guard fires. When the fuzzy returns exactly one candidate (or `unknown`), the guard does not fire — even if the combined hybrid ranking contains multiple candidates because the vector contributed an extra candidate. When the fuzzy returns `ambiguous` but the scope is not `pending_product_selection_restricted`, the guard does not fire. The guard is purely additive: it can only force `ambiguous`; it never promotes an otherwise-correct decision to `ambiguous`.

`_decision` SHALL also return `"ambiguous"` when the combined ranking is empty AND `fuzzy_decision == "ambiguous"` (category-level), and SHALL return `"unknown"` otherwise. This is a small refinement of the existing `if not ranking: return "unknown"` line; it does NOT alter the existing behavior for non-empty rankings, for `fuzzy_decision == "unique"`, or for `fuzzy_decision == "unknown"`. The runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire for category-level inputs because no product ids are extracted from the category-level group (the existing `_fuzzy_ids` extraction walks `encontrados_posibles[].productos[]` and the category-level group carries no `productos`).

#### Scenario: fuzzy ambiguous + restricted pending scope => hybrid remains ambiguous

- **WHEN** the calibration runner evaluates the case `ambiguous-empanada-carne` (input `"empanada de carne"`, `catalog_scope: pending_product_selection_restricted`, `id_comercio: 4`, `allowed_candidate_ids: [11, 12]`, in-memory catalog `empanada_carne_restricted` with `pid=11` (`Empanada de Carne PICANTE`) and `pid=12` (`Empanada de Carne TRADICIONAL`), `expected_decision: ambiguous`)
- **AND** the fuzzy recognizer returns ambiguous with candidates `[11, 12]` (the in-memory catalog has both presentations and the user did not specify a presentation)
- **AND** the vector search returns `unique(pid=11)` (the vector picked the PICANTE presentation)
- **THEN** the fuzzy decision (derived from `observation.fuzzy_ids = (11, 12)` via `_fuzzy_decision(fuzzy_result)`) is `"ambiguous"`
- **AND** the guard fires (the scope is `pending_product_selection_restricted` AND the fuzzy decision is explicitly `ambiguous`)
- **AND** the hybrid decision is `ambiguous` regardless of the vector's top-1 contribution (the semantic/vector top-1 is NOT allowed to promote the case to `unique`)
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)
- **AND** the `false_positives.count` drops from `1` to `0`
- **AND** the `false_positive_tolerance_failed` eligibility reason is eliminated

#### Scenario: guard does not fire for commerce_dynamic_database cases

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case with `allowed_candidate_ids: [1, 2]`, `id_comercio: 1`, fuzzy returns ambiguous `[1, 2]`, vector returns `unique(pid=1)` (e.g. `c1-canonical-pizza-muzzarella`)
- **THEN** the catalog scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`
- **AND** the fuzzy decision (derived from `observation.fuzzy_ids` via `_fuzzy_decision(fuzzy_result)`) is `"ambiguous"`
- **AND** the guard does not fire (the scope check fails — the scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`)
- **AND** the hybrid decision follows the existing scoring rule (the canonical/alias promotion fires and the decision is `unique`)
- **AND** the case is classified as `correct` (the pre-Subphase-4.11.5 behavior is preserved)

#### Scenario: guard does not fire when the fuzzy returns exactly one candidate

- **WHEN** the calibration runner evaluates a `pending_product_selection_restricted` case with fuzzy returning `unique(pid=11)` (e.g. a future refinement case where the fuzzy resolves the presentation)
- **THEN** the catalog scope is `pending_product_selection_restricted`
- **AND** `len(fuzzy_ids) == 1` (the fuzzy decision is explicitly `"unique"`, not `"ambiguous"`)
- **AND** the guard does not fire (the fuzzy decision check fails — the fuzzy decision is `"unique"`, not `"ambiguous"`; the guard does NOT inspect the combined hybrid `ranking` to infer fuzzy ambiguity)
- **AND** the hybrid decision follows the existing scoring rule

#### Scenario: guard does not fire when fuzzy returns unique BUT the combined hybrid ranking contains multiple candidates

- **WHEN** the calibration runner evaluates a `pending_product_selection_restricted` case where the fuzzy returns `unique(pid=11)` (i.e. `observation.fuzzy_ids = (11,)`) AND the vector returns a different candidate `unique(pid=12)` (i.e. `observation.vector_ids = (12,)`)
- **THEN** the catalog scope is `pending_product_selection_restricted`
- **AND** the fuzzy decision (derived from `observation.fuzzy_ids` via `_fuzzy_decision(fuzzy_result)`) is `"unique"` (NOT `ambiguous`)
- **AND** the combined hybrid `ranking` (the union of `observation.fuzzy_ids` and `observation.vector_ids`) contains 2 candidates `(11, 12)` with `len(ranking) > 1`
- **AND** the guard does NOT fire (the previous `len(ranking) > 1` proxy would have incorrectly fired; the corrected guard inspects the fuzzy decision explicitly and the fuzzy decision is `"unique"`, not `"ambiguous"`)
- **AND** the hybrid decision follows the existing scoring rule and is NOT forced to `ambiguous`
- **AND** the case is classified by the existing scoring rule (the pre-Subphase-4.11.5 behavior is preserved)

#### Scenario: guard does not fire when the fuzzy returns unknown

- **WHEN** the calibration runner evaluates the case `picante-restricted-refinement` (input `"picante"`, `catalog_scope: pending_product_selection_restricted`, `expected_decision: unknown`)
- **THEN** the fuzzy returns `unknown` (no candidates match the presentation refinement token)
- **AND** `len(fuzzy_ids) == 0`
- **AND** the fuzzy decision (derived from `observation.fuzzy_ids` via `_fuzzy_decision(fuzzy_result)`) is `"unknown"` (NOT `ambiguous`)
- **AND** the guard does not fire (the fuzzy decision check fails — the fuzzy decision is `"unknown"`, not `"ambiguous"`)
- **AND** the hybrid decision is `unknown` (matching the existing scoring rule)
- **AND** the case is classified as `correct` (the pre-Subphase-4.11.5 behavior is preserved)

#### Scenario: guard does not fire when the fuzzy returns category-level ambiguity at the wrong scope

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case where the fuzzy returns a category-level `encontrados_posibles` group with `kind: "category"` (i.e. the user input matches a category token like `"postre"` against a `commerce_dynamic_database` catalog)
- **THEN** the catalog scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`
- **AND** `_fuzzy_decision(fuzzy_result)` returns `"ambiguous"` (because the category-level group is present)
- **AND** the guard does NOT fire (the scope check fails — the scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`)
- **AND** the hybrid decision follows the existing scoring rule
- **AND** the case is classified by the existing scoring rule (the pre-Subphase-4.11.5 behavior is preserved for the scope check)

#### Scenario: guard does not modify _hybrid_prediction scoring formula (behavioral assertion)

- **WHEN** the test records the runner's observations before and after the guard is applied for the 11 preserved `in_memory` cases and the 36 `commerce_dynamic_database` cases
- **THEN** the recorded observations are byte-identical modulo the documented new `mismatch_category` and `mismatch_category_counts` fields for the 11 preserved `in_memory` cases
- **AND** the recorded observations are byte-identical modulo the documented new `mismatch_category` and `mismatch_category_counts` fields for the 36 `commerce_dynamic_database` cases (the guard does NOT fire for any of them because the scope is NOT `pending_product_selection_restricted`)
- **AND** the `_hybrid_prediction` scoring formula `policy.fuzzy_weight * fuzzy.get(value, 0.0) + policy.vector_weight * vector.get(value, 0.0)` is preserved verbatim (verified by the byte-identical observations of the 47 cases modulo the documented new fields; this replaces any source-string assertion)
- **AND** the guard body is a single positional tag in `_decision` that returns the string `"ambiguous"` immediately when the scope is `pending_product_selection_restricted` AND the fuzzy decision is `"ambiguous"`, with no other side effects (verified by the byte-identical observations of the 47 cases modulo the documented new fields)

#### Scenario: guard does not modify the policy grid (behavioral assertion)

- **WHEN** the test iterates `generate_policy_grid()` from `backend/services/product_recognition_calibration_policy.py` and compares the produced policies to the documented Cartesian grid
- **THEN** the weights match `(0.4, 0.6)`, `(0.5, 0.5)`, `(0.6, 0.4)`; the `unique_threshold` values match `0.65`, `0.70`, `0.75`; the `ambiguous_threshold` values match `0.35`, `0.40`, `0.45`; the `minimum_score_gap` values match `0.00`, `0.05`, `0.10`; and the `vector_top_k` values match `3`, `5`, `7`
- **AND** the total count of policies in the grid is unchanged from Subphase 4.11.4
- **AND** the Subphase 4.11 calibration policy invariants are preserved verbatim (this replaces any source-string assertion)

#### Scenario: JSON report schema is unchanged

- **WHEN** the runner produces a JSON report after the fix
- **THEN** the report carries the documented fields: `dataset_version`, `dataset_fingerprint`, `case_count`, `policy_count`, `selected_policy`, `fuzzy_metrics`, `hybrid_metrics`, `vector_metrics`, `mismatch_category_counts`, `case_results`, `policies`, `comparison`, `infrastructure_failures`, `failed_case_ids`, `latency_p50`, `latency_p95`, `eligibility`, `commerce_catalog_cache_size`
- **AND** the per-case `mismatch_category` field continues to be one of the ten documented categories or `correct`
- **AND** the `false_positives` metric in `hybrid_metrics` and `fuzzy_metrics` is the documented count of predicted-unique decisions when unique was not expected or the top-1 is not in `allowed_candidate_ids`
- **AND** no new required field is added to the report schema
- **AND** the `evidence` field in the per-case diagnostic record is preserved verbatim (the guard does not write evidence)

#### Scenario: 11 preserved in_memory cases produce byte-identical observations modulo the documented new fields

- **WHEN** the runner evaluates the 11 Subphase 4.11 cases that use an in-memory catalog fixture (catalog source: `in_memory`)
- **THEN** the guard fires for the `ambiguous-empanada-carne` case (it is an `in_memory` case whose `catalog_scope == "pending_product_selection_restricted"` AND whose `fuzzy_decision == "ambiguous"` — both guard conditions are satisfied; the case is `in_memory` in catalog source, but case origin is irrelevant to the guard)
- **AND** the guard does not fire for the 10 other `in_memory` cases: each one of them fails at least one of the two guard conditions (either `catalog_scope != "pending_product_selection_restricted"` OR `fuzzy_decision != "ambiguous"`); the other 10 `in_memory` cases are either `unique` or `unknown` and the guard's fuzzy-decision check fails on them
- **AND** the observations for the 10 other `in_memory` cases are byte-identical to the Subphase 4.11.4 observations modulo the documented new `mismatch_category` and `mismatch_category_counts` fields
- **AND** the eligibility gate is unchanged for the 10 cases that were `correct` in Subphase 4.11.4

#### Scenario: 39 currently correct cases do not regress

- **WHEN** the runner evaluates the 47-case dataset and the 39 currently correct cases (correct classification in Subphase 4.11.4)
- **THEN** every case that was `correct` in Subphase 4.11.4 is `correct` in Subphase 4.11.5
- **AND** the 19 `commerce_dynamic_database` cases whose fuzzy returns `ambiguous` continue to be classified by the existing scoring rule (the guard does not fire because the scope is `commerce_dynamic_database`, not `pending_product_selection_restricted`) — the pre-Subphase-4.11.5 behavior is preserved for these cases even though the combined hybrid ranking may contain multiple candidates
- **AND** the 4 other hybrid failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain classified as `real_hybrid_recognizer_failure` (no false promotion)
- **AND** the 3 residual fuzzy failures (`c1-ambiguous-postre`, `c1-fuzzy-vector-disagreement-muzarrella`, `c1-ambiguous-pizza-again`) are classified as `correct` (the residual `real_fuzzy_recognizer_failure` count drops from `3` to `0`)
- **AND** the false-positive case (`ambiguous-empanada-carne`) is classified as `correct` (the residual `real_hybrid_recognizer_failure` count drops from `5` to `4`)
- **AND** the `mismatch_category_counts` aggregate agrees with the per-case `mismatch_category` field

#### Scenario: false_positive_tolerance_failed is eliminated

- **WHEN** the runner produces the post-fix JSON report and the eligibility verdict
- **THEN** `false_positives.count == 0` (the runner's `false_positives` metric is computed against the recorded predictions and no case produces a false positive)
- **AND** `hybrid_metrics.false_positives.rate == 0.0` (and the same for `fuzzy_metrics.false_positives.rate`)
- **AND** the eligibility verdict's `reasons` list does NOT contain `false_positive_tolerance_failed` (the documented Subphase 4.11.3 reason string is preserved as part of the verifier)
- **AND** the other eligibility gates (`primary_metric_improvement`, `restricted_candidate_non_regression`, `canonical_match_accuracy`, `alias_match_accuracy`, `commerce_isolation`, `latency_budget`) are documented as either passing or unchanged from Subphase 4.11.4
- **AND** the final eligibility verdict is either `eligible` (if every gate passes) or `not_eligible` with `reasons` excluding `false_positive_tolerance_failed`

### Requirement: runner classifies category-level fuzzy results as ambiguous via the typed-discriminated-union discriminator

The runner SHALL add a helper `_fuzzy_decision(result)` that inspects the recognizer result and returns `"ambiguous"` whenever an `encontrados_posibles` group carries `kind: "category"`; otherwise it falls back to the existing id-based logic (`"unique"` if `len(fuzzy_ids) == 1`, `"ambiguous"` if `len(fuzzy_ids) > 1`, `"unknown"` if `len(fuzzy_ids) == 0`). The helper is the single source of truth for the fuzzy decision used by `_prediction`, `_hybrid_prediction`, and the `_decision` hybrid guard. The helper does NOT consult the combined hybrid `ranking` to infer fuzzy ambiguity. The helper is a pure function of the recognizer result; it does not mutate the recognizer result, the visible candidates, the pending context, the handlers, the responses, or any persistence.

The runner's `_fuzzy_ids(result)` extraction walks `encontrados[].producto_presentacion_id` and `encontrados_posibles[].productos[].producto_presentacion_id` via `group.get("productos", []) or []` so it safely extracts 0 ids for category-level groups (the typed-discriminated-union discriminator `kind: "category"` is the branch point). The explicit discriminator check inside `_fuzzy_ids` ensures the category signal is captured by `_fuzzy_decision(result)` rather than silently dropped. The runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire for category-level inputs because no product ids are extracted from the category-level group.

#### Scenario: `_fuzzy_decision` returns `"ambiguous"` for category-level groups

- **WHEN** the test imports `_fuzzy_decision` from the runner and calls it with `{"encontrados": [], "encontrados_posibles": [{"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"}], "encontrados_no_disponibles": [], "no_encontrados": []}`
- **THEN** the helper returns `"ambiguous"`
- **AND** the helper does NOT mutate the recognizer result
- **AND** the helper does NOT consult the combined hybrid `ranking` (it is a pure function of the recognizer result)

#### Scenario: `_fuzzy_decision` falls back to id-based logic for product-level groups

- **WHEN** the test calls `_fuzzy_decision({"encontrados": [{"producto_presentacion_id": 1}], "encontrados_posibles": [], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the helper returns `"unique"`
- **WHEN** the test calls `_fuzzy_decision({"encontrados": [{"producto_presentacion_id": 1}], "encontrados_posibles": [{"productos": [{"producto_presentacion_id": 2}]}], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the helper returns `"ambiguous"`
- **WHEN** the test calls `_fuzzy_decision({"encontrados": [], "encontrados_posibles": [], "encontrados_no_disponibles": [], "no_encontrados": []})`
- **THEN** the helper returns `"unknown"`

#### Scenario: `_decision` returns `"ambiguous"` when the combined ranking is empty AND the fuzzy decision is `"ambiguous"` (category-level)

- **WHEN** the test imports `_decision` from the runner and calls it with empty ranking and scores, a policy, the canonical / alias flags as `False`, and `fuzzy_decision="ambiguous"`
- **THEN** `_decision` returns `"ambiguous"` (NOT `"unknown"`)
- **WHEN** the test calls `_decision` with empty ranking and scores, a policy, the canonical / alias flags as `False`, and `fuzzy_decision="unique"`
- **THEN** `_decision` returns `"unknown"`
- **WHEN** the test calls `_decision` with empty ranking and scores, a policy, the canonical / alias flags as `False`, and `fuzzy_decision="unknown"`
- **THEN** `_decision` returns `"unknown"`
- **AND** the existing scoring branches for non-empty rankings are unchanged

#### Scenario: `_flag_fuzzy_boundary_violation` ignores category-level groups

- **WHEN** the test calls `_flag_fuzzy_boundary_violation(case, fuzzy_ids)` where `fuzzy_ids` is the empty tuple (extracted from a category-level `encontrados_posibles` group with `kind: "category"` and no `productos` list)
- **THEN** the function returns `False`
- **AND** the runner's per-case `candidate_boundary_violation` failure category is NOT set for the case `c1-ambiguous-pizza-again` (input `"otra pizza"`, `allowed_candidate_ids: [1, 2, 3, 4]`) because no product ids are extracted from the category-level group
