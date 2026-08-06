## Context

The Subphase 4.11 calibration runner was delivered as an offline, observational, deterministic tool that compares the fuzzy baseline against the hybrid observational recognizer across a versioned `schema_version: 3` dataset of 47 cases (11 preserved Subphase 4.11 cases + 36 new `comercio_id=1` database-backed cases). The most recent calibration report shows:

- fuzzy decision accuracy: `0.1282` (5/39)
- hybrid decision accuracy: `0.1538` (6/39)
- fuzzy false unknowns: `34/36`
- hybrid false unknowns: `12/36`
- hybrid incorrect ambiguities: `21/22`
- hybrid presentation resolution accuracy: `7/39`
- infrastructure failures: `0`
- Subphase 4.12 eligibility status: `not_eligible` (formal reason `latency_budget_failed`)

The latency budget failure is real but secondary; the dominant functional problem is that legitimate cases are being scored as `unknown` or `ambiguous` long before the hybrid policy could ever be exercised. Without diagnosis, any change here would either redesign the recognizer (forbidden by the project rule), raise thresholds (forbidden by the project rule), or weaken the dataset (forbidden by the project rule). The smallest robust correction requires:

1. A closed mismatch-category taxonomy capable of expressing every incorrect case.
2. A per-case diagnostic that exposes the actual fuzzy and hybrid decisions, the resolved numeric IDs, the normalized comparison the evaluator used, and the category.
3. A canonical presentation identifier contract so the evaluator never silently compares numeric `producto_presentacion.id` against `presentacion.codigo`, `presentacion.id`, or normalized descriptions.
4. Targeted dataset corrections backed by catalog evidence, leaving the 11 preserved Subphase 4.11 cases and every other case untouched.
5. A regenerated inventory and a refreshed calibration report that proves the correction is reproducible from the documented command.

The work is concentrated in `backend/cli/calibrate_product_recognizer.py`, the calibration runner / evaluator / normalizer modules, the dataset validator, and focused tests. The Subphase 4.11 and 4.11.1 specs set the non-negotiable invariants; the new `calibration-evaluation-mismatch-diagnosis` capability defines the diagnostic surface.

## Goals / Non-Goals

**Goals:**

- Add a deterministic `--diagnose` mode to the existing calibration CLI that emits one stable per-case entry with `case_id`, `input_text`, `category`, `shape`, `expected_decision`, `expected_producto_presentacion_id`, `expected_presentacion_id`, `actual_fuzzy_decision`, `actual_fuzzy_producto_presentacion_id`, `actual_fuzzy_presentacion_id`, `actual_fuzzy_candidate_ids`, `actual_hybrid_decision`, `actual_hybrid_producto_presentacion_id`, `actual_hybrid_presentacion_id`, `actual_hybrid_candidate_ids`, `normalized_id_used_by_evaluator`, `presentation_resolution_result`, `mismatch_category`, and (when applicable) `evidence`.
- Classify every incorrect case into exactly one of the ten documented categories using only catalog evidence already available from the runner's per-case records.
- Enforce a single canonical presentation identifier (`producto_presentacion.id`) for every comparison and normalization step in the runner and evaluator.
- Emit a `mismatch_category_counts` aggregate in the JSON report alongside the existing fields. Categories with zero incorrect cases SHALL remain at zero; the diagnostic SHALL NOT fabricate or force examples merely to populate empty categories.
- Correct only demonstrated dataset / seed_refs / normalization / decision-mapping defects, leaving the 11 preserved Subphase 4.11 cases and every other case untouched.
- Regenerate the inventory and re-run the calibration to produce a new report from the documented command.
- Add focused regression coverage for the diagnostic mode, the taxonomy, the canonical-identifier consistency, and each demonstrated mismatch category.

**Non-Goals:**

- Redesigning the fuzzy recognizer, the hybrid observer, the policy grid, or the metric denominators.
- Changing thresholds, weights, or the latency budget.
- Activating `PRODUCT_RECOGNIZER_MODE=hybrid` or any other runtime change.
- Changing embeddings, Ollama configuration, vector data, or vector dimensions.
- Synchronizing the specifications or archiving the change during implementation.
- Wholesale regeneration of the dataset; only documented-stale cases are corrected.
- Weakening the dataset, raising the `required_improvement`, or narrowing the `false_positive_tolerance` to lift metrics.
- Changing HTTP contracts, handlers, resolvers, pending contexts, intents, orders, or transaction semantics.

