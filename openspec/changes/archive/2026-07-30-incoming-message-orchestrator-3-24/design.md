## Context

The modern intents pipeline has stabilized two orchestration entry points over the last subphases:

- `backend/intents/orchestration/initial_intent_dispatcher.py` exposes `dispatch_initial_message(db, session, message) -> list[ProcessedIntent]` (Subphase 3.23). It owns the pending-context short-circuit, `IntentClassifier` construction, per-classified-intent dispatch, and rejected-item shaping for fresh messages.
- `backend/intents/orchestration/pending_context_dispatcher.py` exposes `dispatch_pending_context(db, session, message) -> ProcessedIntent` (Subphase 3.18). It owns dispatch into the active `product_selection` context once a classifier or a previous orchestrator has already established one.

Neither module owns the upstream step of "take any inbound message and decide which dispatcher to call". Until now, every consumer would need to branch on `session.context_type` themselves and call the right dispatcher — duplicating the routing rule in every future consumer (FastAPI dependency, background worker, test harness). That violates the project rule that orchestration entry points absorb LLM/recognition/catalog coordination away from callers.

Subphase 3.24 introduces a single thin orchestrator that owns the routing rule and delegates to the two existing dispatchers unchanged. The result is one obvious modern front door for any caller that wants to hand an inbound message off to the intents pipeline.

## Goals / Non-Goals

**Goals:**
- Expose `process_incoming_message(db, session, message) -> list[ProcessedIntent]` as the single modern internal entry point for any inbound message.
- Validate that `message` is a non-empty string before dispatch: `TypeError` for non-string input, `ValueError` for empty / whitespace-only input.
- Route to `dispatch_pending_context(db, session, message)` when `session.context_type is not None`; wrap its `ProcessedIntent` return in a one-item list and return it without invoking the classifier or `dispatch_initial_message`.
- Route to `dispatch_initial_message(db, session, message)` when `session.context_type is None`; return its `list[ProcessedIntent]` unchanged, preserving the order produced by the classifier.
- Stay free of SQLAlchemy queries, repository access, `commit`/`rollback`, FastAPI, Twilio, customer-response generation, handler implementation, and queue promotion.
- Be testable with stub dispatchers; no real LLM call and no `supernova_test` connection required for the orchestrator unit tests.

**Non-Goals:**
- Adding new intents, recognizers, resolvers, processors, handlers, or contracts.
- Modifying `dispatch_initial_message`, `dispatch_pending_context`, `process_initial_agregar_producto`, `IntentClassifier`, or any pending-context service.
- Implementing a FastAPI route, dependency, background task, or Twilio webhook that consumes `process_incoming_message`; the entry point is internal-only for now.
- Implementing queue promotion, retry/backoff, async wrappers, caching, logging, or multi-message history.
- Touching `backend/llm/query_llm.py`, `backend/intents/schemas/intent_classification.py`, `backend/intents/schemas/processed_intent.py`, `backend/config/settings.py`, routers, dependencies, services, repositories, models, or migrations.

## Decisions

- **Module location: `backend/intents/orchestration/incoming_message_orchestrator.py`.** Sits next to `agregar_producto_orchestrator.py`, `initial_intent_dispatcher.py`, and `pending_context_dispatcher.py` so all orchestration entry points share one directory. The package is the project's existing home for LLM-aware, database-aware coordinators that sit between classification and execution.

- **Public surface: a single module-level function.** `process_incoming_message(db, session, message) -> list[ProcessedIntent]` is the only export; `__all__ = ["process_incoming_message"]` keeps the contract narrow and mirrors the discipline of `dispatch_initial_message` and `dispatch_pending_context`.

