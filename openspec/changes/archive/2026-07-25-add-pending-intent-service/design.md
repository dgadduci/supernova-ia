## Context

Phase 3 (Intents) is layering up the runtime. Subphase 3.4 introduced `PendingIntents` as the conversation-wide state. Subphases 3.1–3.6 produced the static contract, per-requirement state, the per-intent envelope, the recognizer-adapter resolver, and the processor. The state has nowhere to live yet. The spec for subphase 3.7 assumes a `pending_intents` column on the `Session` model and a service that owns the read/write/promote lifecycle. This subphase adds the column, the migration, the service, and the tests.

## Goals / Non-Goals

**Goals:**

- Add a `pending_intents` column to the `Session` model: `Text`, nullable, server default `"{}"`.
- Add an Alembic migration that creates the column on both `supernova` and `supernova_test`, with a backfill default of `"{}"` for any pre-existing rows.
- Add a `backend/intents/services/` Python package and `backend/intents/services/pending_intent_service.py` exporting five module-level functions: `load`, `set_active`, `enqueue`, `remove_active`, `clear`.
- `load(session)` reads `session.pending_intents` (or `None`), validates with `PendingIntents.model_validate(...)`, and returns the typed instance.
- `set_active(session, intent)` sets `active` to `intent` and serializes.
- `enqueue(session, intent)` appends `intent` to `queue` and serializes.
- `remove_active(session)` promotes the head of `queue` to `active` (if any), serializes, and returns the new state.
- `clear(session)` resets the state to the default empty `PendingIntents` (no `active`, empty `queue`) and serializes.
- Every mutation serializes the new state with `PendingIntents.model_dump(mode="json")` and writes it back to `session.pending_intents`.
- The service does not commit, query repositories, execute handlers, or manage transactions.
- One test covers: loading an empty session, setting the active intent, enqueueing an intent, promoting the queue after removing the active intent, and clearing pending intents.

**Non-Goals:**

- No router, no FastAPI endpoint, no DB session management, no commit/rollback. The caller is responsible for the SQLAlchemy session and the commit.
- No additional state transitions beyond the spec (e.g. a `mark_executed` that walks the lifecycle to `executed`). The future handler subphase owns that.
- No additional intent processors (the service is specific to `PendingIntents`).
- No persistence beyond the column on `Session`. A future subphase may introduce a separate `IntentState` table for richer history; that is out of scope.

## Decisions

- **D1 — The `pending_intents` column is `Text`, not `JSON`.** SQLAlchemy 2.x supports a `JSON` type, but `Text` is portable across PostgreSQL without a JSONB extension check, and the spec describes the value as "JSON-compatible" (which `Text` is, by virtue of storing a JSON string). Pydantic owns the JSON contract via `model_dump(mode="json")` and `model_validate(...)`. A future subphase may migrate the column to `JSON` if queries on the field become necessary.
- **D2 — Server default is `"{}"`, not `None`.** New `Session` rows get a valid empty JSON string by default, so `model_validate(session.pending_intents)` always succeeds on a fresh row. The column is still nullable for backfill safety on pre-existing rows that may have a `NULL` value before the migration runs.
- **D3 — The migration adds the column as nullable with a server default and a backfill.** The Alembic migration:
  1. `op.add_column("sessions", sa.Column("pending_intents", sa.Text(), nullable=True, server_default="{}"))`
  2. `op.alter_column("sessions", "pending_intents", existing_type=sa.Text(), nullable=False, server_default="{}")` — only if the dev/test database has no rows. The active subphase keeps the column nullable to match the test environment's tendency to truncate and re-seed; a future subphase may add the `NOT NULL` migration once the persistence surface is mature.
- **D4 — Service parameter `session` is the `Session` model instance, not the SQLAlchemy session.** The spec writes `load(session)` and `PendingIntents.model_validate(session.pending_intents or {})`. The parameter must have a `.pending_intents` attribute; the only type in the project with that attribute is the `Session` model. To avoid name shadowing with the SQLAlchemy `Session` class, the implementation imports the SQLAlchemy session as `SqlSession` (consistent with subphase 2.14's `pedido_producto_service.py`).
- **D5 — The service mutates the model in memory and returns the new state.** Each mutation function:
  1. Calls `current = load(session)`.
  2. Applies the change in a local Python object (a new `PendingIntents`).
  3. Calls `session.pending_intents = new_state.model_dump(mode="json")`.
  4. Returns `new_state`.
  The caller is responsible for committing. The service does not raise on a missing commit; the next read sees the in-memory change immediately because `session.pending_intents` was reassigned on the model instance.
- **D6 — `enqueue` and `set_active` always read the current state first.** No caching, no global state. This keeps the service trivially testable: two consecutive calls on the same `session` instance see each other's effect (because each one reads `session.pending_intents` afresh).
- **D7 — `remove_active` promotion rule.** The function reads the current state, sets `active = queue[0]` if `queue` is non-empty (and pops it), and clears `active` to `None` if `queue` is empty. The serialized form is then written back. This is the "first queued intent becomes active" rule the spec mandates.
- **D8 — `clear` resets to a default `PendingIntents()` and serializes.** No special "delete the column" behavior; the column is preserved with the empty JSON.
- **D9 — `load` tolerates a `None` value.** If `session.pending_intents is None` (a row that pre-dates the migration), `load` returns a default `PendingIntents()`. The spec text says `model_validate(session.pending_intents or {})`; the `or {}` is the implementation.
- **D10 — `__all__` declares every public function.** Five functions: `load`, `set_active`, `enqueue`, `remove_active`, `clear`. This keeps the test introspection consistent with the prior subphases.

## Risks / Trade-offs

- **[Risk] Concurrent writes to the same `session.pending_intents` from two adapters may lose updates.** → Acceptable for the active subphase: the model lives in a single SQLAlchemy session, and the active subphase introduces no concurrency. A future subphase may add a JSON merge or a pessimistic lock.
- **[Risk] The `Text` column is not queryable in PostgreSQL JSONB style.** → Acceptable: the spec does not require querying the field. A future subphase may migrate the column to `JSON` if queryability becomes necessary.
- **[Trade-off] Service mutates the model in memory and does not commit.** → Matches the existing pattern (e.g. `pedido_producto_service`). The caller is responsible for `session.commit()`. Tests do not require a commit to observe the mutation because each test reads `session.pending_intents` directly on the same instance.

## Open Questions

- None. The function signatures, the column type, the serialization rules, and the "no commit / no repository / no handler / no transaction" constraint are all fixed by Subphase 3.7 in `project.md`.