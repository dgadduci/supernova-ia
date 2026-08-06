## Context

Subphase 4.11 delivered an offline calibration runner for the observational hybrid product recognizer. The runner consumes a JSON dataset at `backend/data/product_recognition_calibration_cases.json` (currently `schema_version: 2`, 10 cases). The dataset is dual-sourced:

- **In-memory fixture cases** (`catalog_scope: "in_memory"`) reuse existing test fixtures from `backend/tests/`. They cover exact canonical, alias, fuzzy misspelling, ambiguous, unknown, quantity, and a couple of restricted cases. Each case carries a `catalog_fixture` key that points to a `catalogs` entry whose `entries` list is passed to the fuzzy recognizer's `recognize(text, catalog)` call. These are the 10 preserved Subphase 4.11 cases; their `id_comercio` values are not 1 and they are **not** counted as `comercio_id=1` cases.
- **Commerce dynamic database cases** (`catalog_scope: "commerce_dynamic_database"`) carry an empty `entries` list and rely on the vector search service to fetch the real catalog from the database at runtime. They use `expected_producto_presentacion_id_ref` to defer the expected product ID to a runtime-resolved seed key.

The current dataset is too small for `comercio_id=1` and uses synthetic fixture catalogs that do not reflect any real commerce. The runner accepts an `eligibility` argument for the Subphase 4.12 gate, but no dataset or CLI currently carries the explicit inputs (`primary_metric`, `required_improvement`, `false_positive_tolerance`, `latency_budget_ms_p95`), so the CLI produces `pending` on every run and operators have to inject the inputs by hand.

Subphase 4.11.1 must make the calibration usable for `comercio_id=1` by adding real database-backed cases that cover the 80/20 of representative input shapes, must define the eligibility inputs in the dataset so the CLI can emit a real verdict, and must ensure the `seed_refs` map is regenerated or validated by an explicit repository-supported inventory step rather than maintained by hand.

## Goals / Non-Goals

**Goals:**

- Expand the calibration dataset to a final total of 30–50 cases inclusive of the 10 preserved Subphase 4.11 cases.
- Final dataset contains at least 30 evaluable cases for `comercio_id=1`, in addition to the 10 preserved cases for other comercios. The preserved cases for other comercios remain in the dataset but are excluded from the `comercio_id=1` minimum.
- Every new `comercio_id=1` case uses `catalog_scope: "commerce_dynamic_database"`, `id_comercio: 1`, and references real `producto`, `producto_presentacion`, `presentacion`, and `producto_alias` rows that exist in the seeded database.
- Cover the 80/20 of representative input shapes for `comercio_id=1`: exact canonical, alias, fuzzy misspelling, colloquial wording, product+presentation, quantity words, ambiguous requests, unknown products, restricted candidate sets, semantically similar products, and cases where fuzzy and vector may disagree.
- Define an explicit repository-supported inventory step scoped to regenerating or validating the top-level `seed_refs` entries used by the new `commerce_dynamic_database` cases with `id_comercio=1`. It queries only that seeded commerce and is the single source of truth for which `producto_presentacion_id` belongs to each such symbolic key. Numeric IDs are NEVER used as portable symbolic references; the `seed_refs` map uses opaque symbolic keys only.
- Runtime code MUST NOT import test infrastructure to resolve `seed_refs`. The inventory step lives outside the runtime code path.
- Apply database-backed reference validation only to cases whose `catalog_scope` is `commerce_dynamic_database`. For each such case, before evaluating that case, resolve and validate every `expected_producto_presentacion_id_ref` and validate every `allowed_candidate_ids` / `restricted_candidate_ids` entry against the case's own `id_comercio`. Fail clearly for missing, nonexistent, cross-commerce, or ambiguous references, identifying the case, reference or candidate, offending value, and expected commerce scope.
- Preserve the existing embedded-catalog validation and evaluation path for all `in_memory` cases. Do not validate their candidate IDs against the seeded database, force `id_comercio=1`, or reinterpret fixture IDs as production database IDs.
- Carry the explicit eligibility inputs on the dataset (`primary_metric`, `required_improvement`, `false_positive_tolerance`, `latency_budget_ms_p95`) so the CLI can consume them without an operator runtime flag.
- Bump the dataset `schema_version` to `3` and keep existing `v2` datasets valid.
- Preserve the existing 10 cases verbatim, the Subphase 4.11 runner, the deterministic grid, the JSON report schema, the `Fuzzy baseline comparison and eligibility` requirement, the CLI surface, and the rule that fuzzy remains authoritative and hybrid remains observational.
- Add the minimum tests required to validate dataset schema; scope-aware reference validation for all expected and candidate references in `commerce_dynamic_database` cases; preservation of the 10 verbatim `in_memory` cases on their embedded-catalog path; category coverage; eligibility evaluation; deterministic calibration output; and explicit failure messages for missing, nonexistent, cross-commerce, and ambiguous references.
- Run the inventory step, run embedding seeding if required, execute the calibration CLI for `comercio_id=1`, and report results. Do not run `/opsx:sync` or `/opsx:archive`.

