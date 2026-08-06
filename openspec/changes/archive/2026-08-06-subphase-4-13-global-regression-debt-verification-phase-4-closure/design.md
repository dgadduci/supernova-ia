## Context

4.13 is deliberately a one-way verification boundary: existing production
behavior is observed through its real factory, recognizer, calibration, and
pending-context seams; the only artifacts produced are test/static-check
output and a closure report. It does not create a parallel test harness or
re-implement recognition decisions.

The authoritative outcomes are:

| Outcome | Closure decision |
| --- | --- |
| All required commands succeed and calibration is `eligible` | Recommend Phase 4 closure. |
| A required Phase-4 test/static/calibration command fails newly | Block closure; create a separate corrective change after approval. |
| Optional debt is unchanged, reduced, has line-number drift, or equivalent diagnostic wording, and required Phase-4 commands pass | Document the variation; defer it unless it meets a blocking condition. |
| Optional debt is materially new, increases documented debt, changes runtime/business behavior, or overlaps a required Phase-4 boundary | Block closure; create a separate corrective change after approval. |
| Environment cannot execute a command | No behavioral verdict and not a regression; run every required command successfully in the supported local environment before closure. |

## Real execution paths under verification

```text
catalog -> FuzzyProductRecognizer
        -> factory mode=fuzzy (authoritative)
        -> factory mode=shadow -> ShadowedProductRecognizer (observational)
        -> factory mode=hybrid_authoritative
           -> calibrated policy + embedding/vector search
           -> catalog-ID filter + guards
           -> hybrid result, or byte-for-byte fuzzy on technical failure

pending product selection -> restricted catalog -> RecognizeContext
                         -> hybrid restricted-scope guard
pending ambiguity reply -> deterministic resolver -> existing dispatcher/execution
```

The passed catalog remains the authoritative candidate universe. Recognition
does not own database commit or rollback; integration tests exercise the
existing caller-owned transactional path rather than introducing a new one.

## Regression matrix

| Area | Existing verification | Required invariant |
| --- | --- | --- |
| Fuzzy | recognizer contract/baseline/alias suites | Four-key shape, commerce isolation, safe unknown/ambiguous behavior. |
| Vector | embedding model/indexer/search suites | Per-commerce retrieval and catalog/index boundaries. |
| Shadow | shadow service/module-boundary suites | Fuzzy result remains authoritative; failures are observable. |
| Calibration | runner, dataset, policy, eligibility, report, CLI and 4.11.x suites | Frozen grid/report semantics; 47-case result remains eligible. |
| Pending | 4.12A unit and E2E suites | Candidate IDs cannot be widened; deterministic reply resolution is preserved. |
| Authoritative hybrid | settings/factory/controlled-hybrid suite | Opt-in/reversible mode, policy fail-closed, scope filter/guards, fuzzy technical fallback. |

## Validation design

Run the matrix in focused groups so the first failing boundary is identifiable.
The calibration command writes only to `/private/tmp`, making it reversible
and avoiding repository artifacts. Its report must have
`eligibility.status == "eligible"`; the command itself must exit zero.

Use these exact commands from the repository root:

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_producto_presentacion_embedding_model.py backend/tests/test_producto_presentacion_embedding_integration.py backend/tests/test_producto_presentacion_embedding_indexer.py backend/tests/test_product_presentation_vector_search_service.py backend/tests/test_product_presentation_vector_search_module_boundaries.py backend/tests/test_catalog_embedding_synchronization_service.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognition_shadow_service.py backend/tests/test_product_recognition_shadow_module_boundaries.py backend/tests/test_shadow_metrics_recorder.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_dataset_4_11_1.py backend/tests/test_product_recognition_calibration_eligibility.py backend/tests/test_product_recognition_calibration_report.py backend/tests/test_product_recognition_calibration_policy.py backend/tests/test_product_recognition_calibration_cli.py backend/tests/test_product_recognition_calibration_commerce_catalog.py backend/tests/test_product_recognition_calibration_inventory_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_4_11_4.py backend/tests/test_product_recognition_calibration_4_11_5.py backend/tests/test_product_recognition_calibration_4_11_7.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py backend/tests/test_pending_product_ambiguity_resolution.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_settings_product_recognizer_mode.py backend/tests/test_product_recognition_factory.py backend/tests/test_controlled_hybrid_product_recognition.py
PYTHONPATH=. venv/bin/python -m backend.cli.calibrate_product_recognizer --dataset backend/data/product_recognition_calibration_cases.json --output /private/tmp/phase-4-13-calibration.json --diagnose --diagnose-output /private/tmp/phase-4-13-calibration.diagnose.json --limit 47
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/recognizers/fuzzy_product_recognizer.py backend/recognizers/product_recognizer_contract.py backend/services/product_recognition_factory.py backend/services/product_recognition_shadow_service.py backend/services/hybrid_authoritative_recognizer.py backend/services/hybrid_authoritative_policy_source.py backend/services/product_presentation_vector_search_service.py backend/services/product_recognition_calibration_runner.py backend/intents/context/product_selection_context_resolver.py backend/intents/context/pending_product_ambiguity_resolver.py
PYTHONPATH=. venv/bin/python -m compileall backend/recognizers/product_recognizer.py backend/recognizers/fuzzy_product_recognizer.py backend/recognizers/product_recognizer_contract.py backend/services/product_recognition_factory.py backend/services/product_recognition_shadow_service.py backend/services/hybrid_authoritative_recognizer.py backend/services/hybrid_authoritative_policy_source.py backend/services/product_presentation_vector_search_service.py backend/services/product_recognition_calibration_runner.py backend/intents/context/product_selection_context_resolver.py backend/intents/context/pending_product_ambiguity_resolver.py
openspec validate subphase-4-13-global-regression-debt-verification-phase-4-closure --strict
```

The optional diagnostic command for the known smoke debt is intentionally
separate and cannot change the closure verdict unless one of its failures is
materially new, increases documented debt, changes runtime/business behavior,
or overlaps the Phase-4 matrix:

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py
PYTHONPATH=. venv/bin/python -m ruff check backend/tests/test_llm_settings.py
PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py
```

## Acceptance criteria

1. Every required command exits zero; the calibration JSON exists and reports
   `eligibility.status == "eligible"`.
2. Fuzzy, vector, shadow, calibration, pending ambiguity, and authoritative
   hybrid suites all pass without changing their code or fixtures.
3. The hybrid suite proves the two guards, catalog filtering, commerce
   isolation, and fuzzy fallback for technical failures; empty filtered vector
   output remains a semantic outcome, not a fallback trigger.
4. The pending suites prove no candidate outside the persisted narrowed set
   can resolve a pending intent.
5. Every optional-debt result is classified with evidence. Only the exact
   documented baseline, a reduced inventory, line-number drift, or equivalent
   diagnostic wording may be deferred, provided it does not introduce a
   materially new issue, increase documented debt, change runtime/business
   behavior, or overlap the required Phase-4 surface.
6. No implementation, test, migration, sync, or archive is performed.
7. An environment blocker is not classified as a regression, but all required
   commands run successfully in the supported local environment before Phase
   4 closure is recommended.

## Deferred limitations

The four smoke failures, three B017 findings, generic-type mypy inventory,
and two raw-fuzzy baseline limitations remain deferred only under the precise
classification rule above. The mypy baseline is evidenced by
`openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/tasks.md:35`,
which records 16 historical generic-type findings and its stash/main
comparison. Their cost is unrelated cleanup or responsibility movement; their
benefit is not required to establish Phase-4 functional closure. This
decision is reversible through separately approved changes.
