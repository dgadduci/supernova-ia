## 1. Comparison dataclass — add the explicit `failure_category` field

- [x] 1.1 Add `failure_category: str | None` as the last declared field of `ProductRecognitionShadowComparison` in `backend/services/product_recognition_shadow_comparison.py` and update the docstring to enumerate the new field (and the "twelve fields" total).
- [x] 1.2 Update the `__all__` re-export comments (if any) only if they reference the field count; the dataclass name itself stays the same.

## 2. Shadow service — pass the category through the constructor

- [x] 2.1 In `ProductRecognitionShadowService.compare` in `backend/services/product_recognition_shadow_service.py`, pass `failure_category=failure_category` (the existing local variable, kept untouched) to the `ProductRecognitionShadowComparison` constructor and remove the `object.__setattr__(comparison, "_failure_category", failure_category)` block (currently at line 230).
- [x] 2.2 Confirm the `compare` method returns the same `(comparison, hybrid_observation)` tuple shape and the existing `failure_category` local variable still drives the comparison field for the embedding-pipeline exception, vector-pipeline exception, and success paths.

## 3. Recorder — read the category from the explicit field

- [x] 3.1 In `ShadowMetricsRecorder.record` in `backend/services/shadow_metrics_recorder.py`, replace the `_failure_category_unset(comparison)` / `_failure_category_from(comparison)` helpers with a direct read of `comparison.failure_category`; keep the existing `vector_available is False and failure_category is None` → `"unknown"` fallback.
- [x] 3.2 Remove the now-unused `_failure_category_unset` and `_failure_category_from` helpers and the `getattr` import path; the recorder module no longer touches a hidden `_failure_category` attribute.

## 4. Focused tests — update the existing setup and add 4.10.1 coverage

- [x] 4.1 In `backend/tests/test_shadow_metrics_recorder.py`, replace the `object.__setattr__(comparison, "_failure_category", "embedding_failure")` setup in `test_recorder_preserves_failure_category_when_set` with a constructor argument on `_make_comparison(...)` (or a follow-up `dataclasses.replace`) so the explicit `failure_category` field drives the assertion.
- [x] 4.2 Add a `test_recorder_does_not_attach_hidden_failure_category` test that asserts `comparison.failure_category` is read directly and that no `_failure_category` attribute lookup is performed.
- [x] 4.3 In `backend/tests/test_product_recognition_shadow_service.py`, replace the `getattr(comparison, "_failure_category", None)` assertion with the direct `comparison.failure_category` field access.
- [x] 4.4 Add a `test_shadow_service_does_not_use_object_setattr` test that introspects the shadow service module and asserts no `object.__setattr__` call exists on a `ProductRecognitionShadowComparison` instance.
- [x] 4.5 Add a `test_comparison_exposes_twelve_fields` test that asserts the dataclass exposes the twelve documented fields and that no hidden `_failure_category` attribute exists on a constructed instance.

## 5. Validation

- [x] 5.1 Run `python -m compileall backend`.
- [x] 5.2 Run `ruff check backend`.
- [x] 5.3 Run `mypy --strict backend/services`.
- [x] 5.4 Run the focused 4.10 and 4.10.1 tests with `pytest` (the suites in `backend/tests/test_shadow_metrics_recorder.py`, `backend/tests/test_product_recognition_shadow_service.py`, `backend/tests/test_product_recognition_shadow_module_boundaries.py`, and the new 4.10.1 tests).
- [x] 5.5 Run `openspec validate clean-shadow-failure-reporting-4-10-1 --strict`.
- [x] 5.6 Report the files changed, the chosen typed-contract approach (explicit `failure_category` field on the comparison), the tests executed, and their results.