**Non-Goals:**

- Activate `PRODUCT_RECOGNIZER_MODE=hybrid` or promote any selected policy into runtime defaults.
- Modify handlers, resolvers, pending contexts, intents, orders, responses, persistence contracts, HTTP endpoints, canonical specs, or runtime settings.
- Import external ML, optimization, or schema migration libraries.
- Add new runtime call sites, factory paths, or shadow-mode observation surfaces.
- Have runtime code import test infrastructure or fixtures to resolve `seed_refs`.
- Replace or weaken any existing 4.11 requirement or scenario.
- Grow the dataset beyond ~50 cases or chase theoretical exhaustiveness.
- Hand-maintain the `seed_refs` map outside the inventory step.

## Decisions

### Decision: New cases use `catalog_scope: "commerce_dynamic_database"` and `id_comercio: 1`

The existing dataset already supports `commerce_dynamic_database` scope (see `multi-word-jamon-queso-dynamic`). Reusing the same scope keeps the runner, the vector search service, and the fuzzy recognizer call path untouched. The 4.11 runner resolves the catalog at runtime from the database via the `vector_search_factory`; the new cases simply point at `comercio_id=1` and reference real `producto_presentacion_id` values in `allowed_candidate_ids`.

The 10 preserved Subphase 4.11 cases keep their `catalog_scope: "in_memory"` and their existing `catalogs[*].entries`. They are not rewritten to `commerce_dynamic_database` and they are not migrated to `comercio_id=1`. They stay in the dataset verbatim to keep the regression baseline intact.

**Alternatives considered:**

- Adding a new catalog scope (e.g., `commerce_dynamic_database_with_aliases`) — rejected. Adds a new code path without proven need; the existing scope already fetches `aliases` from the joined product rows.
- Loading the catalog eagerly into `catalogs[*].entries` for each new case — rejected. Bypasses the established runtime resolution path and breaks `commerce_isolation` enforcement (the runner would have to skip commerce filtering on the explicit catalog).
- Migrating the 10 preserved cases to `comercio_id=1` — rejected. Changes their expected outcomes and breaks the regression baseline; the user explicitly requires preserving them verbatim and excluding them from the `comercio_id=1` minimum.

### Decision: Top-level `seed_refs` map is regenerated or validated by an explicit repository-supported inventory step

The dataset ships a top-level `seed_refs` map where each symbolic key (e.g., `pp_empanada_pollo`, `pp_pizza_muzzarella_chica`) points to the real `producto_presentacion_id` resolved from the database for `comercio_id=1`. The keys are opaque symbolic identifiers — never numeric IDs — so the dataset stays portable across reseeds and database changes.

The map is not hand-maintained. A new repository-supported script, `backend/scripts/calibration_inventory.py`, is the single source of truth for the mapping used by the new `commerce_dynamic_database` cases with `id_comercio=1`. It does not inventory, validate, or reinterpret the preserved `in_memory` cases. The script:

1. Connects to the seeded database through the project's existing SQLAlchemy session factory.
2. Queries active `producto`, `producto_presentacion`, `presentacion`, and `producto_alias` rows for `id_comercio = 1`.
3. Resolves each symbolic key to the matching `producto_presentacion_id` by name, presentation code, and alias.
4. Runs in one of two modes:
   - **Regenerate**: writes the resolved mapping back into `backend/data/product_recognition_calibration_cases.json` under the top-level `seed_refs` key, preserving the existing case bodies and the optional `eligibility` block.
   - **Validate**: reads the existing `seed_refs` map and fails with a clear, non-generic message when any reference is missing, cross-commerce, or ambiguous.
