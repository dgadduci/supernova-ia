## Context

Phase 3 (Intents) is layering up to the dispatch path. Subphases 3.3–3.9 produced the static contract, per-requirement state, the per-intent envelope, the conversation-wide state, the resolver, the processor, the persistence service for `pending_intents`, the `ContextType` enum, and the `ContextTypeResolver`. The next layer is the *entry-point* — the function that ties them together when a new WhatsApp message arrives. The active subphase introduces both a new `Session` column (`context_type`) and the service that owns the entry-point flow. The service is the smallest, narrowest piece of the dispatch path that has well-defined input/output contract.

## Goals / Non-Goals

**Goals:**

- Add a `context_type` column to the `Session` model: `Mapped[str | None]` typed as `String(50)`, nullable, no default.
- Add an Alembic migration that creates the column on both `supernova` and `supernova_test`, with no backfill (pre-existing rows are NULL).
- Add `backend/intents/context/pending_context_service.py` exporting two functions and a `__all__`:
  - `set_pending_intent(session, intent: ProcessedIntent) -> PendingIntents`
  - `clear_pending_context(session) -> None`
- `set_pending_intent`:
  1. Validates `intent.status == "pending_resolution"`; raises `ValueError` otherwise.
  2. Resolves the context with `resolve_context_type(intent)`; raises `ValueError` if the result is `None`.
  3. Stores the intent as active using `set_active(session, intent)` from `PendingIntentService`.
  4. Assigns `session.context_type = context_type.value` (a `str`).
  5. Returns the resulting `PendingIntents`.
- `clear_pending_context`:
  1. Clears pending intents using `clear(session)` from `PendingIntentService`.
  2. Assigns `session.context_type = None`.
- Both functions are **in-memory mutations**; the caller is responsible for committing.
- The service does not call recognizers, handlers, repositories, generate responses, or log.
- One test covers: saving a valid pending product-selection intent; rejecting a non-pending intent; rejecting a pending intent without resolvable context; clearing both `pending_intents` and `context_type`.

**Non-Goals:**

- No router, no FastAPI endpoint, no commit, no transaction manager. The caller owns the SQLAlchemy session and the commit.
- No additional `ContextType` values, no new resolvers, no changes to `PendingIntentService` or `ContextTypeResolver`.
- No `context_type` value parsing on read (today the value is a `str`; a future subphase may introduce a `ContextType(session.context_type)` conversion when reading).
- No migration of pre-existing `Session` rows to a default `context_type` (the column is nullable; future subphases may backfill).

## Decisions

- **D1 — `context_type` is `String(50)`, not a SQLAlchemy `Enum`.** The spec writes `session.context_type = context_type.value` (a `str`). To match the spec's API without coercion surprises, the column is `String(50)`. A future subphase may migrate to a SQLAlchemy `Enum` if it needs Python-typed reads. Today the value is plain text.
- **D2 — The column is nullable, no default.** Pre-existing `Session` rows have `NULL` after the migration. A future subphase that introduces a backfill will run separately. The active subphase does not preempt the backfill design.
- **D3 — `set_pending_intent` raises `ValueError` for both invalid cases.** The spec mandates it. The error message should be descriptive: `"intent.status must be 'pending_resolution' (got '<actual>')"` for the status check, `"no ContextType can be resolved for the given intent"` for the resolver check.
- **D4 — The service mutates the model in memory and returns the new state.** The function returns `PendingIntents` (from `set_active`) for the setter, and `None` for the clearer. The caller is responsible for committing. This matches the pattern of `PendingIntentService` (subphase 3.7).
- **D5 — The service does not validate the resolved context against the session's existing `context_type`.** If the caller has already set `context_type` to a different value and now passes a different intent, the service overwrites the column. A future subphase may add a check that prevents a session from switching contexts mid-flight. Today the service is a thin coordinator.
- **D6 — `__all__` is declared.** Two public symbols: `set_pending_intent`, `clear_pending_context`. Mirrors the prior subphases' `__all__` discipline.
- **D7 — File location: `backend/intents/context/pending_context_service.py`.** The spec mandates the path. The `backend/intents/context/` package is the home for intent classification and dispatch concerns. `context_type_resolver.py` (subphase 3.9) lives alongside; future resolvers and dispatch helpers slot in too.
- **D8 — No external side effects.** The function does not call `print`, does not log, does not mutate the input `intent` (it only reads from it), does not raise on unexpected input beyond the two `ValueError` cases the spec mandates.

## Risks / Trade-offs

- **[Risk] The `pending_intents` and `context_type` columns are not written atomically.** A commit that fails between the two `session.X = Y` assignments leaves the model in an inconsistent state. → Acceptable: the service is in-memory mutation; the caller owns the commit. A future subphase may wrap the call in a single transaction.
- **[Risk] The `ValueError` for "no resolvable context" is broad.** A future caller may want to distinguish "intent is not pending" from "no context for this pending intent". → Acceptable for the active subphase: the spec mandates a single `ValueError` for both. A future subphase may split the exceptions.
- **[Trade-off] Reading `session.context_type` returns a `str`, not a `ContextType` member.** A future subphase that consumes the column will need to wrap the read in `ContextType(session.context_type)`. Today the service is a write-only coordinator.

## Open Questions

- None. The two function signatures, the validation rules, the `session.context_type` storage, the file location, and the "no side effects" constraint are all fixed by Subphase 3.10 in `project.md`.