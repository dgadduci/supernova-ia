## Context

Subphase 4.11.6 closed the calibration chain by resolving the six remaining `C401` Ruff findings. The 47-case calibration is otherwise green: 41/47 cases are `correct`, `false_positives.count == 0`, and `false_unknowns.count == 6`. The residual 4 `real_hybrid_recognizer_failure` cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) all share the same failure mode: fuzzy returns `unique(single_pid)` and the vector returns nothing (`len(observation.vector_ids) == 0`); the hybrid scoring then degrades the fuzzy decision to `unknown` because `policy.fuzzy_weight * fuzzy_score + policy.vector_weight * 0` does not meet `policy.unique_threshold` for the best policy selected by the runner.

Subphase 4.11.5 introduced a positional guard in `_hybrid_prediction` for the symmetric case: `catalog_scope == "pending_product_selection_restricted"` AND `fuzzy_decision == "ambiguous"` forces `ambiguous` so the vector cannot promote an ambiguous fuzzy to a unique hybrid. The Subphase 4.11.7 guard is the structural counterpart: `fuzzy_decision == "unique"` AND `len(observation.vector_ids) == 0` returns the fuzzy prediction verbatim so the score-threshold gating cannot degrade a unique fuzzy (with no vector disagreement) to an `unknown` hybrid. The new guard is scope-independent: it does NOT inspect `catalog_scope`; it requires only that the fuzzy produced a unique decision and the vector contributed no candidates.

The two guards are mutually exclusive on `fuzzy_decision`: the 4.11.5 guard requires `fuzzy_decision == "ambiguous"`; the 4.11.7 guard requires `fuzzy_decision == "unique"`. There is no risk that the new guard short-circuits the 4.11.5 guard for any case, because the two preconditions cannot be simultaneously satisfied.

The two files touched are:

- `backend/services/product_recognition_calibration_runner.py` — the `_hybrid_prediction` function carries the new positional guard. No other function in the runner is modified. The guard sits ABOVE the existing 4.11.5 guard in source order; both guards remain positional `if` blocks and neither one disables the other.
- `backend/tests/test_product_recognition_calibration_4_11_7.py` (new file) — the focused regression suite for the four cases plus preservation checks for the 4.11.5 guard and the eligibility verdict.

The runner's `_decision` function is preserved verbatim — the guard does not modify the scoring formula, the policy grid, the JSON report schema, the diagnostic surface, or the eligibility verifier. The runner's `_flag_fuzzy_boundary_violation` (`runner.py:795-796`) is preserved verbatim — it still flags `pending_product_selection_restricted` cases whose fuzzy ids exceed `allowed_candidate_ids`. The runner's `_fuzzy_decision` (`runner.py:112-130`) and `_exact_flags` (`runner.py:133-148`) helpers are preserved verbatim.

## Goals / Non-Goals

**Goals:**

- Eliminate all 4 remaining `real_hybrid_recognizer_failure` cases (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) by returning the fuzzy prediction verbatim when `fuzzy_decision == "unique"` and `vector_ids` is empty.
- Preserve the 4.11.5 `pending_product_selection_restricted` + `fuzzy_ambiguous` → `ambiguous` behaviour (`ambiguous-empanada-carne` continues to return `ambiguous`).
- Keep the source change to the smallest possible surface (1 new positional guard inside `_hybrid_prediction`; 1 new test file).
- Maintain `false_positives.count == 0` (the guard cannot introduce a false positive because it short-circuits BEFORE the scoring rule and only returns the already-validated fuzzy prediction).
- Maintain `incorrect_unique_decisions.count == 0` (the four cases that flip to `unique` all have `expected_decision == "unique"` and `expected_producto_presentacion_id == fuzzy_ids[0]`).
- Re-run the 47-case calibration end-to-end after the fix and produce `calibration_after.json` + `calibration_after_diagnose.json` under the change's `diagnostics/` directory. Confirm the eligibility verdict remains `eligible`.

**Non-Goals:**