5. Exits non-zero with a clear message identifying the symbolic key, the offending value, and the expected scope on any failure.

The inventory step is intentionally separate from the runtime code path. Runtime code (the runner, the policy, the resolver) MUST NOT import the inventory step, the test fixtures, or any test infrastructure. The runner only reads the symbolic references and asks the dataset to resolve them; the resolution path stays inside the runner's own validation, which calls the same database queries the inventory step uses.

**Alternatives considered:**

- Hand-maintaining the `seed_refs` map in the dataset — rejected. Drifts from the database after reseeds and produces errors that are hard to localise.
- Hard-coding integer IDs as portable symbolic references (e.g., `seed_refs: { "42": 42 }`) — rejected. Conflates the symbolic key with the value; a reseed that changes the ID silently breaks the lookup and the failure mode is opaque.
- Resolving at runtime via a fixture helper — rejected. Couples the dataset to test infrastructure and forces the runtime to import test modules.
- Reading the database from the runner at runtime to build the `seed_refs` map on the fly — rejected. Mixes dataset authoring with runtime execution and makes the dataset non-portable across environments.

### Decision: Database-backed reference validation is scope-aware and per case

Only a case with `catalog_scope == "commerce_dynamic_database"` enters database-backed reference validation. Immediately before evaluating each such case, the runner:

- resolves and validates every `expected_producto_presentacion_id_ref` through `seed_refs`;
- validates every `allowed_candidate_ids` and `restricted_candidate_ids` entry;
- checks every resolved or direct candidate ID against that case's own `id_comercio`; and
- fails clearly for a missing symbolic reference, a nonexistent resolved or candidate ID, an ID owned by another commerce, or a symbolic key that resolves ambiguously.

Each failure identifies the case, reference or candidate, offending value, and expected commerce scope. Validation occurs before the affected case is evaluated; already-preserved behavior for other scopes is not replaced by a global database preflight.

Cases with `catalog_scope: "in_memory"` remain on the existing embedded-catalog validation and evaluation path. Their candidate IDs are not checked against the seeded database, their existing `id_comercio` values are not forced to `1`, and fixture IDs are not reinterpreted as production database IDs. This preserves all 10 Subphase 4.11 cases verbatim and keeps their fixture semantics intact.

**Alternatives considered:**

- Validating every case against the `comercio_id=1` seeded database before the run — rejected. It misinterprets fixture IDs, overrides each case's scope, and breaks the preserved `in_memory` regression path.
- Logging a warning and skipping the case — rejected. Silently hides a broken database-backed case and produces a misleading report.
- Treating all reference failures as a generic exception — rejected. Operators cannot distinguish missing, nonexistent, cross-commerce, and ambiguous references.
- Falling back to the fuzzy baseline for a broken database-backed reference — rejected. The affected case would no longer test its declared real-database expectation.

### Decision: Optional `eligibility` block in the dataset, schema_version `3`

The dataset gets an optional top-level `eligibility` block:

```jsonc
"eligibility": {
  "primary_metric": "decision_accuracy",
  "required_improvement": 0.0,
  "false_positive_tolerance": 0.0,
  "latency_budget_ms_p95": 500
}
```

`validate_dataset` accepts `schema_version` `3` and validates the block when present (numeric types, allowed primary metric values, non-negative latency budget). Existing `v2` validation is preserved unchanged. When `runner.run` is called without an explicit `eligibility` argument, it reads the block from the dataset and converts `latency_budget_ms_p95` to the milliseconds value the existing gate expects.

**Alternatives considered:**

- A new CLI flag for each eligibility input — rejected. Splits the source of truth across dataset and CLI; an operator running the CLI from a fresh checkout would get `pending` without realising they need flags.
- A separate `eligibility.json` config file — rejected. Splits the dataset across two files that must be kept in sync; the dataset is the single source of truth in 4.11.

### Decision: Runner reads dataset `eligibility` only when no explicit argument is supplied

