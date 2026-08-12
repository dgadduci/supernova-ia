## 1. Shared boundary

- [x] 1.1 Bind quitar, modificar, and both relevant pending resolvers to the existing factory; remove only their local production fuzzy selection.
- [x] 1.2 Preserve each caller's existing catalog construction, context metadata, `ProcessedIntent` shape, and handler ownership.
- [x] 1.3 Verify every vector candidate is filtered to the passed catalog before decision/ranking translation.
- [x] 1.4 Thread `commerce_id` through `RecognizeContext.commerce_id` from each entry point (`agregar_producto`, `quitar_producto`, `modificar_producto`, pending product selection, pending modification) so the hybrid authoritative recognizer can run its vector pipeline with the supplied commerce id without reloading or widening the catalog.
- [x] 1.5 `HybridAuthoritativeProductRecognizer` reads `intent_metadata["commerce_id"]` first and falls back to the injected `commerce_id_resolver`; when neither yields an `int`, it raises `HybridAuthoritativeCommerceIdMissing` instead of silently returning the fuzzy result under a fallback category. Missing `commerce_id` is NOT a fallback reason under the OpenSpec contract.

## 2. Authoritative behavior and telemetry

- [x] 2.1 Confirm the three mode contracts and safe invalid-mode fallback.
- [x] 2.2 Complete the exact technical-only fallback classification and ensure semantic outcomes never fallback.
- [x] 2.3 Reuse existing observation structures for configured/effective mode, strategy, decisions, fallback, and category.
- [x] 2.4 Extend `ProductRecognitionShadowComparison` with the explicit `fallback: bool` field and thread it from the hybrid authoritative recognizer and the shadow service.
- [x] 2.5 Extend `ShadowMetricsRecorder.record` with `configured_mode`, `effective_mode`, `authoritative_strategy`, and `fallback_category` kwargs and emit them in the structured log record.
- [x] 2.6 `Settings.product_recognizer_configured_mode` carries the raw operator env value alongside the effective `product_recognizer_mode`; the factory passes both into the recognizers so every record exposes configured/effective mode.
- [x] 2.7 Add the `ObservedFuzzyProductRecognizer` decorator that subclasses `FuzzyProductRecognizer` and emits one `ShadowMetricsRecorder` record per `recognize(...)` call. The decorator carries the configured/effective mode, the fuzzy authoritative strategy, a non-evaluated hybrid decision, and an optional sanitized `fallback_category="invalid_mode"` for the safe-fuzzy invalid-mode fallback. The decorator never invokes embedding, the vector-search pipeline, or any database session.

## 3. Focused tests and validation

- [x] 3.1 Add/update focused unit tests for all mode contracts, fallback prohibitions, catalog isolation, and candidate ordering.
- [x] 3.2 Add/update focused flow tests for agregar, quitar, modificar, pending product selection, and pending modification.
- [x] 3.3 Add focused integration tests that drive the real production wrappers with the hybrid authoritative recognizer bound and prove the embedding + vector pipeline runs when the entry point supplies the commerce id.
- [x] 3.4 Add focused observability tests that assert the recorder payload for the documented modes, technical-fallback categories, semantic outcomes, and the safe-fuzzy invalid-mode fallback; sensitive fields are never emitted.
- [x] 3.5 Add focused tests that prove missing `commerce_id` raises `HybridAuthoritativeCommerceIdMissing` instead of recording a fallback; the exception message never carries the customer text, the catalog payload, or any internal infrastructure detail.
- [x] 3.6 Add focused tests that prove the `ObservedFuzzyProductRecognizer` decorator emits one record per call in fuzzy mode and in the safe-fuzzy invalid-mode fallback; the four-key result contract is preserved byte-for-byte.
- [x] 3.7 User runs and reports: `venv/bin/python -m pytest backend/tests/test_product_recognition_factory.py backend/tests/test_controlled_hybrid_product_recognition.py backend/tests/test_product_recognition_shadow_service.py backend/tests/test_pending_product_ambiguity_resolution.py backend/tests/test_quitar_producto_recognizer.py backend/tests/test_modificar_producto_recognizer.py backend/tests/test_product_selection_context_resolver.py backend/tests/test_modificar_producto_initial.py backend/tests/test_quitar_producto_initial.py backend/tests/test_product_modification_resolver.py backend/tests/test_order_line_selection_resolver.py`.
- [x] 3.8 User runs and reports Ruff and compileall for the exact touched Python files, then `openspec validate subphase-4-12b-controlled-authoritative-hybrid-product-recognition --strict`.

## 4. Approval gate

- [x] 4.1 Obtained explicit user approval before delegating implementation to Minimax 3.
- [x] 4.2 Kept production on fuzzy/shadow; no hybrid activation, sync, or deploy occurred in this change.