- Refactoring `_decision`, `_prediction`, `_exact_flags`, `_fuzzy_decision`, `_fuzzy_ids`, `_hybrid_prediction` (other than adding the new guard), `_flag_fuzzy_boundary_violation`, `_strategy_metrics`, or `_eligibility`.
- Adding new fields to `StrategyPrediction`, `CaseObservation`, or the per-case `case_results` record.
- Modifying the policy dataclass, the policy grid generator, the JSON report schema, the diagnostic surface, the CLI surface, or the shadow service.
- Modifying the recognizer, the embedding client, the Ollama configuration, the vector data, or the fuzzy threshold.
- Modifying the calibration dataset (no new cases, no removed cases, no renamed cases).
- Disabling Ruff rule `C401` or any other rule; adding `noqa` comments.
- Touching the FastAPI routers, services, repositories, schemas, handlers, resolvers, recognizers, orchestrators, the pending-context chain, the seeds, the migrations, the settings, the dataset, the `pyproject.toml`, the `ruff.toml`, the `alembic.ini`, or any test file outside the new `test_product_recognition_calibration_4_11_7.py`.
- Running Ruff with `--unsafe-fixes` to auto-apply any rewrite.
- Synchronizing any capability spec or archiving the change (per `openspec/config.yaml`, sync and archive are explicit user commands, not part of `/opsx:apply`).

## Decisions

### Decision 1: Add the guard as a single positional `if` block ABOVE the existing 4.11.5 guard in `_hybrid_prediction`

**Rationale.** The Subphase 4.11.5 guard is a positional `if` block at the top of `_hybrid_prediction` (`runner.py:203-215`). The Subphase 4.11.7 guard is the structural counterpart: a second positional `if` block immediately above it. The 4.11.7 guard checks `observation.fuzzy_decision == "unique"` AND `not observation.vector_ids`. If both conditions are met, the guard returns a `StrategyPrediction` built from the fuzzy observation directly (the same shape as the 4.11.5 guard returns). If either condition fails, the function falls through to the existing 4.11.5 guard and then to the existing scoring path. This keeps the new code symmetric with the existing pattern and makes the 4.11.7 guard self-documenting.

The 4.11.5 guard handles `catalog_scope == "pending_product_selection_restricted"` AND `fuzzy_decision == "ambiguous"` — a case that the 4.11.7 guard does NOT match (because the 4.11.7 guard requires `fuzzy_decision == "unique"`). The two guards are therefore mutually exclusive on `fuzzy_decision`, and there is no risk of the new guard short-circuiting the 4.11.5 guard for any case.

**Alternatives considered.**

- **Move the new guard BELOW the existing 4.11.5 guard** — equivalent semantically (the two guards are mutually exclusive on `fuzzy_decision`). Placing the new guard above is purely a readability choice so the most general guard (`fuzzy_unique + empty_vector`) is the first positional check. Rejected because the 4.11.5 guard is more specific to a particular scope, and placing the more general guard first matches the conventional ordering ("check the most common case first"). Both orderings are correct.
- **Combine the two guards into a single conditional with `or`** — would conflate two unrelated cases. Rejected for clarity: the 4.11.5 guard handles "fuzzy says ambiguous, vector would otherwise promote to unique at a restricted scope"; the 4.11.7 guard handles "fuzzy says unique, vector is silent and the threshold gates degrade it to unknown". They have different semantics, different return shapes (the 4.11.5 guard returns `decision="ambiguous"` and discards the vector; the 4.11.7 guard returns the fuzzy prediction verbatim), and different rationale. Combining them would obscure both.
- **Apply the guard in `_decision` instead of `_hybrid_prediction`** — `_decision` is called from `_prediction` (which is also used for the pure-fuzzy `_prediction` call at `runner.py:832` and for the pure-vector `_prediction` calls inside `fuzzy_predictions`). Applying the guard in `_decision` would also affect the fuzzy-prediction path (which already returns `unique` for `len(ranking) == 1` regardless of threshold) and could mask real defects in the policy grid. Rejected because the guard is specifically about the hybrid path where the vector contribution is absent; it must live in `_hybrid_prediction`.

### Decision 2: The guard returns the fuzzy prediction verbatim, NOT the fuzzy prediction through `_prediction`

**Rationale.** The guard returns a `StrategyPrediction` constructed directly from `observation.fuzzy_ids` and `observation.fuzzy_scores`, with `canonical` and `alias` computed by `_exact_flags(case, observation.fuzzy_ids)`. This is the same shape the 4.11.5 guard returns (which uses `_exact_flags(case, observation.fuzzy_ids)` and returns `observation.fuzzy_ids[0]` as `top_id`, `observation.fuzzy_ids` as `ranking`, and `observation.fuzzy_scores` as `scores`).