The existing `ProductRecognitionCalibrationRunner.run` already accepts an `eligibility` keyword argument. Existing tests pass it explicitly. The new behaviour is: if `eligibility` is `None` and the dataset has an `eligibility` block, the runner reads it from the dataset. If `eligibility` is `None` and the dataset has no `eligibility` block, the runner falls back to the existing `pending` behaviour. If `eligibility` is supplied explicitly, the dataset block is ignored.

**Alternatives considered:**

- Always reading the dataset block when present and merging with the argument — rejected. Introduces precedence ambiguity and could mask test bugs.
- Raising an error when both are supplied — rejected. Forces test rewrites without proven benefit.

### Decision: CLI surface unchanged

The CLI already calls `runner.run(dataset, commerce_id=args.commerce_id, limit=args.limit)` without an `eligibility` argument. With the runner change above, the CLI will automatically pick up the dataset `eligibility` block. No CLI flag changes are required.

**Alternatives considered:**

- Adding `--eligibility-*` flags — rejected. Duplicates the dataset block; the runner already reads the dataset first.

### Decision: Final case count and `comercio_id=1` minimum

The final dataset has 30–50 cases total, inclusive of the 10 preserved Subphase 4.11 cases. The `comercio_id=1` minimum is 30 evaluable cases, counted only from the new `commerce_dynamic_database` cases. The 10 preserved `in_memory` cases contribute to the overall total but are excluded from the `comercio_id=1` minimum.

**Alternatives considered:**

- Treating the 10 preserved cases as `comercio_id=1` cases — rejected. Their `catalog_scope` is `in_memory` and their `id_comercio` is not 1; they cannot be evaluated against the seeded database for `comercio_id=1`.
- Dropping the 10 preserved cases — rejected. They are the regression baseline for the 4.11 runner; removing them breaks the existing test suite.

### Decision: Tests focus on the new behaviour, not on the existing 4.11 regression surface

The 4.11 focused tests already cover policy validation, runner semantics, eligibility gates, JSON determinism, the CLI, and the Subphase 4.5–4.10.1 regression set. The new tests cover only:

