## 1. Model and Migration

- [x] 1.1 Modify `backend/models/session.py` to add a `context_type` column on the `Session` model:
  - `context_type: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)`
  - Place the new column after `pending_intents` (or in a sensible position) without disturbing the existing fields.
- [x] 1.2 Import `String` from `sqlalchemy` in `backend/models/session.py` if not already imported.
- [x] 1.3 Hand-write the Alembic migration `backend/alembic/versions/<rev>_add_session_context_type.py` that:
  - adds the column `context_type` (String(50), nullable=True, no server default)
  - does NOT backfill pre-existing rows (the column is nullable, so existing rows are NULL)
- [x] 1.4 Apply the migration to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm both DBs are at the new head.

## 2. Service Module

- [x] 2.1 Create `backend/intents/context/pending_context_service.py` exporting two functions and a `__all__`:
  - `set_pending_intent(session, intent: ProcessedIntent) -> PendingIntents` — pure orchestration, no I/O, no DB, no recognizer, no handler.
    - Imports: `ProcessedIntent` from `backend.intents.schemas.processed_intent`; `PendingIntents` from `backend.intents.schemas.pending_intents`; `resolve_context_type` from `backend.intents.context.context_type_resolver`; `set_active` from `backend.intents.services.pending_intent_service`; `ContextType` from `backend.sessions.enums.context_type`.
    - The function:
      1. Validates `intent.status == "pending_resolution"`; raises `ValueError(f"intent.status must be 'pending_resolution' (got '{intent.status}')")` otherwise.
      2. Calls `context_type = resolve_context_type(intent)`. If `context_type is None`, raises `ValueError("no ContextType can be resolved for the given intent")`.
      3. Calls `state = set_active(session, intent)` from `PendingIntentService` to persist the intent as active.
      4. Assigns `session.context_type = context_type.value` (a `str`).
      5. Returns `state`.
  - `clear_pending_context(session) -> None` — pure orchestration, no I/O, no DB.
    - The function:
      1. Calls `clear(session)` from `PendingIntentService` to reset `pending_intents`.
      2. Assigns `session.context_type = None`.
      3. Returns `None`.
  - `__all__ = ["set_pending_intent", "clear_pending_context"]`.

## 3. Verification

- [x] 3.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - imports `set_pending_intent`, `clear_pending_context`, `PendingIntentService`;
  - creates a `SessionModel` instance with `pending_intents = "{}"` and `context_type = None`;
  - asserts a valid pending product-selection intent is stored: `set_pending_intent` returns a `PendingIntents` with the intent as `active`; `session.context_type == "product_selection"`; `PendingIntentService.load(session).active` is the intent; rejects the same intent twice is idempotent (set then check is consistent);
  - asserts `set_pending_intent` raises `ValueError` for `intent.status in {"ready", "executed", "rejected", "failed"}` and does not mutate `session.context_type` or `session.pending_intents`;
  - asserts `set_pending_intent` raises `ValueError` for a pending intent with a `completed` `producto_presentacion_id` requirement (no resolvable context) and does not mutate either field;
  - asserts `set_pending_intent` raises `ValueError` for a pending intent with empty `candidate_ids` and does not mutate either field;
  - asserts `set_pending_intent` returns a `PendingIntents` whose serialized form equals `PendingIntentService.load(session).model_dump(mode="json")`;
  - asserts `clear_pending_context` after a set leaves `session.context_type is None` and `PendingIntentService.load(session).active is None` with `queue == []`;
  - asserts `clear_pending_context` after only setting `session.context_type = "product_selection"` directly leaves both fields at default;
  - asserts `clear_pending_context` after only setting `pending_intents` via `set_active` leaves `session.context_type is None` and `pending_intents` is default;
  - asserts `clear_pending_context` on a fresh session returns `None` and leaves the session unchanged;
  - asserts the module's `__all__` is exactly `{"set_pending_intent", "clear_pending_context"}`;
  - asserts `backend/intents/context/` contains exactly `{"context_type_resolver.py", "pending_context_service.py"}` (plus the `__init__.py` from subphase 3.9).
- [x] 3.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 315 tests.
- [x] 3.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new file compiles.