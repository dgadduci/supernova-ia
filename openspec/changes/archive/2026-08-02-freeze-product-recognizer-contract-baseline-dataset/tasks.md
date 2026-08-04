## 1. Freeze the Complete Backend Contract

- [x] 1.1 Inventory every production `detectar_productos` call and result-lifecycle path across `backend/`, including `agregar_producto_orchestrator`, product-selection service/resolver, `quitar_producto` adapter, `modificar_producto` source and destination stages, product-intent resolution, pending-context dispatch/execution, and FIFO queue promotion; classify legacy and test-only call sites separately.
- [x] 1.2 Record the exact current catalog projection, accepted additional fields, four top-level result keys, nested dictionary shapes, field types, empty-value behavior, quantity default, availability behavior, preserved fields, duplicate handling, and ordering semantics from the existing implementation and consumers.
- [x] 1.3 Identify the existing test catalog fixtures and real `producto_presentacion_id` values for exact, ambiguous, restricted refinement, alias, misspelling, unknown, quantity, and multi-word cases; reject any case requiring invented production IDs.
- [x] 1.4 Add focused assertions for the frozen contract before changing composition boundaries, including key order, nested shapes, field preservation, candidate grouping/order, unknown fragments, availability handling, duplicate IDs, and quantity behavior.

## 2. Add Separate Static Contract and Fuzzy Adapter

- [x] 2.1 Create `backend/recognizers/product_recognizer_contract.py` with `TypedDict` or explicit aliases for catalog entries, recognized products, possible groups, unmatched fragments, and the exact four-key result, plus `ProductRecognizerProtocol`.
- [x] 2.2 Create `backend/recognizers/fuzzy_product_recognizer.py` with `FuzzyProductRecognizer` delegating directly to the existing `detectar_productos` pipeline without copying, reordering, normalizing, or tuning results; retain the existing fuzzy module as the algorithm owner.
- [x] 2.3 Preserve `detectar_productos(texto, productos_presentaciones)` as a compatible public entry point and verify protocol/function equivalence for IDs, quantities, unknown fragments, unavailable entries, preserved fields, and ordering.
- [x] 2.4 Replace concrete fuzzy-recognizer dependencies at practical composition boundaries with the protocol-compatible implementation while retaining required resolver helper compatibility and restricted catalog boundaries; do not rewrite pending-context flow.
- [x] 2.5 Add a reusable implementation-neutral contract test harness and run it against `FuzzyProductRecognizer` using existing in-memory catalogs and the real pending-flow restricted catalogs.

## 3. Create and Validate the Baseline Dataset

- [x] 3.1 Create `backend/tests/fixtures/product_recognizer_baseline.json` using existing test catalog fixtures or references, with unique case IDs, input text, result type, category/reason, expected IDs, expected quantities, and explicit catalog scope metadata.
- [x] 3.2 Include cases for exact product, product plus presentation, fuzzy misspelling, supported alias, ambiguous `empanada de carne`, unknown `caramelo`, and multi-word `empanada de jamón y queso` using real fixture IDs.
- [x] 3.3 Add `picante` and `grande` refinement cases using the exact restricted candidate catalogs and candidate IDs from the real pending product-selection or modification flows; reject full-catalog or synthetic-candidate substitutions.
- [x] 3.4 Mark every case that exposes an accepted fuzzy limitation with `known_fuzzy_limitation` and a non-empty `limitation_note`; ensure annotations describe current behavior only and are not desired semantic outcomes.
- [x] 3.5 Add dataset schema and integrity validation for required fields, allowed result types, unique case IDs, fixture references, expected IDs, restricted candidate scope, and limitation metadata.
- [x] 3.6 Add execution tests that run every baseline case through real `FuzzyProductRecognizer` without mocking and validate current unique, ambiguous, unknown, quantity, and limitation expectations.

## 4. Preserve Integration Behavior and Verify

- [x] 4.1 Add or update an `agregar_producto` integration smoke test proving one unique path works through the abstraction and preserves its current result keys, IDs, quantity, and status behavior.
- [x] 4.2 Add or update pending product-selection and modification refinement integration tests proving `picante`/`grande` use restricted candidate catalogs and produce the same ready or pending outcomes and candidate IDs.
- [x] 4.3 Run focused regressions for `agregar_producto`, pending product selection, `quitar_producto`, and `modificar_producto`, including source and destination recognition, product-intent resolution, pending dispatch, execution, and queue promotion; fix only abstraction compatibility issues.
- [x] 4.4 Update recognizer diagnostics only if needed to expose the concrete implementation name, without adding semantic/vector/Ollama diagnostics or changing existing diagnostic semantics.
- [x] 4.5 Run `PYTHONPATH=. venv/bin/python -m compileall backend`, strict OpenSpec validation, and the focused contract, baseline, and integration test commands; record results and leave the change active and unsynchronized.