- `validate_dataset` accepts `schema_version` `3` and validates the optional `eligibility` block.
- `validate_dataset` rejects malformed `eligibility` blocks (missing keys, non-numeric values, negative latency budget).
- `validate_dataset` continues to accept `v2` datasets unchanged.
- The runner reads `eligibility` from the dataset when no explicit argument is supplied.
- The runner uses the explicit `eligibility` argument when supplied and ignores the dataset block.
- A focused test that runs the inventory step against the seeded database and confirms every `seed_refs` entry used by a new `commerce_dynamic_database` case with `id_comercio=1` resolves to an existing product presentation in that commerce.
- Focused tests asserting database-backed validation applies only to `commerce_dynamic_database` cases, validates every expected and allowed/restricted candidate against each case's own `id_comercio`, and reports missing, nonexistent, cross-commerce, and ambiguous failures before evaluating the affected case.
- A focused regression test asserting all 10 preserved `in_memory` cases remain verbatim and continue through embedded-catalog validation/evaluation without seeded-database candidate validation, forced `id_comercio=1`, or fixture-ID reinterpretation.
- A focused test that asserts the expanded dataset covers every allowed category (`canonical`, `alias`, `ambiguous`, `unknown`, `restricted`, `commerce_isolation`, `baseline`) AND has at least 30 evaluable cases for `comercio_id=1` AND has between 30 and 50 cases total.
- A focused test that asserts the calibration report is deterministic for the expanded dataset (sorted keys, stable list order, finite numbers, byte-identical for equal observations).
- A focused test that asserts the runner does not import test infrastructure (no fixture, no `backend.tests.*` import in the runner's import graph under the test).

**Alternatives considered:**

- Re-running the full 4.11 focused test suite — required by the implementation verification task, but not a new test. The implementation will run the existing suite as a regression guard.

### Decision: Embedding seeding is run if and only if the case requires a vector result that is absent

The vector search service requires embeddings to exist for the candidates of each case. If the database is missing embeddings for any product referenced by the new cases, the operator runs the existing embedding seeding flow before calibration. If embeddings already exist, the seeding step is skipped. This is a deployment-time decision, not a code change.

**Alternatives considered:**

- Automatically seeding embeddings from the CLI — rejected. Out of scope for 4.11.1; mixing seeding and calibration would require a new transactional command and was not requested.

## Risks / Trade-offs

- [Dataset IDs drift from the database after a reseed] → Mitigation: the inventory step regenerates or validates the `seed_refs` map from the seeded database; a focused test exercises the validate path. The dataset continues to use opaque symbolic keys, so a reseed only requires running the inventory step in regenerate mode.
- [Database-backed validation accidentally reaches `in_memory` fixtures] → Mitigation: branch exclusively on `catalog_scope == "commerce_dynamic_database"`; preserve the embedded-catalog path and add a regression test proving the 10 verbatim cases do not query the seeded database, force commerce 1, or reinterpret fixture IDs.
- [A database-backed case is validated against commerce 1 instead of its declared commerce] → Mitigation: derive the validation scope from each case's own `id_comercio`; tests include cross-commerce and non-1 database-backed fixtures even though the new inventory-generated cases are commerce 1.
- [Missing / nonexistent / cross-commerce / ambiguous references produce opaque errors] → Mitigation: fail before evaluating the affected database-backed case with a distinct message naming the case, reference or candidate, offending value, and expected commerce scope.
- [Runtime code accidentally imports test infrastructure to resolve `seed_refs`] → Mitigation: a focused test asserts the runner's import graph does not import `backend.tests.*` or any fixture module. The inventory step lives outside the runtime code path and is documented as a tool script, not a runtime dependency.
- [Vector search coverage is missing for some products] → Mitigation: the implementation runs the project's embedding seeding flow before calibration if the report shows vector infrastructure failures concentrated on a small set of product IDs.
- [Eligibility inputs are hard-coded in the dataset] → Trade-off: the dataset becomes the single source of truth for eligibility, including its numeric values. Operators who want to override the inputs can pass an explicit `eligibility` argument (e.g., via a small in-process script) or modify the dataset. Documented in the proposal.
- [Schema version bump to `3` could surprise downstream consumers] → Mitigation: `validate_dataset` accepts `1` and `2` unchanged; `3` only adds an optional block. The CLI and the runner behave identically for `v2` datasets.
- [Real cases may surface runner defects that the 10-case fixture set masked] → Trade-off: the implementation runs the full 4.11 focused test suite plus the new tests as a regression guard. If a runner defect is found, it is fixed in this change as a blocking defect (per the project.md rule "preserve existing calibration runner and report schema unless a real blocking defect is found").

## Migration Plan

There is no schema migration. The deployment steps are:

1. Run the inventory step in regenerate mode for the new `commerce_dynamic_database` cases with `id_comercio=1`: `python -m backend.scripts.calibration_inventory --dataset backend/data/product_recognition_calibration_cases.json --mode regenerate`.
2. Re-run the inventory step in validate mode over that same scope: `python -m backend.scripts.calibration_inventory --dataset backend/data/product_recognition_calibration_cases.json --mode validate`.
3. Run `python -m backend.tests.embedding_seeding` (or the project's equivalent) if the database is missing embeddings for any `comercio_id=1` product referenced by the new cases.
4. Run `python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output reports/calibration-comercio-1.json --commerce-id 1`.
5. Inspect the JSON report at `reports/calibration-comercio-1.json` and the CLI summary on stdout.

Rollback: revert the change. The dataset returns to its previous shape, the inventory step is removed, the runner ignores the optional `eligibility` block, and no database state is mutated.

## Open Questions

- Should the dataset include a `notes` field per case to document the source of the expected outcome (e.g., "manually verified against `comercio_id=1` products on 2026-08-04")? Not required by the project.md; deferred to a future subphase if needed.
- Should the new cases be tagged with a `coverage_surface` field to distinguish them from the 4.1 baseline cases? Not required by the project.md; deferred to a future subphase if needed.
- Are there any `comercio_id=1` products or aliases that should be excluded from the calibration (e.g., seasonal or recently retired)? To be confirmed by the operator before running the calibration; out of scope for this change.
- Should the inventory step also seed the `allowed_candidate_ids` / `restricted_candidate_ids` arrays for the new cases, or should those remain hand-authored? Initial proposal: only the `seed_refs` map is regenerated; the candidate arrays stay hand-authored and are validated by the runner. Deferred to a future subphase if the hand-authored arrays drift.
