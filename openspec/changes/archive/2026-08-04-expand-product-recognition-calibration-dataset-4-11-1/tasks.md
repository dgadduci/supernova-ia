## 1. Inventory and seed references for comercio_id=1

- [x] 1.1 Query the seeded database for every active `producto`, `producto_presentacion`, `presentacion`, and `producto_alias` row for `id_comercio = 1` and capture the resulting `producto_presentacion_id` values plus the canonical product names and presentation codes. Use the project's existing SQLAlchemy session factory; do not introduce a new persistence path.
- [x] 1.2 Add a repository-supported inventory step at `backend/scripts/calibration_inventory.py` that runs in `--mode regenerate` or `--mode validate`. Scope it exclusively to regenerating and validating the top-level `seed_refs` map used by the new `commerce_dynamic_database` cases with `id_comercio=1`; it must not inspect or reinterpret preserved `in_memory` cases. It exits non-zero with a clear, structured message per failure mode (missing, nonexistent, cross-commerce, ambiguous).
- [x] 1.3 Build a top-level `seed_refs` map in `backend/data/product_recognition_calibration_cases.json` mapping opaque symbolic keys used by the new `commerce_dynamic_database` cases (e.g. `pp_empanada_pollo`, `pp_pizza_muzzarella_chica`) to resolved `producto_presentacion_id` values for `comercio_id=1`. Numeric IDs are NEVER used as portable symbolic references, and preserved `in_memory` fixture IDs are not added or reinterpreted.
- [x] 1.4 Run the inventory step in `--mode regenerate` to write only the `seed_refs` entries used by the new `commerce_dynamic_database` cases with `id_comercio=1`, then run `--mode validate` over that same scope. Commit the updated dataset only after validation passes.
- [x] 1.5 Validate that every alias row for `comercio_id=1` is loadable and that names with diacritics resolve correctly (casefold, accent-insensitive comparison) so the new cases can reference them.
- [x] 1.6 Confirm the inventory step lives outside the runtime code path. Runtime code MUST NOT import `backend.scripts.calibration_inventory`, `backend.tests.*`, or any fixture module. The runner resolves `seed_refs` through its own validation, not through the inventory step.

## 2. Expand the calibration dataset

- [x] 2.1 Keep the existing 11 Subphase 4.11 cases verbatim — including their `catalog_scope: "in_memory"` fixtures, their `catalogs[*].entries` lists, and their expected outcomes — and add new cases for `comercio_id=1` using `catalog_scope: "commerce_dynamic_database"` and an empty `catalogs[*].entries` list. The 11 preserved cases are NOT counted as `comercio_id=1` cases and are excluded from the per-commerce minimum.
- [x] 2.2 Add at least one case for each required input shape: exact canonical, alias, fuzzy misspelling, colloquial wording, product+presentation, quantity word, ambiguous request, unknown product, restricted candidate set, semantically similar product, and a fuzzy/vector disagreement case.
- [x] 2.3 Use `expected_producto_presentacion_id_ref` (resolved from `seed_refs`) for every new `comercio_id=1` case and `expected_decision` of `unique`, `ambiguous`, or `unknown` per the input shape.
- [x] 2.4 Populate `allowed_candidate_ids` and `restricted_candidate_ids` using only `producto_presentacion_id` values that exist in the database for `comercio_id=1`; for commerce isolation, restrict to a single `id_comercio` and avoid including candidates from other comercios.
- [x] 2.5 Assign `category` from `{"canonical", "alias", "ambiguous", "unknown", "restricted", "commerce_isolation", "baseline"}` and ensure every category is present at least once across the new cases.
- [x] 2.6 Bump the dataset `schema_version` to `3` and add an optional top-level `eligibility` block with `primary_metric = "decision_accuracy"`, `required_improvement = 0.0`, `false_positive_tolerance = 0.0`, and `latency_budget_ms_p95 = 500`.
- [x] 2.7 Confirm the final dataset totals 30–50 cases inclusive of the 11 preserved Subphase 4.11 cases (47 total), AND contains at least 30 evaluable cases for `comercio_id=1` (36 added), AND contains no production customer data.

## 3. Extend dataset validation

- [x] 3.1 Update `validate_dataset` in `backend/services/product_recognition_calibration_policy.py` to accept `schema_version` equal to `3` while preserving the existing `1` and `2` validation paths.
- [x] 3.2 Add validation for the optional `eligibility` block when `schema_version >= 3`: required keys present, `primary_metric` in the allowed set, `required_improvement` and `false_positive_tolerance` non-negative finite numbers, `false_positive_tolerance` in `[0, 1]`, `latency_budget_ms_p95` non-negative finite number.
- [x] 3.3 Keep the existing dataset fingerprint computation unchanged; the new `eligibility` block participates in the canonical JSON because the dataset's whole body is hashed.

## 4. Extend the runner to read dataset eligibility and validate seed_refs