The reason NOT to call `_prediction(case, observation.fuzzy_ids, observation.fuzzy_scores, None)` is that `_prediction` with `policy=None` uses the id-based fallback (`"unique" if len(ranking) == 1 else "ambiguous" if len(ranking) > 1 else "unknown"`) and bypasses `_exact_flags` for `canonical` / `alias`. For the 4.11.7 guard, the canonical / alias flags must still be honored (a fuzzy_unique match that ALSO matches an alias is still a fuzzy_unique match, and a fuzzy_unique match that ALSO matches the canonical name is still a fuzzy_unique match — but a fuzzy_unique match that does NOT match either canonical or alias is still a fuzzy_unique match for the purposes of this guard). Computing `_exact_flags(case, observation.fuzzy_ids)` explicitly preserves the symmetry with the 4.11.5 guard's return shape and documents the intent.

**Alternatives considered.**

- **Return `_prediction(case, observation.fuzzy_ids, observation.fuzzy_scores, policy, observation.fuzzy_decision)`** — this would re-enter the scoring formula. The intent of the 4.11.7 guard is to BYPASS the scoring formula; re-entering `_prediction` defeats the purpose. Rejected.
- **Return `_prediction(case, observation.fuzzy_ids, observation.fuzzy_scores, None)`** — uses the id-based fallback but bypasses `_exact_flags`. Equivalent for the four failing cases (none of them match canonical or alias), but loses the canonical / alias flags in the returned `StrategyPrediction` and is therefore inconsistent with the 4.11.5 guard. Rejected for symmetry.

### Decision 3: Hand-write the new test file `test_product_recognition_calibration_4_11_7.py` instead of extending the 4.11.5 file

**Rationale.** Subphase 4.11.5 pinned its fixes in `test_product_recognition_calibration_4_11_5.py` (archived at `openspec/changes/archive/2026-08-05-subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/`). Subphase 4.11.7 introduces a new behaviour (the `fuzzy_unique + empty_vector` guard) and therefore needs a dedicated file to pin the new behaviour without growing the 4.11.5 file beyond its natural scope.

The new file is small and focused: it pins (1) the four named cases become `unique` with the correct `producto_presentacion_id`; (2) the 4.11.5 `ambiguous-empanada-carne` case continues to return `ambiguous`; (3) `false_positives.count` remains `0`; (4) `incorrect_unique_decisions.count` remains `0`; (5) the complete 47-case calibration remains `eligible`. The test count is determined by what the file needs to pin the closure criterion; no specific number is required.

Helpers that are short enough to inline are duplicated inline if necessary. No shared helper module is required.

**Alternatives considered.**

- **Extend `test_product_recognition_calibration_4_11_5.py`** — would conflate the 4.11.5 fix scope (the `pending_product_selection_restricted` + `fuzzy_ambiguous` guard) with the 4.11.7 fix scope (the `fuzzy_unique + empty_vector` guard). Both guards must remain auditable as separate units; future contributors reviewing the 4.11.5 change must be able to read its test surface in isolation. Rejected for clarity.
- **Add a single regression test to the existing `test_product_recognition_calibration_runner.py`** — would couple the new behaviour to the broader runner test file and would not provide a dedicated location for the 4.11.7 audit trail. Rejected for the same reason.

### Decision 4: Do not modify the calibration dataset

**Rationale.** The four failing cases already exist in the dataset with stable `case_id`, input text, catalog scope, expected decision, and expected `producto_presentacion_id`. The runner's evaluation logic is the only thing that needs to change. Adding new cases (e.g. for future regressions) is out of scope; removing cases would break the Subphase 4.11–4.11.6 baselines. The 47-case baseline is the source of truth for the calibration chain.

**Alternatives considered.**

- **Add a new "fuzzy_unique + empty_vector" calibration case category** — would expand the dataset and the runner's metric surface. Out of scope; the dataset is closed under Subphase 4.11.1 / 4.11.4. Rejected.
- **Rename the four failing cases to mark them as "expected hybrid_unknown"** — would defeat the purpose of the fix. Rejected.

### Decision 5: Re-run the calibration end-to-end after the fix and produce `calibration_after.json` + `calibration_after_diagnose.json`

**Rationale.** The Subphase 4.11.5 convention is to regenerate the calibration artifacts under the change's `diagnostics/` directory. The new artifacts document the post-fix state and provide a reference for future subphases. The pre-fix state is documented at `openspec/changes/archive/2026-08-05-subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/diagnostics/`; the 4.11.7 change references the archive by path and produces its own `before.json` + `before.diagnose.json` only if needed for the verification tasks.

**Alternatives considered.**

- **Skip the re-run and rely solely on the focused regression test file** — would lose the calibration-wide evidence. The 47-case calibration is the Subphase 4.11 contract surface; the post-fix artifacts are part of that contract. Rejected.
- **Modify the 4.11.5 diagnostics in place** — would overwrite the 4.11.5 baseline. The 4.11.5 change is archived and its diagnostics are immutable. Rejected.