## Decisions

1. **Diagnostic lives inside the existing CLI surface as an opt-in `--diagnose` flag.** We add `--diagnose` and `--diagnose-output` to `python -m backend.cli.calibrate_product_recognizer` rather than introducing a new CLI module. This preserves the Subphase 4.11 CLI session ownership, exit-code semantics, and atomic-output contract, and the new capability's spec only needs to declare the new flags. A new CLI module would have duplicated session management, output writing, and parameter validation, and would have weakened the Subphase 4.11 invariant by introducing two ways to invoke the same calibration.

2. **Mismatch taxonomy is a closed, lowercase snake-case enum defined next to the runner.** The ten categories and their definitions live in a single module-level `MISMATCH_CATEGORY` enum (or `Final` set of string constants) that the runner, the evaluator, and the JSON report reader all import. This avoids string drift across modules and makes the taxonomy enforceable at the type level. Each category is a simple `str` `Enum` so JSON serialization stays human-readable.

3. **Per-case classification is a pure function of the runner's existing records.** The classifier inspects the already-captured `expected_decision`, `expected_producto_presentacion_id`, `actual_fuzzy_decision`, `actual_fuzzy_producto_presentacion_id`, `actual_hybrid_decision`, `actual_hybrid_producto_presentacion_id`, `actual_fuzzy_candidate_ids`, `actual_hybrid_candidate_ids`, the case's `id_comercio`, and the resolved `seed_refs` from the inventory. No new database calls are needed at diagnostic time. The classifier is a single function that returns the category and an optional `evidence` string; this lets the new capability's spec be expressed as a contract without prescribing implementation details.

4. **Canonical identifier contract is enforced by extracting one helper.** A new `normalize_canonical_id(record)` helper resolves the canonical `producto_presentacion.id` from a recognizer result row, an inventory entry, an expected seed reference, or a candidate list. The runner and evaluator call this helper at every comparison site. Any previous callsite that compared `presentacion.codigo` strings, `presentacion.id` numbers, or normalized descriptions against a `producto_presentacion.id` is replaced with a helper call. This is the smallest change that fixes the silent dual-id bug without redesigning the recognizer.

5. **Dataset corrections are case-by-case with explicit structured evidence.** Each corrected case is committed in the same PR as the diagnostic that triggered it. Because JSON does not allow comments, correction evidence is stored in an optional `correction_evidence` object attached to the corrected case entry, containing `mismatch_category` (one of the ten documented categories), `reason` (a human-readable explanation of the demonstrated defect), and `catalog_reference` (the catalog artifact — a `seed_refs` key, a numeric `producto_presentacion.id`, or a comparable identifier — that supports the correction). The field is only present on corrected cases; uncorrected cases (including all 11 preserved Subphase 4.11 cases) do not carry it. The 11 preserved Subphase 4.11 cases are never touched. The inventory regeneration step is the same `validate_dataset` + `build_seed_refs_inventory` documented in Subphase 4.11.1, and the new inventory is committed to the change root. The dataset's `schema_version` remains `3`; no new schema is introduced. The dataset validator is extended to accept the optional `correction_evidence` object without rejecting uncorrected cases.

6. **The runner tracks the inventory generation timestamp per dataset.** A new `inventory_generated_at` field on the dataset (and a parallel `inventory_path` if the inventory is checked into the change root) lets the runner detect that the inventory is stale relative to the dataset. The runner refuses to run when the dataset's `seed_refs` has changed since the inventory was generated. This keeps the "no stale or cross-commerce IDs" invariant enforceable without a separate lint step.

7. **Regression coverage is one new test file plus targeted additions to the existing 4.11.1 file.** The new `backend/tests/test_product_recognition_calibration_4_11_3.py` covers the diagnostic mode, the taxonomy, the canonical-identifier helper, the inventory-refusal path, and each demonstrated mismatch category. Existing 4.11 and 4.11.1 tests remain untouched and continue to pass. The new tests do not duplicate the existing ones; they only assert the new behaviors.

8. **Latency budget is not raised.** The Subphase 4.11.2 → Subphase 4.11.3 chain has a documented `latency_budget_failed` verdict, but raising the budget in this subphase would paper over the real problem. The new report keeps the existing 500 ms `latency_budget_ms_p95` and reports the real eligibility verdict (which may still be `not_eligible` with `latency_budget_failed` as the reason, but with the functional categories resolved).