- **Typing aliases for the two `Session` meanings.** Use `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model — the same aliases already used in `agregar_producto_orchestrator.py` and `initial_intent_dispatcher.py`. This avoids shadowing the most-imported symbol in the module.

- **Message validation runs first, before any dispatcher call.** `process_incoming_message` checks `isinstance(message, str)` (raising `TypeError` on mismatch) and `message.strip()` (raising `ValueError` on empty / whitespace-only) before consulting `session.context_type`. Rationale: validation errors should never depend on routing state; both branches must reject malformed input identically.

- **Pending-context branch wraps the return in a one-item list.** `dispatch_pending_context` returns a single `ProcessedIntent`; `process_incoming_message` returns `list[ProcessedIntent]` to match the initial branch shape. The caller therefore never needs to know which dispatcher actually ran. Rationale: a uniform return type is the whole point of having a single entry point.

- **Initial branch returns the dispatcher's list unchanged.** `dispatch_initial_message` already returns `list[ProcessedIntent]` and already preserves the classified-intent order. `process_incoming_message` does not re-sort, filter, or reshape; it forwards the list as-is. Rationale: any reordering logic would risk dropping items or reordering intents incorrectly; the dispatcher is the source of truth for initial intent order.

- **Routing rule: `session.context_type is not None` → pending, `is None` → initial.** This is the exact rule already encoded inside `dispatch_initial_message` as its short-circuit guard and inside `dispatch_pending_context` as its precondition. `process_incoming_message` is the layer that owns the rule explicitly so neither the caller nor the initial dispatcher has to reason about it twice.

- **No logging in this module.** The dispatchers already log their own events (`IntentClassifier` logs classification start/success/failure; the pending-context dispatcher logs its own audit trail); adding a third logging layer would duplicate events without adding visibility. If a future caller needs a single audit trail it can wrap `process_incoming_message` from outside.

- **Tests: `unittest.TestCase` with stub dispatchers, no real LLM, no `supernova_test` connection.** Match the style of `backend/tests/test_initial_intent_dispatcher.py` and `backend/tests/test_intent_classifier.py`. The test module patches `dispatch_initial_message` and `dispatch_pending_context` at the orchestrator module's import site (`backend.intents.orcherstration.incoming_message_orchestrator.dispatch_initial_message` / `.dispatch_pending_context`) with `MagicMock` returns. No DB session is opened beyond passing a `MagicMock(name="DatabaseSession")`.

## Risks / Trade-offs

- [Risk] Callers may invoke `process_incoming_message` with non-string or empty input and rely on a silent fallback → Mitigation: the orchestrator raises `TypeError` and `ValueError` deterministically before any dispatcher call, matching the validation contract already enforced by `IntentClassifier.query` and `dispatch_pending_context`. Both branches fail identically.

- [Risk] Adding a wrapper layer risks subtle reordering or filtering of `dispatch_initial_message`'s result → Mitigation: the orchestrator returns the dispatcher's list reference unchanged; the test suite asserts identity / contents-preservation so any future accidental reshape is caught immediately.

- [Risk] A future subphase may want to add logging, retry/backoff, or async wrappers here, blurring the routing-only contract → Mitigation: the change is intentionally a thin `if/elif` plus two function calls; no logging, no async, no retry is added. The non-goals section is explicit so future change authors know to fold such additions into a separate subphase.

- [Risk] Returning `list[ProcessedIntent]` (rather than `ProcessedIntent | list[ProcessedIntent]`) hides the pending branch's single-item shape from naive callers → Mitigation: the type annotation is explicit; the test suite asserts the wrapping behavior (pending result is wrapped in a one-item list, not flattened). Callers cannot accidentally treat the pending branch as a multi-intent flow.

- [Risk] The orchestrator adds a third module to the intents orchestration package, increasing import surface → Mitigation: `__all__` discipline keeps the public surface to a single function; the test suite asserts `__all__ == ["process_incoming_message"]` so future drift is caught immediately.

## Migration Plan

1. Add `backend/intents/orchestration/incoming_message_orchestrator.py` exporting `process_incoming_message` with the documented signature and routing behavior; do not touch any other module.
2. Add `backend/tests/test_incoming_message_orchestrator.py` with stub `dispatch_initial_message` and stub `dispatch_pending_context`; cover both routing branches, message validation (non-string, empty, whitespace-only), pending-result wrapping, initial-result pass-through, order preservation, and the no-commit guarantee.
3. Run only the new test module: `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_incoming_message_orchestrator`.
4. Run `PYTHONPATH=. venv/bin/python -m compileall backend` to catch syntax errors.
5. Roll back by deleting the new module and its test file; no other module imports them, so no ripple effects.

## Open Questions

None.
