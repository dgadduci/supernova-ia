## Context

The modern intents pipeline has stabilized the routing layer over the last subphases:

- `backend/intents/orchestration/incoming_message_orchestrator.py` exposes `process_incoming_message(db, session, message) -> list[ProcessedIntent]` (Subphase 3.24). It validates the message and routes to `dispatch_pending_context` or `dispatch_initial_message`, but deliberately does not call `db.commit()` or `db.rollback()` — persistence is the caller's responsibility.
- `backend/intents/orchestration/initial_intent_dispatcher.py` exposes `dispatch_initial_message(db, session, message) -> list[ProcessedIntent]` (Subphase 3.23) and `dispatch_pending_context(db, session, message) -> ProcessedIntent` lives in `pending_context_dispatcher.py` (Subphase 3.18). Neither one owns commit/rollback; both delegate to the lower-level orchestrators and handlers.

Until now, every future consumer of the modern pipeline (FastAPI dependency, background worker, Twilio webhook adapter, test harness) would have to remember the same three rules:

1. Wrap `process_incoming_message(db, session, message)` in `try:`.
2. On success call `db.commit()` exactly once.
3. On any exception call `db.rollback()` exactly once and re-raise the original.

Duplicating that wrapper in every consumer violates the project's "one obvious entry point" discipline. Subphase 3.26 introduces a thin transactional wrapper that owns the commit/rollback boundary and delegates to the existing orchestrator unchanged. The result is one obvious modern transactional front door for any caller that wants to hand an inbound message off to the intents pipeline and have the persistence boundary managed for them.

## Goals / Non-Goals

**Goals:**

- Expose `process_incoming_message_transactional(db, session, message) -> list[ProcessedIntent]` as the single modern transactional entry point for any inbound message.
- Delegate to `process_incoming_message(db, session, message)` exactly once; do not re-validate the message, do not re-route, do not reshape the result.
- On success (no exception raised by the inner call): call `db.commit()` exactly once and return the inner result unchanged.
- On `rejected` or `failed` business outcomes: still call `db.commit()` exactly once; these are valid business results, not errors.
- On any raised exception: call `db.rollback()` exactly once and re-raise the original exception unchanged (no wrapping, no conversion, no swallowing).
- Stay free of SQLAlchemy queries, repository access, `HTTPException` translation, response generation, Twilio integration, logging, retry/backoff, async wrappers, and caching.
- Be testable with a stubbed `process_incoming_message` and a `MagicMock(name="DatabaseSession")`; no real LLM call and no `supernova_test` connection required for the unit tests.

**Non-Goals:**

- Adding new intents, recognizers, resolvers, processors, handlers, or contracts.
- Modifying `process_incoming_message`, `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, `IntentClassifier`, or any pending-context service.
- Implementing a FastAPI route, dependency, background task, or Twilio webhook that consumes `process_incoming_message_transactional`; the entry point is internal-only for now.
- Implementing retry/backoff, async wrappers, logging, caching, savepoints, nested transactions, or per-intent commits.
- Touching `backend/llm/query_llm.py`, `backend/intents/schemas/intent_classification.py`, `backend/intents/schemas/processed_intent.py`, `backend/config/settings.py`, routers, dependencies, services, repositories, models, or migrations.
- Refreshing or expiring SQLAlchemy models after commit; no `db.refresh()` or `db.expire()` is added.

## Decisions

- **Module location: `backend/intents/orchestration/transactional_message_processor.py`.** Sits next to `incoming_message_orchestrator.py`, `agregar_producto_orchestrator.py`, `initial_intent_dispatcher.py`, and `pending_context_dispatcher.py` so all orchestration entry points share one directory. The package is the project's existing home for LLM-aware, database-aware coordinators that sit between classification and execution.

- **Public surface: a single module-level function.** `process_incoming_message_transactional(db, session, message) -> list[ProcessedIntent]` is the only export; `__all__ = ["process_incoming_message_transactional"]` keeps the contract narrow and mirrors the discipline of `process_incoming_message`, `dispatch_initial_message`, and `dispatch_pending_context`.

- **Typing aliases for the two `Session` meanings.** Use `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model — the same aliases already used in `incoming_message_orchestrator.py`, `agregar_producto_orchestrator.py`, and `initial_intent_dispatcher.py`. This avoids shadowing the most-imported symbol in the module.

- **Single try/except with no `else` branch.** The wrapper calls `process_incoming_message(db, session, message)` inside `try:`; on success it falls through to `db.commit()` and `return result`; on any exception it executes `db.rollback()` and `raise` (re-raising the original via bare `raise`). Rationale: a single `try/except` keeps the success path linear and the failure path linear, with no overlap between `commit()` and `rollback()`. A `try/commit/except/rollback/raise` shape is preferred over `try/commit/else/return` because it makes the commit-vs-rollback boundary explicit and makes accidental double-commit impossible.

