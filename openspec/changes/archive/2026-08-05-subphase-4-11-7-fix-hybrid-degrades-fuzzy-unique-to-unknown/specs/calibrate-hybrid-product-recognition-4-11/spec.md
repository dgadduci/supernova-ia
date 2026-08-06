## ADDED Requirements

### Requirement: hybrid preserves fuzzy_unique when the vector contributes no candidates

The hybrid decision produced by the runner (`backend/services/product_recognition_calibration_runner.py`) SHALL return `"unique"` when `observation.fuzzy_decision == "unique"` AND `len(observation.vector_ids) == 0`. The guard is a single positional `if` block at the top of `_hybrid_prediction` (placed ABOVE the Subphase 4.11.5 `pending_product_selection_restricted` + `fuzzy_ambiguous` guard, which remains unchanged) that short-circuits BEFORE the existing scoring rule. When the guard fires, the runner returns a `StrategyPrediction` constructed from the fuzzy observation directly: `decision="unique"`, `top_id=observation.fuzzy_ids[0]`, `ranking=observation.fuzzy_ids`, `scores=observation.fuzzy_scores`, `canonical` and `alias` computed by `_exact_flags(case, observation.fuzzy_ids)` (the same shape the 4.11.5 guard returns). The guard does NOT modify `_decision`, `_prediction`, `_exact_flags`, `_fuzzy_decision`, `_fuzzy_ids`, `_flag_fuzzy_boundary_violation`, `_strategy_metrics`, or `_eligibility`. The guard does NOT add a new field to `StrategyPrediction` or `CaseObservation`; it does NOT modify the policy dataclass, the policy grid generator, the JSON report schema, the diagnostic surface, or the CLI surface.

The guard fires only when both conditions are met:

- `observation.fuzzy_decision == "unique"`
- `len(observation.vector_ids) == 0` (i.e. the vector contributed no candidates — the `vector_ids` tuple is empty)

The guard is scope-independent: it does NOT inspect `catalog_scope` and may therefore fire for `pending_product_selection_restricted` cases whenever the precondition holds (which is impossible in the current dataset, but the guard itself imposes no scope restriction).

The guard does NOT fire when EITHER condition fails. In particular:

- The guard does NOT fire when `observation.fuzzy_decision == "ambiguous"` (the 4.11.5 guard still fires for that case at a `pending_product_selection_restricted` scope; elsewhere the existing scoring rule applies).
- The guard does NOT fire when `observation.fuzzy_decision == "unknown"` (the existing scoring rule applies and produces `unknown`).
- The guard does NOT fire when `len(observation.vector_ids) > 0` (the existing scoring rule applies and the vector contribution is honored, even if the vector top-1 disagrees with the fuzzy top-1).
- The two guards are mutually exclusive on `fuzzy_decision`: the 4.11.5 guard requires `"ambiguous"`; the 4.11.7 guard requires `"unique"`. There is no risk of the 4.11.7 guard short-circuiting the 4.11.5 guard for any case.
- The guard is purely additive: it can only force `unique`; it never forces `ambiguous` or `unknown`.

The guard's `canonical` / `alias` flags are computed by `_exact_flags(case, observation.fuzzy_ids)` (the existing helper at `runner.py:133-148`). For the four named failing cases, the input does not equal the canonical `producto_nombre` and does not appear in any alias list, so `canonical=False, alias=False` — but the guard does NOT use the `canonical or alias` short-circuit; it forces `"unique"` based purely on the `fuzzy_decision == "unique"` AND `len(vector_ids) == 0` precondition. The `canonical` / `alias` flags are still recorded in the returned `StrategyPrediction` so the per-case `case_results` records continue to expose them (the dataset's `match_expectation` field remains the source of truth for the per-case canonical / alias expectation).

The runner's existing scoring formula `policy.fuzzy_weight * fuzzy.get(value, 0.0) + policy.vector_weight * vector.get(value, 0.0)` is preserved verbatim. The guard short-circuits BEFORE the scoring formula; the scoring formula is only consulted when the guard does not fire.

#### Scenario: product-plus-presentation returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `product-plus-presentation` (input `"una pizza muzza grande"`, `catalog_scope: in_memory`, `id_comercio: 2`, `allowed_candidate_ids: [2]`, in-memory catalog `pizza_mozzarella_presentations` with `pid=2`, `expected_decision: unique`, `expected_producto_presentacion_id: 2`)
- **AND** the fuzzy recognizer returns `unique(pid=2)` with `observation.fuzzy_ids = (2,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=2`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: fuzzy-misspelling-mozzarella returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `fuzzy-misspelling-mozzarella` (input `"piza mozarela"`, `catalog_scope: in_memory`, `id_comercio: 3`, `allowed_candidate_ids: [100]`, in-memory catalog `pizza_mozzarella_short` with `pid=100`, `expected_decision: unique`, `expected_producto_presentacion_id: 100`)
- **AND** the fuzzy recognizer returns `unique(pid=100)` with `observation.fuzzy_ids = (100,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=100`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: supported-mozza-alias returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `supported-mozza-alias` (input `"pizza muzza"`, `catalog_scope: in_memory`, `id_comercio: 3`, `allowed_candidate_ids: [100]`, in-memory catalog `pizza_mozzarella_short` with `pid=100`, `expected_decision: unique`, `expected_producto_presentacion_id: 100`, `match_expectation: alias`)
- **AND** the fuzzy recognizer returns `unique(pid=100)` with `observation.fuzzy_ids = (100,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=100`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: multi-word-jamon-queso-dynamic returns hybrid unique with the correct id

