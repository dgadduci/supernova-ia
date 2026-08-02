## ADDED Requirements

### Requirement: Rejected handler result clears pending context

When the dispatched handler returns a `ProcessedIntent` whose `status == "rejected"`, the function SHALL call `clear_pending_context(session)` exactly once and SHALL set `session.context_type = None` exactly once, then return the rejected intent. The function SHALL NOT clear pending context for any other status (`executed`, `pending_resolution`, `failed`). The function SHALL NOT swallow a raised exception thrown by the handler; the exception propagates unchanged so the transactional wrapper's `db.rollback()` is preserved.

#### Scenario: Rejected result clears pending context

- **WHEN** the active intent is `ready` and `execute_agregar_producto` returns a `ProcessedIntent` with `status == "rejected"`
- **THEN** the function calls `clear_pending_context(session)` exactly once, sets `session.context_type = None` exactly once, and returns the rejected intent

#### Scenario: Failed handler result preserves pending context

- **WHEN** the active intent is `ready` and `execute_agregar_producto` returns a `ProcessedIntent` with `status == "failed"`
- **THEN** the function does NOT call `clear_pending_context(session)` and does NOT assign `session.context_type`, and returns the failed intent

#### Scenario: Executed handler result still clears pending context

- **WHEN** the active intent is `ready` and `execute_agregar_producto` returns a `ProcessedIntent` with `status == "executed"`
- **THEN** the function calls `clear_pending_context(session)` exactly once and sets `session.context_type = None` exactly once, and returns the executed intent (this is the existing behavior preserved by the new contract)

#### Scenario: Raised exception propagates unchanged

- **WHEN** the handler raises any exception (e.g. `IntegrityError`, `OperationalError`, `RuntimeError`)
- **THEN** the exception propagates out of `execute_ready_pending_context` unchanged, no `clear_pending_context` call is made, and `session.context_type` is not modified

### Requirement: Definitive rejection routes the next unrelated message back to initial classification

After a definitive `rejected` handler result, `session.context_type` SHALL be `None` and `session.pending_intents` SHALL be the empty default. The next message that arrives through `process_incoming_message` SHALL therefore be routed through `dispatch_initial_message` (not `dispatch_pending_context`), regardless of the `intent` field of the rejected `ProcessedIntent`.

#### Scenario: Definitive rejected then unrelated message reaches initial classification

- **WHEN** the function returns a rejected intent (so `session.context_type = None` and `session.pending_intents` is empty)
- **THEN** the next call to `process_incoming_message(db, session, "hola")` reaches `dispatch_initial_message` and reaches `IntentClassifier` for the new message, and the rejected intent is NOT preserved as active

#### Scenario: Failed handler result keeps the next message on pending context

- **WHEN** the function returns a failed intent (so `session.context_type` and `session.pending_intents` remain unchanged)
- **THEN** the next call to `process_incoming_message(db, session, <retry>)` is routed through `dispatch_pending_context` and never reaches `IntentClassifier`
