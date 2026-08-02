## Why

`ProductIntentResolver` still reads the legacy `id` and `source_text` fields, while the current `ProductRecognizer` emits `producto_presentacion_id` and `texto_origen`. This compatibility drift can produce key errors or incorrect candidate and message data when the recognizer and resolver are used together, so Subphase 3.13 should correct the resolver and lock the current contract with focused tests.

## What Changes

- Update confident-match resolution to read `producto_presentacion_id` and preserve `cantidad`.
- Update possible-candidate resolution to populate `candidate_ids` from `producto_presentacion_id` in order.
- Update unavailable and not-found message extraction to use the current recognizer output fields.
- Add minimum regression coverage proving the resolver no longer requires the legacy `id` field.
- Preserve the existing four-key output shape and pure, side-effect-free behavior.

## Capabilities

### New Capabilities

### Modified Capabilities
- `product-intent-resolver`: Align the resolver requirements with the current `ProductRecognizer` output contract and remove the legacy `id` dependency.

## Impact

- `backend/intents/resolvers/product_intent_resolver.py`
- Resolver verification tests in `backend/tests/api_smoke.py`
- Delta specification for `openspec/specs/product-intent-resolver/spec.md`
- No changes to recognizer fuzzy logic, intent contracts, persistence, handlers, APIs, or dependencies.
