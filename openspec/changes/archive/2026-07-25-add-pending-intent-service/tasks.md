## 1. Model and Migration

- [x] 1.1 Modify `backend/models/session.py` to add a `pending_intents` column on the `Session` model:
  - `pending_intents: Mapped[str | None] = mapped_column(Text, nullable=True, default="{}", server_default="{}")`
  - Place the new column after `estado_session` (or in a sensible position) without disturbing the existing fields.
- [x] 1.2 Import `Text` from `sqlalchemy` in `backend/models/session.py` if not already imported.
- [x] 1.3 Hand-write the Alembic migration `backend/alembic/versions/<rev>_add_session_pending_intents.py` that:
  - adds the column `pending_intents` (Text, nullable=True, server_default="{}")
  - leaves the column nullable (the active subphase does not add a `NOT NULL` constraint; future subphases may add it once the persistence surface is mature)
- [x] 1.4 Apply the migration to `supernova_test` (`PYTHONPATH=. venv/bin/alembic upgrade head`) and to `supernova` (`SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova PYTHONPATH=. venv/bin/alembic upgrade head`). Confirm both DBs are at the new head.

## 2. Service Module

- [x] 2.1 Create the empty package marker `backend/intents/services/__init__.py`.
- [x] 2.2 Create `backend/intents/services/pending_intent_service.py` exporting five module-level functions and a `__all__`:
  - `load(session) -> PendingIntents` — read `session.pending_intents` (or `None`), validate via `PendingIntents.model_validate(...)`, return the typed instance.
  - `set_active(session, intent: ProcessedIntent) -> PendingIntents` — set `active` to `intent`, leave queue unchanged, serialize via `PendingIntents.model_dump(mode="json")`, write to `session.pending_intents`, return the new state.
  - `enqueue(session, intent: ProcessedIntent) -> PendingIntents` — append `intent` to `queue`, leave `active` unchanged, serialize, write, return the new state.
  - `remove_active(session) -> PendingIntents` — set `active = queue[0]` (and pop `queue[0]`) if `queue` is non-empty, else `active = None`; serialize, write, return the new state.
  - `clear(session) -> None` — reset to a default `PendingIntents()`, serialize, write, return `None`.
  - Imports: `PendingIntents` from `backend.intents.schemas.pending_intents`; `ProcessedIntent` from `backend.intents.schemas.processed_intent`. Use `from typing import TYPE_CHECKING` for the `Session` model type to avoid circular imports.
  - `__all__ = ["load", "set_active", "enqueue", "remove_active", "clear"]`.

## 3. Verification

- [x] 3.1 Add one test entry to `backend/tests/api_smoke.py` that:
  - creates a `Session` instance (use the existing helpers: pick a `comercio_id` from `_existing_comercio_ids()` and create a `cliente` via `POST /clientes`, then call `POST /sessions` and use the returned id with `TestingSessionLocal` to construct the model instance for in-memory tests; alternatively, use a fresh `Session(...)` with `pending_intents="{}"` for purely in-memory tests);
  - asserts `load(session)` on an empty session returns a default `PendingIntents`;
  - asserts `load(session)` on `pending_intents=None` returns a default `PendingIntents`;
  - asserts `load(session)` on a non-empty session returns the persisted state;
  - asserts `set_active(session, intent)` persists the new active and returns the new state;
  - asserts `enqueue(session, intent)` appends to the queue and returns the new state;
  - asserts `remove_active(session)` promotes the queue head and returns the new state;
  - asserts `remove_active(session)` with an empty queue sets `active = None` and returns the new state;
  - asserts `clear(session)` resets the state and returns `None`;
  - asserts every mutation writes a value to `session.pending_intents` that round-trips through `PendingIntents.model_validate(json.loads(session.pending_intents))`;
  - asserts the module's `__all__` is exactly the five public symbols;
  - asserts the `services/` package contains only `__init__.py` and `pending_intent_service.py`.
- [x] 3.2 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and confirm the new tests pass alongside the existing 274 tests.
- [x] 3.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` to confirm the new files compile.