- [x] 4.1 Update `ProductRecognitionCalibrationRunner.run` in `backend/services/product_recognition_calibration_runner.py` so that when `eligibility is None` and the dataset has an `eligibility` block, the runner uses the dataset block (mapping `latency_budget_ms_p95` to `latency_budget`) as the eligibility input.
- [x] 4.2 Keep the existing `eligibility` argument path intact: when an explicit `eligibility` argument is supplied, the dataset block is ignored and the explicit argument is used.
- [x] 4.3 Keep the existing `pending` fallback when both the dataset `eligibility` block and the `eligibility` argument are absent.
- [x] 4.4 For each case whose `catalog_scope == "commerce_dynamic_database"`, resolve and validate every `expected_producto_presentacion_id_ref` and validate every `allowed_candidate_ids` / `restricted_candidate_ids` entry against that case's own `id_comercio` before evaluating that case. The resolution does NOT import the inventory step or any test infrastructure.
- [x] 4.5 Fail clearly before evaluating the affected `commerce_dynamic_database` case when a symbolic reference is missing, a resolved or candidate ID is nonexistent, an ID belongs to another commerce, or symbolic resolution is ambiguous. Each failure identifies the case, reference or candidate, offending value, and expected commerce scope.
- [x] 4.6 Preserve the existing `in_memory` embedded-catalog validation and evaluation path: do not validate candidate IDs against the seeded database, do not force `id_comercio=1`, and do not reinterpret fixture IDs as production database IDs.

## 5. Focused tests

- [x] 5.1 Add a focused test asserting `validate_dataset` accepts the expanded `schema_version: 3` dataset and rejects malformed `eligibility` blocks (missing keys, non-numeric values, negative latency budget, unsupported primary metric, out-of-range false-positive tolerance, non-finite numbers).
- [x] 5.2 Add a focused test asserting `validate_dataset` continues to accept `schema_version: 2` datasets unchanged.
- [x] 5.3 Add a focused test asserting `ProductRecognitionCalibrationRunner.run` consumes the dataset `eligibility` block when no explicit `eligibility` argument is supplied, and uses the explicit argument when supplied.
- [x] 5.4 Add a focused test that runs the inventory step against the seeded database for the new `commerce_dynamic_database` cases with `id_comercio=1`, resolves their `seed_refs` entries, and confirms every referenced `producto_presentacion_id` exists for `comercio_id=1`; do not include preserved `in_memory` cases in inventory validation.
- [x] 5.5 Add focused tests asserting that each `commerce_dynamic_database` case validates every expected reference and every allowed/restricted candidate against its own `id_comercio`, and fails clearly and separately for missing, nonexistent, cross-commerce, and ambiguous references before evaluating that case.
- [x] 5.6 Add a focused regression test asserting all in-memory cases remain verbatim, use their embedded catalogs, do not query the seeded database to validate candidate IDs, retain their own `id_comercio`, and do not reinterpret fixture IDs as production database IDs.
- [x] 5.7 Add a focused test asserting the runner's import graph does not import `backend.tests.*`, `backend.scripts.calibration_inventory`, or any fixture module. The resolution path stays inside the runner's own validation and the existing SQLAlchemy session factory.
- [x] 5.8 Add a focused test asserting the expanded dataset covers every required input shape category and every allowed category in `{"canonical", "alias", "ambiguous", "unknown", "restricted", "commerce_isolation", "baseline"}`, AND has at least 30 evaluable `commerce_dynamic_database` cases for `comercio_id=1`, AND has between 30 and 50 cases total.
- [x] 5.9 Add a focused test asserting the calibration report is deterministic for the expanded dataset (sorted keys, stable list order, finite numbers, byte-identical for equal recorded observations).

## 6. Implementation verification

- [x] 6.1 Run the repository-provided formatter, linter, and strict typecheck commands over the touched files and resolve failures.
- [x] 6.2 Run the new focused tests and the existing 4.11 focused test suite plus the Subphase 4.5–4.10.1 regression tests; resolve failures.
- [x] 6.3 Confirm fuzzy remains the authoritative runtime recognizer, hybrid remains observational, no runtime contract changes were introduced, and no `PRODUCT_RECOGNIZER_MODE=hybrid` activation, handlers, resolvers, pending contexts, intents, orders, responses, persistence contracts, canonical specs, or runtime settings changed.
- [x] 6.4 Confirm runtime code does not import the inventory step, `backend.tests.*`, or any fixture module. The inventory step is a tool script callable from the project root, not a runtime dependency.
- [x] 6.5 Run the inventory step in `--mode validate` against the final dataset and confirm it exits zero while considering only `seed_refs` used by the new `commerce_dynamic_database` cases with `id_comercio=1`.
- [x] 6.6 If the database is missing embeddings for any `comercio_id=1` product referenced by the new cases, run the project's embedding seeding flow.
- [x] 6.7 Execute `python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output reports/calibration-comercio-1.json --commerce-id 1` and capture the report path and the CLI summary.
- [x] 6.8 Report the total case count, the `comercio_id=1` evaluable case count, the category counts, the fuzzy metrics, the hybrid metrics, the selected policy, the infrastructure failures, and the eligibility status with reasons; do not run `/opsx:sync` or `/opsx:archive`.