- **WHEN** the calibration runner evaluates the case `multi-word-jamon-queso-dynamic` (input `"empanada de jamon y queso"`, `catalog_scope: commerce_dynamic_database`, `id_comercio: 1`, `expected_decision: unique`, `expected_producto_presentacion_id_ref: pp_empanada_jamon_queso`, `match_expectation: neither`)
- **AND** the fuzzy recognizer returns `unique(pid=33)` with `observation.fuzzy_ids = (33,)`, `observation.fuzzy_decision = "unique"`, `observation.fuzzy_scores = (s,)` for some `s > 0`
- **AND** the vector search returns no candidates (`observation.vector_ids = ()`, `observation.vector_scores = ()`)
- **THEN** the guard fires (the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`)
- **AND** the hybrid decision is `"unique"` with `top_id=33`
- **AND** the case is classified as `correct` (the residual `real_hybrid_recognizer_failure` for this case is eliminated)

#### Scenario: guard does not fire when vector contributes candidates

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case where `observation.fuzzy_decision == "unique"` AND `observation.vector_ids` is non-empty
- **THEN** the guard does NOT fire (the `len(vector_ids) == 0` check fails — the vector contributed candidates)
- **AND** the hybrid decision follows the existing scoring rule (the canonical/alias promotion fires, the combined `ranking` is sorted by score, and the decision is `"unique"`)
- **AND** the case classification is preserved (the pre-Subphase-4.11.7 behavior is preserved)

#### Scenario: guard does not fire when fuzzy decision is ambiguous

- **WHEN** the calibration runner evaluates a case where `observation.fuzzy_decision == "ambiguous"` AND `observation.vector_ids` is empty
- **THEN** the guard does NOT fire (the `fuzzy_decision == "unique"` check fails — the fuzzy decision is `"ambiguous"`)
- **AND** the existing scoring rule applies
- **AND** the case classification is preserved (the pre-Subphase-4.11.7 behavior is preserved)

#### Scenario: guard does not fire when fuzzy decision is unknown

- **WHEN** the calibration runner evaluates a case where `observation.fuzzy_decision == "unknown"` AND `observation.vector_ids` is empty (e.g. `picante-restricted-refinement` with fuzzy `unknown`)
- **THEN** the guard does NOT fire (the `fuzzy_decision == "unique"` check fails — the fuzzy decision is `"unknown"`)
- **AND** the existing scoring rule applies: `not ranking` AND `fuzzy_decision == "unknown"` → `"unknown"`
- **AND** the `ambiguous-empanada-carne` case is NOT triggered by this guard because its `fuzzy_decision == "ambiguous"` — the 4.11.5 guard handles it instead

#### Scenario: 4.11.5 ambiguous-empanada-carne guard still fires

- **WHEN** the calibration runner evaluates the case `ambiguous-empanada-carne` (input `"empanada de carne"`, `catalog_scope: pending_product_selection_restricted`, `id_comercio: 4`, `allowed_candidate_ids: [11, 12]`, in-memory catalog `empanada_carne_restricted` with `pid=11` and `pid=12`, `expected_decision: ambiguous`)
- **AND** the fuzzy recognizer returns ambiguous with `observation.fuzzy_ids = (11, 12)`, `observation.fuzzy_decision = "ambiguous"`
- **AND** the vector search returns `unique(pid=11)`
- **THEN** the Subphase 4.11.7 guard does NOT fire (the `fuzzy_decision == "unique"` check fails — the fuzzy decision is `"ambiguous"`)
- **AND** the Subphase 4.11.5 guard fires (the scope is `pending_product_selection_restricted` AND the fuzzy decision is `"ambiguous"`)
- **AND** the hybrid decision is `"ambiguous"` regardless of the vector's top-1 contribution
- **AND** the case is classified as `correct` (the pre-Subphase-4.11.7 behavior is preserved)

#### Scenario: 4.11.5 restricted ambiguous guard remains correct after the fix

- **WHEN** the focused regression suite pins the 4.11.5 guard after the 4.11.7 fix is applied
- **THEN** `ambiguous-empanada-carne` is classified as `correct` with `actual_hybrid_decision == "ambiguous"`
- **AND** the 4.11.7 guard does NOT fire for `ambiguous-empanada-carne` (the fuzzy decision is `"ambiguous"`, not `"unique"`)

#### Scenario: false_positives remain zero after the fix

- **WHEN** the runner produces the post-fix JSON report and the eligibility verdict
- **THEN** `hybrid_metrics.false_positives.count == 0` (the 4.11.7 guard returns the fuzzy prediction verbatim, which has already been validated as `unique` by `_fuzzy_decision`; the fuzzy recognizer is the production-grade recognizer audited across the Subphase 4.11 chain; no case produces a false positive)
- **AND** `hybrid_metrics.false_positives.rate == 0.0`
- **AND** `incorrect_unique_decisions.count` does NOT increase (the 4 cases that flip from `"unknown"` to `"unique"` all have `expected_decision == "unique"` and `expected_producto_presentacion_id == fuzzy_ids[0]`, so the `_correct` check returns `True`)

#### Scenario: complete 47-case calibration remains eligible

- **WHEN** the runner evaluates the 47-case dataset after the fix
- **THEN** `decision_accuracy.count == 45` (up from 41)
- **AND** `false_unknowns.count == 2` (down from 6)
- **AND** `false_positives.count == 0`
- **AND** `incorrect_unique_decisions.count == 0`
- **AND** the eligibility verdict is `eligible`