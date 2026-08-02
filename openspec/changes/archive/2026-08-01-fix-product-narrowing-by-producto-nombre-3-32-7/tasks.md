## 1. Implement the product-name match predicate

- [x] 1.1 In `backend/intents/context/product_selection_context_resolver.py`, extend the per-candidate loop in `_narrow_by_presentacion_alias` (the block that builds `matching_ids`) so each candidate is considered a match when **either** `_presentacion_matches(codigo, presentacion_alias)` is true (the existing path) **or** `presentacion_alias` appears as a whole word in the candidate's `producto_nombre` after `_normalizar_texto` normalization. The whole-word test MUST use `set(_normalizar_texto(nombre).split())` membership so a substring such as `picantes` does NOT match the alias `picante`. The existing `presentacion_codigo` match path MUST remain bit-for-bit equivalent.
- [x] 1.2 Keep the rest of `_narrow_by_presentacion_alias` unchanged: the `presentacion_alias = _extraer_presentacion(message)` call, the `irrelevant = STOPWORDS | TAMANIOS | set(PRESENTACION_ALIASES.keys())` set, the `_extraneous_words_relate_to_active_intent` guard from 3.32.5, and the `intersection = [cid for cid in active_intent.candidate_ids if cid in matching_ids]` filter. Do not modify `PRESENTACION_ALIASES`, `_extraer_presentacion`, or any recognizer code.
- [x] 1.3 Confirm the module still imports cleanly: `PYTHONPATH=. .venv/bin/python -c "from backend.intents.context.product_selection_context_resolver import resolve_product_selection; print('ok')"` exits 0.

## 2. Focused unit tests for the new predicate

- [x] 2.1 In `backend/tests/test_product_selection_context_resolver.py`, add `ResolveProductSelectionProductoNombreAliasTest` (or extend an existing class) with focused tests that:
  - drive `_narrow_by_presentacion_alias` (or `resolve_product_selection` end-to-end) with `picante` against a catalog of two candidates sharing `presentacion_codigo == "UNIDAD"` and `producto_nombre` "Empanada de Carne" and "Empanada de Carne Picante", and assert the returned intent selects the Picante id, has `status == "ready"`, `candidate_ids == []`, and the original `cantidad` preserved.
  - drive the same scenario with `tradicional` against a Pizza Muzzarella / Pizza Muzzarella Tradicional pair and assert the same outcome.
  - drive `carne picante` and assert the 3.32.5 extraneous-token guard still permits narrowing, and the new predicate selects the Picante id.
  - drive `la picante` and `la de carne picante` against the same active intent and assert the same outcome.
  - drive `picante` against a catalog that includes a candidate with `producto_nombre` "Empanada Picantes Variedad" (substring-only, no whole-word `picante`) and assert the candidate is NOT in `matching_ids` and the resolver returns the active intent unchanged.
  - drive `la grande` against a Pizza Chica / Pizza Grande pair and assert the existing `presentacion_codigo` path still selects Pizza Grande (regression test).
  - drive `grandi` (alias variant for `grande`) against a candidate whose `producto_nombre` contains the token `grande` and assert the alias normalization from `_extraer_presentacion` makes the new predicate fire.
  - drive a scenario where the alias matches multiple product-narrow candidates and assert the resolver returns a copy with `candidate_ids` reduced, `status == "pending_resolution"`, and the original `cantidad` preserved.

## 3. End-to-end regression test

- [x] 3.1 In `backend/tests/test_agregar_producto_sequential_queue_end_to_end.py` (or a sibling end-to-end test module), add an HTTP regression test that drives the real `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` endpoint against `supernova_test` with a sequence mirroring the original failure: `agrega 1 empanada de carne` followed by `carne picante`. Assert that the second turn:
  - returns the Carne Picante confirmation (not a re-clarification),
  - leaves `candidate_ids` empty for the active Carne intent,
  - preserves the original `cantidad == 1`,
  - does not call the classifier a second time on the second turn,
  - does not promote or alter the queue (queue is empty in this scenario).
- [x] 3.2 Re-run the existing 3.32.5 `SequentialQueueE2EExactAssertionsTest` and the 3.32.4 pending-queue regressions and confirm they still pass (no behavior change for flows that did not exercise the product-name path).

## 4. Diagnostic surface verification

- [x] 4.1 With a `CollectingDiagnosticSink` active (the 3.32.6 mechanism), drive a `carne picante` flow and confirm the `RESOLVER INPUT` table still emits with `incoming_text="carne picante"`, `candidate_count=2`, and the candidate catalog projection including both `producto_nombre` values. Confirm the `RESOLVER CANDIDATES` table renders both rows. Confirm the `RESOLVER OUTPUT` table records `status_after="ready"`, `selected_candidate_id=32`, `candidate_ids_after=[]`, and the matches list contains the single entry.
- [x] 4.2 With a `NoopDiagnosticSink` (the default), confirm the same flow returns the same `ProcessedIntent` and emits no event (existing 3.32.6 contract preserved).

## 5. Lint, type, and validation

- [x] 5.1 Run `PYTHONPATH=. .venv/bin/python -m compileall backend` and confirm exit 0.
- [x] 5.2 Run `PYTHONPATH=. .venv/bin/python -m ruff check backend` and `PYTHONPATH=. .venv/bin/python -m mypy backend` and confirm no new failures on the changed files.
- [x] 5.3 Run `PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_product_selection_context_resolver -v` and the end-to-end regression test and confirm all pass.
- [x] 5.4 Run `openspec validate fix-product-narrowing-by-producto-nombre-3-32-7 --strict` and confirm valid.

## 6. Reporting

- [x] 6.1 Mark every task above completed in this file.
- [x] 6.2 Append a `## Subphase 3.32.7 — ...` completed block to `openspec/specs/project.md` following the same format as 3.32.5 / 3.32.6, recording the predicate change, the test counts, and the diagnostic observations.
- [x] 6.3 Do NOT run `openspec sync`, do NOT run `openspec archive`, and do NOT start the next subphase. Stop after reporting.
