## Context

The pending-context execution component handles ready agregar_producto intents, but the conversation runtime lacks an entry point that decides which per-context path to follow based on `session.context_type`. The dispatcher must advance the active pending intent for `product_selection`, persist the outcome, and trigger execution only when the intent becomes ready.

## Goals / Non-Goals

**Goals:**
- Provide a single message-routing entry point keyed by `session.context_type`.
- Reuse existing pending-intent and pending-context execution components.
- Persist updated active intent for both `pending_resolution` and `ready` outcomes.
- Reject unsupported or invalid context types without clearing pending state.

**Non-Goals:**
- Classifying or detecting new intents from raw messages.
- Queue promotion, response generation, HTTP handling, or router integration.
- Direct SQLAlchemy or repository access; commits or rollback.
- Modifying handlers, recognizers, processors, or pending-context rules.

## Decisions

- Place the dispatcher in `backend/intents/orchestration/pending_context_dispatcher.py` because it routes between per-context components and the pending state.
- Reuse `pending_intent_service.load` for state validation and `set_active` to persist updated active intents.
- Dispatch only `product_selection` through `ProductSelectionContextService.resolve`; defer all other contexts to future subphases.
- Persist the pending result with `set_active` whenever the resulting status remains `pending_resolution` or becomes `ready`, preserving pending context.
- Trigger `execute_ready_pending_context` only when the dispatched result becomes `ready`, allowing the existing handler boundary to own context cleanup.
- Treat missing active intent or missing context type as a rejected, context-preserving outcome.
- Limit the public surface to `dispatch_pending_context`.

## Risks / Trade-offs

- [Risk] Missing or invalid active intent produces no persisted state → Mitigation: return a typed rejected `ProcessedIntent` without modifying the session.
- [Risk] Future context types grow this dispatcher → Mitigation: reject explicitly and document that additional contexts are deferred to their own subphases.
- [Risk] Persisting updated active intent twice (dispatcher + execution) → Mitigation: dispatcher persists the dispatched result; execution only owns ready/executed transitions and cleanup.

## Migration Plan

1. Inspect current pending-state load/persist, per-context orchestration, and pending-context execution components.
2. Implement dispatcher and transitions for the `product_selection` context only.
3. Add focused tests for pending/reject/execute paths, including context preservation.
4. Run minimum tests and compile check.
5. Roll back by removing the dispatcher module and tests; existing components remain unchanged.

## Open Questions

None.
