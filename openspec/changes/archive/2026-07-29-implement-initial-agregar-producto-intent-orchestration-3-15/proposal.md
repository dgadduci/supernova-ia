## Why

The project now has independent product recognition, normalization, typed intent processing, context classification, and pending-context persistence, but no single entry point coordinates the initial `agregar_producto` pass. Subphase 3.15 adds that orchestration boundary so an incoming message can produce a valid `ProcessedIntent`, persist only valid pending product-selection context, and leave ready intents for a future handler flow.

## What Changes

- Add `process_initial_agregar_producto(db, session, source_text: str) -> ProcessedIntent` in `backend/intents/orchestration/agregar_producto_orchestrator.py`.
- Load the session commerce catalog through the existing service layer.
- Compose `detectar_productos`, `resolve_product_intent`, and `process_agregar_producto` in that order.
- Persist pending intents only when `resolve_context_type` identifies a valid context.
- Return ready intents without executing handlers or generating responses.
- Preserve no-commit, no-rollback, no-persistence-side-effect constraints beyond `set_pending_intent` state mutation.
- Add tests for exact matches, ambiguous matches, invalid pending results, context persistence, and typed return values.

## Capabilities

### New Capabilities
- `agregar-producto-intent-orchestration`: Defines the initial orchestration flow and its side-effect boundaries.

### Modified Capabilities

## Impact

- `backend/intents/orchestration/agregar_producto_orchestrator.py`
- Existing product query service, recognizer, product intent resolver, processor, context-type resolver, and pending-context service integration
- Tests in `backend/tests/api_smoke.py`
- No handler, order, order-line, FastAPI, migration, or external dependency changes.
