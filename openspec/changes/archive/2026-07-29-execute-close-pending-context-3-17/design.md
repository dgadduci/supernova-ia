## Context

Pending context state is stored on the conversation session as a typed active intent plus context type. The agregar-producto handler can execute a ready intent, but lifecycle cleanup must occur only after successful execution. This orchestration component bridges those responsibilities without becoming a generic dispatcher.

## Goals / Non-Goals

**Goals:**
- Load and validate the active pending intent.
- Dispatch the currently supported agregar-producto handler.
- Clear context only after an executed result.
- Preserve context for rejected and failed outcomes.

**Non-Goals:**
- Generic context dispatch or handler registration.
- Queue promotion.
- Database queries, commits, rollback, HTTP, or responses.
- Changes to handlers or recognizers.

## Decisions

- Place the function in `backend/intents/orchestration/pending_context_execution.py` because it coordinates state and handler lifecycle.
- Reuse `pending_intent_service.load` for state loading, `execute_agregar_producto` for execution, and `clear_pending_context` for successful cleanup.
- Return rejected copies for missing active, non-ready, and unsupported handlers, preserving original state when an intent exists.
- Clear context only when the handler returns `executed`; rejected/failed results leave state untouched for future recovery or response handling.
- Support only `handler == "agregar_producto"` to avoid introducing the generic dispatcher ahead of its subphase.

## Risks / Trade-offs

- [Risk] Missing active intent has no object to copy → Mitigation: define a minimal rejected `ProcessedIntent` result for the execution request.
- [Risk] Premature cleanup loses recoverable context → Mitigation: gate cleanup strictly on `status == "executed"`.
- [Risk] Unsupported handlers grow over time → Mitigation: reject explicitly now and defer registry/dispatch abstractions.

## Migration Plan

1. Inspect current pending-state load/clear and handler contracts.
2. Implement the orchestration function and typed rejection paths.
3. Add focused tests for execute/clear, preserve, missing, non-ready, unsupported, and no-commit behavior.
4. Run minimum tests and compile check.
5. Roll back by removing the orchestration module and tests; existing services remain unchanged.

## Open Questions

None.