- **Bare `raise`, not `raise exception`.** The wrapper uses `raise` inside the `except` block to re-raise the original exception unchanged. Rationale: `raise e` would attach the current traceback frame to the exception; `raise` preserves the original traceback and matches Python's recommended exception-propagation pattern. The minimum tests assert `pytest.raises` sees the exact same exception type and instance.

- **`rejected` and `failed` results are committed, not rolled back.** The success path is "no exception was raised by `process_incoming_message`". A returned `ProcessedIntent` with `status == "rejected"` or `status == "failed"` is a valid business outcome (e.g., the LLM could not classify the message, or the handler rejected the line item); it must still be persisted exactly like an `executed` outcome. Rationale: the dispatcher already shapes `rejected` results inside a list — the transactional wrapper should treat the entire list as one atomic outcome and commit on success regardless of the per-item status.

- **No `db.refresh()`, no `db.expire()`, no `db.flush()` call from this wrapper.** The wrapper only calls `commit()` and `rollback()` on the SQLAlchemy session. Refresh and flush remain the responsibility of the layer that needs post-commit visibility (e.g., a future API response builder). Rationale: the project rule "do not refresh models unless an existing test proves it is necessary" is binding; no existing test requires refresh here, so the wrapper does not introduce it.

- **No retry, no backoff, no async wrapper.** If `process_incoming_message` raises, the wrapper rolls back once and re-raises; it never retries the call. Rationale: any retry policy belongs to a future caller that knows the deployment's idempotency story (Twilio webhook retries, queue worker redelivery). The wrapper is intentionally the smallest possible commit/rollback boundary so any future policy can wrap it without undoing its work.

- **No logging in this module.** The dispatchers already log their own events; adding a third logging layer would duplicate events without adding visibility. If a future caller needs a single audit trail it can wrap `process_incoming_message_transactional` from outside.

- **Tests: `unittest.TestCase` with stubbed `process_incoming_message`, no real LLM, no `supernova_test` connection.** Match the style of `backend/tests/test_incoming_message_orchestrator.py`. The test module patches `process_incoming_message` at the new module's import site (`backend.intents.orchestration.transactional_message_processor.process_incoming_message`) with `MagicMock` returns; a `MagicMock(name="DatabaseSession")` stands in for the SQLAlchemy session so `db.commit` / `db.rollback` can be asserted without a real connection.

## Risks / Trade-offs

- [Risk] A caller may invoke `process_incoming_message` directly and forget to wrap it in commit/rollback, bypassing the new boundary → Mitigation: the spec is explicit that `process_incoming_message` is internal-only and that any future consumer (FastAPI dependency, background worker, Twilio webhook adapter) must call `process_incoming_message_transactional`. Future subphases that expose the pipeline to HTTP, queue, or webhook layers must fold the boundary into the entry point rather than re-wrapping `process_incoming_message`.

- [Risk] The wrapper commits even when every item in the returned list is `rejected`, which may not be what every future caller wants → Mitigation: rejected/failed outcomes are valid business outcomes; the dispatcher already shapes them, and the spec is explicit that they commit. If a future caller needs to drop the entire transaction on rejected outcomes, it can wrap `process_incoming_message_transactional` in a conditional instead of reaching past it.

- [Risk] A future subphase may want to add logging, retry/backoff, or async wrappers here, blurring the commit/rollback-only contract → Mitigation: the wrapper is intentionally a single `try/except` plus `commit()`/`rollback()`/`raise`; no logging, no async, no retry is added. The non-goals section is explicit so future change authors know to fold such additions into a separate subphase.

- [Risk] Adding a fourth module to the intents orchestration package increases import surface → Mitigation: `__all__` discipline keeps the public surface to a single function; the test suite asserts `__all__ == ["process_incoming_message_transactional"]` so future drift is caught immediately.

- [Risk] The wrapper assumes the SQLAlchemy session is the unit of work and that calling `commit()` exactly once is safe → Mitigation: the spec, the minimum tests, and the non-goals section all forbid savepoints, nested transactions, and multiple commits; the wrapper commits at most once and rolls back at most once per call. A future caller that needs savepoints can wrap the session in its own context manager.

## Migration Plan

1. Add `backend/intents/orchestration/transactional_message_processor.py` exporting `process_incoming_message_transactional` with the documented signature and try/commit-or-rollback/raise behavior; do not touch any other module.
2. Add `backend/tests/test_transactional_message_processor.py` with a stubbed `process_incoming_message`; cover the success path (`commit` called exactly once, no `rollback`, result returned), the `rejected` / `failed` business-outcome commit path (same assertions), the exception path (`rollback` called exactly once, no `commit`, original exception re-raised unchanged), and the `__all__` discipline.
3. Run only the new test module: `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_transactional_message_processor`.
4. Run `PYTHONPATH=. venv/bin/python -m compileall backend` to catch syntax errors.
5. Run `openspec validate incoming-message-transactional-processor-3-26 --strict` and confirm valid.
6. Roll back by deleting the new module and its test file; no other module imports them, so no ripple effects.

## Open Questions

None.
