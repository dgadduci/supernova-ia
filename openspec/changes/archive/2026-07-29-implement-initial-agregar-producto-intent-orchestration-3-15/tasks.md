## 1. Orchestrator Implementation

- [x] 1.1 Inspect existing product catalog service, recognizer, product intent resolver, agregar-producto processor, context-type resolver, and pending-context service signatures.
- [x] 1.2 Create `backend/intents/orchestration/agregar_producto_orchestrator.py` exporting `process_initial_agregar_producto(db, session, source_text: str) -> ProcessedIntent`.
- [x] 1.3 Compose catalog loading, `detectar_productos`, `resolve_product_intent`, and `process_agregar_producto` without duplicating component logic or placing SQLAlchemy queries in the orchestrator.
- [x] 1.4 Persist pending context only when `resolve_context_type` returns a valid context; return ready and invalid-pending intents without handlers or customer responses.
- [x] 1.5 Preserve transaction ownership by avoiding commit/rollback and keep `__all__` limited to the orchestration function.

## 2. Verification

- [x] 2.1 Add tests for exact product results producing `ready` without handler execution.
- [x] 2.2 Add tests for ambiguous presentations producing `pending_resolution` with candidate IDs.
- [x] 2.3 Add tests proving valid product-selection pending context is stored and `session.context_type` is set.
- [x] 2.4 Add tests proving unknown/unavailable or invalid pending results are not persisted.
- [x] 2.5 Add tests proving no commit, rollback, order mutation, handler execution, or response generation occurs and the return value is a valid `ProcessedIntent`.
- [x] 2.6 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and summarize the complete initial flow.
- [x] 2.7 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.
