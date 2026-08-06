## Why

Subphase 4.10 shipped a frozen `ProductRecognitionShadowComparison` dataclass that carries the sanitized shadow-failure category through a hidden mutation: `ProductRecognitionShadowService.compare` calls `object.__setattr__(comparison, "_failure_category", ...)` to attach a value the public dataclass schema does not declare, and `ShadowMetricsRecorder.record` reads it back with `getattr(comparison, "_failure_category", None)`. The mutation breaks the "frozen dataclass" contract for an undocumented field, hides the failure category from the typed surface, and forces every reader to use `getattr` defensively. The smallest clean fix is to make the failure category a first-class declared field on the comparison so the recorder reads it through the public shape.

## What Changes

- Add `failure_category: str | None` as an explicit field of `ProductRecognitionShadowComparison` in `backend/services/product_recognition_shadow_comparison.py`. The field carries the sanitized shadow-pipeline failure category (`"embedding_failure"`, `"vector_failure"`, `None`, or the recorder-side `"unknown"` fallback).
- Replace the `object.__setattr__(comparison, "_failure_category", ...)` mutation in `ProductRecognitionShadowService.compare` with the explicit constructor argument.
- Replace the `getattr(comparison, "_failure_category", None)` reads in `ShadowMetricsRecorder.record` with the explicit field access; the recorder-side `"unknown"` fallback continues to apply when `vector_available is False` and `failure_category is None`.
- Preserve the existing tuple return shape of `ProductRecognitionShadowService.compare` and the existing `ShadowMetricsRecorder.record(...)` signature; the only change is the field type.
- Update the relevant requirement in `openspec/specs/product-recognition-shadow-mode/spec.md` so the comparison dataclass is documented as carrying twelve fields instead of eleven, and the recorder's failure-category path is documented as an explicit field read.

## Capabilities

### New Capabilities

_None — this change does not introduce a new capability._

### Modified Capabilities

- `product-recognition-shadow-mode`: the `ProductRecognitionShadowComparison` dataclass requirement gains a `failure_category: str | None` field (twelve fields instead of eleven); the `ShadowMetricsRecorder` requirement is updated so the failure category is read through the explicit field and the `unknown` fallback is documented.

## Impact

- `backend/services/product_recognition_shadow_comparison.py` — add `failure_category: str | None` field; update the dataclass docstring.
- `backend/services/product_recognition_shadow_service.py` — pass `failure_category` explicitly to the `ProductRecognitionShadowComparison` constructor in `compare`; remove the `object.__setattr__` mutation.
- `backend/services/shadow_metrics_recorder.py` — read `comparison.failure_category` directly in `record`; drop the `_failure_category_unset` / `_failure_category_from` helpers and the `getattr` defensive reads.
- `backend/tests/test_shadow_metrics_recorder.py` — replace the `object.__setattr__` test setup with constructor-based field assignment; assert the explicit field drives the log record.
- `backend/tests/test_product_recognition_shadow_service.py` — replace the `getattr(comparison, "_failure_category", None)` assertion with the direct field access.
- `openspec/specs/product-recognition-shadow-mode/spec.md` — delta spec update for the modified requirement.
- No settings, thresholds, fuzzy-authoritative behavior, customer-visible results, pending contexts, handlers, persistence, vector-search behavior, or logging safety rules change.
- The `Callable[[], ProductPresentationVectorSearchService]` dependency shape stays unchanged.