9. **Hybrid mode is not activated regardless of the new report.** The runner runs in observational mode only; `PRODUCT_RECOGNIZER_MODE` remains untouched; the calibration report remains observational. Activation is reserved for a future subphase that consumes the new report's evidence.

10. **Roadmap entry is updated to the standard completed-entry format.** The pending `### Implement Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch. [ ]` line in `openspec/specs/project.md` is replaced with a `### Subphase 4.11.3 — Diagnose and Correct Calibration Evaluation Mismatch [x] — completed` entry following the exact structure used by Subphase 4.11.2.

## Risks / Trade-offs

- [Diagnostic mode changes the CLI exit-code semantics] → The diagnostic mode uses the same exit-code rules as the existing mode (non-zero only on invalid dataset, invalid configuration, database failure, or total calibration failure). A focused test pins this and the diagnostic mode is documented in the new capability's spec.
- [Mismatched identifier representations slip past the refactor] → The new `normalize_canonical_id` helper is the only allowed comparison entry point; the existing `compare_*` helpers are refactored through it. A new strict-mypy and Ruff sweep plus a focused regression test on a synthetic mixed-id case pins the behavior.
- [Dataset corrections accidentally widen `allowed_candidate_ids` or remove a restricted ID] → The dataset validator from Subphase 4.11.1 already rejects any `restricted_candidate_ids` overlap with `allowed_candidate_ids`; the new `inventory_generated_at` field forces regeneration after any change. The runner's inventory-refusal path refuses to run against a stale inventory, so any change is enforced to be backed by a fresh inventory.
- [Multiple mismatch categories could apply to one case] → The classifier returns the first matching category in the documented evaluation order. The evaluation order is documented in the new capability's spec and is enforced by the mismatch-category unit test. The `mismatch_category_counts` aggregate still sums to the total incorrect cases.
- [The fuzzy recognizer is actually wrong for some cases and the diagnostic flags it as `real_fuzzy_recognizer_failure`] → The project rule forbids changing the recognizer in this subphase. The diagnostic captures the evidence in the report and the failure is left for a future subphase. The new report lists these as remaining real recognizer failures.
- [Broad test churn obscures the small fix] → The new tests are confined to a single new file plus the new behaviors. The existing 4.11 and 4.11.1 tests are untouched. The exception is the existing dataset file, which is corrected only where the diagnostic proves the expectation is wrong.
- [The new report still shows `not_eligible` for `latency_budget_failed`] → This is the documented behaviour and is preserved. The goal of this subphase is to make the functional categories correct, not to flip the verdict. A future subphase can address the latency budget with its own evidence.

## Migration Plan

This subphase has no production runtime migration. The migration is purely offline and is the documented workflow:

1. Implement the diagnostic mode, the taxonomy, the canonical-identifier helper, and the inventory-refusal path.
2. Run the diagnostic against the current `schema_version: 3` dataset to capture the per-case mismatch categories.
3. For each case flagged under `invalid_dataset_expectation`, `stale_seed_reference`, `commerce_scope_mismatch`, `product_id_mismatch`, `presentation_id_mismatch`, `output_normalization_mismatch`, or `decision_mapping_mismatch`, correct the dataset (or the runner) with explicit evidence.
4. Regenerate the inventory and commit it to the change root.
5. Re-run the full calibration and commit the new report.
6. Update the project roadmap entry.

Rollback is a single `git revert` of the change; the dataset is corrected case-by-case and the runner changes are isolated to the offline calibration flow. No runtime call site, setting, factory, recognizer contract, handler, resolver, pending context, intent, order, response, persistence contract, HTTP endpoint, embedding model, Ollama configuration, or vector data is touched.

## Open Questions

- Which concrete cases will be flagged under which category? The diagnostic will produce the answer; until it runs, the implementation must not assume which cases change.
- Whether the new report's eligibility status will remain `not_eligible` (with the same or a different reason) or will become `eligible` depends on the diagnostic. The implementation must not rely on either outcome.
- Whether the inventory needs to be committed to the change root or to a stable path under `backend/data/` is a small choice that will be made when the inventory is regenerated; the new capability's spec supports both by leaving the `inventory_ref` path open.