## Risks / Trade-offs

- **[Risk] The new guard could mask a real defect in the policy grid or the scoring formula** → Mitigation: the guard is purely additive (it can only force `unique`; it never forces `ambiguous` or `unknown`); it short-circuits BEFORE the scoring rule; it only fires when `fuzzy_decision == "unique"` AND `len(observation.vector_ids) == 0` (a precondition that the runner has already validated). The Subphase 4.11.5 guard is the symmetric pattern, and the Subphase 4.11.5 baseline confirms the symmetric pattern is safe. The guard does NOT fire for `fuzzy_decision == "ambiguous"` (which the 4.11.5 guard handles), `fuzzy_decision == "unknown"` (the existing scoring rule applies), or non-empty `vector_ids` (the existing scoring rule applies). The guard is therefore narrowly scoped to the four failing cases and cannot regress any other case.
- **[Risk] The new guard could introduce a false positive** → Mitigation: the guard returns the fuzzy prediction verbatim, which has already been validated as `unique` by `_fuzzy_decision`. The fuzzy recognizer is the production-grade recognizer used by `agregar_producto` / `modificar_producto` / `quitar_producto`, and its `unique` decisions have been independently audited across the Subphase 4.11 chain. The `false_positives` metric is pinned to `0` in the focused regression suite and in the post-fix calibration artifact.
- **[Risk] The new guard could regress the Subphase 4.11.5 guard** → Mitigation: the two guards are mutually exclusive on `fuzzy_decision`. The 4.11.5 guard handles `fuzzy_decision == "ambiguous"`; the 4.11.7 guard handles `fuzzy_decision == "unique"`. Both guards can coexist in `_hybrid_prediction` without overlap. The `ambiguous-empanada-carne` case (the 4.11.5 canonical example) has `fuzzy_decision == "ambiguous"` and therefore cannot trigger the 4.11.7 guard. The focused regression suite pins both guards.
- **[Risk] The new guard could affect the `incorrect_unique_decisions` metric** → Mitigation: the four failing cases are `expected_decision == "unique"`, `actual_fuzzy_decision == "unique"`, `actual_hybrid_decision == "unknown"`, and the guard forces `actual_hybrid_decision == "unique"` with `top_id` matching the fuzzy top-1. The `incorrect_unique_decisions` metric is the count of `predicted_unique` cases where `_correct` returns `False`. For the four cases, `_correct` is `prediction.decision == case["expected_decision"] and prediction.top_id == case.get("expected_producto_presentacion_id")`. The guard's output has `decision == "unique"` and `top_id == fuzzy_ids[0] == expected_producto_presentacion_id`, so `_correct` returns `True` and the metric does not increase.
- **[Risk] The new guard could be misread as "fuzzy always wins"** → Mitigation: the guard has a specific precondition (`fuzzy_decision == "unique" AND not vector_ids`). The guard does NOT fire for `fuzzy_decision == "ambiguous"` (the 4.11.5 guard handles that case at the `pending_product_selection_restricted` scope, and elsewhere the existing scoring rule applies). The guard does NOT fire for `fuzzy_decision == "unknown"` (the existing scoring rule applies and produces `unknown`). The guard does NOT fire when `vector_ids` is non-empty (the existing scoring rule applies and the vector contribution is honored). The guard is therefore narrowly scoped and cannot be generalized to "fuzzy always wins".

## Migration Plan

This change has no deployment surface. The calibration runner is exercised only by the offline calibration pipeline (the runner, the shadow service, the CLI, the eligibility verifier, and the focused regression suites). The runner's output is consumed only by the calibration reports, the dataset fingerprints, and the focused regression test files. All paths converge on the JSON report and the per-case `case_results`, both of which have an unchanged schema.

Rollback is a 1-file git revert of `backend/services/product_recognition_calibration_runner.py` (the new guard is removed) plus a 1-file revert of the test file. No data migration, no schema change, no cache invalidation. The rollback re-introduces the four `real_hybrid_recognizer_failure` cases, which is the only operational risk, and the rollback is described in `git log` for auditability.

## Open Questions

(none — the guard is fully determined by the existing diagnostics. The four failing cases are documented in `openspec/changes/archive/2026-08-05-subphase-4-11-5-reduce-residual-fuzzy-failures-and-false-positives/diagnostics/after.diagnose.json` and the pre-existing `_hybrid_prediction` flow. No design-time ambiguity remains.)