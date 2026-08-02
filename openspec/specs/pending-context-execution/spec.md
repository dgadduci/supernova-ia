## Purpose

Execute ready pending intents while preserving validation, dispatch, cleanup, and orchestration boundaries.
## Requirements
### Requirement: Pending context execution function
The system SHALL export `execute_ready_pending_context(db: DatabaseSession, session: ConversationSession) -> ProcessedIntent` from `backend/intents/orchestration/pending_context_execution.py`.

#### Scenario: Function is importable
- **WHEN** a module imports `execute_ready_pending_context`
- **THEN** the import succeeds and the binding is callable

### Requirement: Active ready intent validation
The function SHALL load pending state through `PendingIntentService`, require an active intent, and require `active.status == "ready"` before handler execution.

#### Scenario: Missing active intent is rejected
- **WHEN** pending state has no active intent
- **THEN** the function returns a rejected `ProcessedIntent` without handler execution or context cleanup

#### Scenario: Non-ready active intent is rejected
- **WHEN** the active intent status is not `ready`
- **THEN** the function returns a rejected copy and leaves pending context unchanged

### Requirement: Agregar producto dispatch
The function SHALL dispatch active intents whose `handler == "agregar_producto"` and `status == "ready"` to `execute_agregar_producto(db, session, active)`.

#### Scenario: Ready agregar_producto is executed
- **WHEN** a ready active intent has handler `agregar_producto`
- **THEN** the function delegates exactly once to the agregar-producto handler

### Requirement: Quitar producto dispatch
The function SHALL dispatch active intents whose `handler == "quitar_producto"` and `status == "ready"` to `execute_quitar_producto(db, session, active)`.

#### Scenario: Ready quitar_producto is executed
- **WHEN** a ready active intent has handler `quitar_producto`
- **THEN** the function delegates exactly once to the quitar-producto handler

### Requirement: Modificar producto dispatch
The function SHALL dispatch active intents whose `handler == "modificar_producto"` and `status == "ready"` to `execute_modificar_producto(db, session, active)`.

#### Scenario: Ready modificar_producto is executed
- **WHEN** a ready active intent has handler `modificar_producto`
- **THEN** the function delegates exactly once to the modificar-producto handler

#### Scenario: modificar_producto does not invoke other handlers
- **WHEN** a ready active intent has handler `modificar_producto`
- **THEN** `execute_agregar_producto` and `execute_quitar_producto` are NOT invoked

### Requirement: Unsupported handler is rejected
When a ready active intent names a handler that is neither `agregar_producto`, `quitar_producto`, nor `modificar_producto`, the function SHALL return a rejected copy without handler execution.

#### Scenario: Ready unsupported handler is rejected
- **WHEN** a ready active intent names a handler that is not `agregar_producto`, `quitar_producto`, or `modificar_producto`
- **THEN** the function returns a rejected copy without invoking any handler

### Requirement: Successful context cleanup
When handler execution returns `status == "executed"`, the function SHALL call `clear_pending_context(session)`, clearing pending intents and setting context type to `None`, then return the executed intent. This applies to `agregar_producto`, `quitar_producto`, and `modificar_producto` handlers.

#### Scenario: Executed result clears context
- **WHEN** the dispatched handler returns an executed intent (agregar_producto, quitar_producto, or modificar_producto)
- **THEN** pending state is cleared, context type becomes `None`, and the executed intent is returned

### Requirement: Execution orchestration boundaries
The function SHALL reuse `load`, `clear_pending_context`, and `execute_agregar_producto`; it SHALL not perform SQLAlchemy queries, repository access, commits, rollback, HTTP concerns, response generation, queue promotion, handler changes, or recognizer changes.

#### Scenario: No transaction or infrastructure side effects
- **WHEN** the function completes any path
- **THEN** it has not committed, rolled back, queried repositories, generated responses, or promoted a queue

### Requirement: Public surface is limited
The module SHALL export only `execute_ready_pending_context` through `__all__` and SHALL not introduce a generic context dispatcher.

#### Scenario: Single public execution symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["execute_ready_pending_context"]`

### Requirement: Rejected handler result clears pending context

When the dispatched handler (agregar_producto, quitar_producto, or modificar_producto) returns a `ProcessedIntent` whose `status == "rejected"`, the function SHALL call `clear_pending_context(session)` exactly once and SHALL set `session.context_type = None` exactly once, then return the rejected intent. The function SHALL NOT clear pending context for any other status (`executed` is handled by the existing cleanup rule above; `pending_resolution` and `failed` preserve context). The function SHALL NOT swallow a raised exception thrown by the handler; the exception propagates unchanged so the transactional wrapper's `db.rollback()` is preserved.

#### Scenario: Rejected result clears pending context

- **WHEN** the active intent is `ready` and the dispatched handler returns a `ProcessedIntent` with `status == "rejected"`
- **THEN** the function calls `clear_pending_context(session)` exactly once, sets `session.context_type = None` exactly once, and returns the rejected intent

#### Scenario: Failed handler result preserves pending context

- **WHEN** the active intent is `ready` and the dispatched handler returns a `ProcessedIntent` with `status == "failed"`
- **THEN** the function does NOT call `clear_pending_context(session)` and does NOT assign `session.context_type`, and returns the failed intent

#### Scenario: Raised exception propagates unchanged

- **WHEN** the handler raises any exception (e.g. `IntegrityError`, `OperationalError`, `RuntimeError`)
- **THEN** the exception propagates out of `execute_ready_pending_context` unchanged, no `clear_pending_context` call is made, and `session.context_type` is not modified

### Requirement: Definitive rejection routes the next unrelated message back to initial classification

After a definitive `rejected` handler result, `session.context_type` SHALL be `None` and `session.pending_intents` SHALL be the empty default. The next message that arrives through `process_incoming_message` SHALL therefore be routed through `dispatch_initial_message` (not `dispatch_pending_context`), regardless of the `intent` field of the rejected `ProcessedIntent`. This applies to `agregar_producto`, `quitar_producto`, and `modificar_producto` handlers.

#### Scenario: Definitive rejected then unrelated message reaches initial classification

- **WHEN** the function returns a rejected intent (so `session.context_type = None` and `session.pending_intents` is empty)
- **THEN** the next call to `process_incoming_message(db, session, "hola")` reaches `dispatch_initial_message` and reaches `IntentClassifier` for the new message, and the rejected intent is NOT preserved as active

#### Scenario: Failed handler result keeps the next message on pending context

- **WHEN** the function returns a failed intent (so `session.context_type` and `session.pending_intents` remain unchanged)
- **THEN** the next call to `process_incoming_message(db, session, <retry>)` is routed through `dispatch_pending_context` and never reaches `IntentClassifier`

### Requirement: Ready agregar_producto queue draining
Pending-context execution SHALL return an ordered `list[ProcessedIntent]`. For `agregar_producto`, it SHALL execute the active ready intent, append its outcome, promote after each definitive `executed` or `rejected` result, and continue executing consecutive promoted ready additions.

#### Scenario: Two ready additions execute in FIFO order
- **WHEN** the active addition and the queue head are both ready
- **THEN** both handlers execute exactly once in FIFO order and both outcomes are returned in that order

#### Scenario: Definitive rejection does not discard later addition
- **WHEN** the active handler returns `rejected` and the promoted queue head is ready
- **THEN** the rejected outcome is returned first and the promoted addition executes and is returned second

### Requirement: Queue draining pauses at unresolved or failed work
Execution SHALL stop when the promoted active addition has `status == "pending_resolution"` or when a handler returns `failed`, preserving that active item and the remaining queue.

#### Scenario: Promotion reaches unresolved addition
- **WHEN** an executed active addition promotes a `pending_resolution` addition
- **THEN** execution returns the executed outcome, leaves the unresolved addition active, preserves the queue tail, and does not call its handler

#### Scenario: Handler failure stops draining
- **WHEN** a ready active handler returns `failed`
- **THEN** the failed outcome is returned, that intent remains active, and no queued handler executes

### Requirement: Context clears only after agregar_producto queue exhaustion
The execution flow SHALL keep `session.context_type == "product_selection"` while an active or queued addition remains and SHALL clear pending context only after the final definitive addition has been removed.

#### Scenario: Intermediate execution keeps context open
- **WHEN** one addition executes and another unresolved addition is promoted
- **THEN** product-selection context remains active

#### Scenario: Final execution clears context
- **WHEN** the final active addition executes and no queue remains
- **THEN** pending state is empty and `session.context_type is None`

### Requirement: Transaction and exception boundaries remain unchanged
Pending-context execution SHALL NOT commit or roll back, and raised handler exceptions SHALL propagate unchanged without removing active or queued intents.

#### Scenario: Raised exception preserves outer rollback ownership
- **WHEN** an agregar-producto handler raises
- **THEN** execution re-raises the same exception, does not clear pending state, and does not call commit or rollback

### Requirement: Promotion returns the next unresolved agregar_producto interaction
After an active `agregar_producto` reaches definitive `executed` or `rejected`, pending execution SHALL promote the persisted FIFO queue head. If the promoted intent is `pending_resolution`, execution SHALL append that intent exactly once after the definitive outcome, make it the active interaction, and stop.

#### Scenario: Executed active is followed by promoted clarification
- **WHEN** the active Carne addition executes and queued Pizza is `pending_resolution`
- **THEN** results are Carne `executed` then Pizza `pending_resolution`, Pizza is active, and the queue tail is preserved

#### Scenario: Rejected active still promotes clarification
- **WHEN** the active addition is definitively rejected and the queue head is unresolved
- **THEN** results are the rejection then the promoted `pending_resolution`, and the session is not left on the rejected item

### Requirement: Promotion drains ready additions until the next interaction boundary
Pending execution SHALL inspect each promoted persisted intent in FIFO order. It SHALL execute promoted `ready` additions immediately, continue after definitive `executed` or `rejected` outcomes, and stop only when the queue is exhausted, an active intent requires clarification, or a handler returns `failed`.

#### Scenario: Pending ready pending sequence advances deterministically
- **WHEN** resolving pending A promotes ready B followed by pending C
- **THEN** A executes, B executes exactly once, C becomes active, and results are A `executed`, B `executed`, C `pending_resolution`

#### Scenario: Finite ready queue is fully drained
- **WHEN** all promoted additions are ready
- **THEN** each executes exactly once in FIFO order and pending context clears after the finite queue is exhausted

#### Scenario: Failed result stops advancement
- **WHEN** a promoted ready handler returns `failed`
- **THEN** that intent remains active, the remaining queue is unchanged, and no later handler executes

### Requirement: Promoted context type comes from the promoted intent
When a promoted intent remains unresolved, pending execution SHALL determine its context type through the existing context-type resolver and persist that context for the active intent. It SHALL NOT blindly reuse a completed intent's context type.

#### Scenario: Promoted product selection restores product context
- **WHEN** an unresolved queued `agregar_producto` is promoted
- **THEN** `session.context_type` equals `product_selection` as resolved from that promoted intent

### Requirement: Promotion preserves persisted intent data
Promotion SHALL use the queued `ProcessedIntent` value without rerunning the intent classifier or rebuilding it from response text. Quantity, candidate IDs, source text, resolved data, requirements, status, handler, intent name, and refinement state SHALL remain unchanged until the active resolver legitimately refines them.

#### Scenario: Quantity and candidates survive promotion
- **WHEN** a queued Pizza intent stores quantity 2 and a restricted set of candidate IDs
- **THEN** the promoted intent still has quantity 2 and the same candidate IDs before customer refinement

### Requirement: Promotion preserves outer transaction ownership
Pending execution SHALL NOT commit or roll back. A raised handler or lower-layer exception SHALL propagate unchanged so the transactional processor can roll back all order mutations and pending-state advancement from the current incoming message.

#### Scenario: Later promoted execution raises
- **WHEN** an earlier promoted addition mutates the order in memory and a later handler raises
- **THEN** the exception propagates and pending execution performs no commit, rollback, or false-success return

### Requirement: Active completion removes only the authoritative active value

After a ready active `agregar_producto` intent executes or is definitively rejected, pending execution SHALL remove only that completed active item from the authoritative pending state. It SHALL NOT restore a stale pre-resolution active value, discard the queue, or duplicate an active item.

#### Scenario: Executed Carne is removed exactly once

- **WHEN** resolved Carne executes while Pizza is queued
- **THEN** Carne appears in outcomes exactly once, no Carne copy remains active or queued, and Pizza remains available for promotion

#### Scenario: Technical exception preserves rollback ownership

- **WHEN** active or promoted execution raises an exception
- **THEN** the exception propagates, pending execution performs no commit or rollback, and the outer transaction can roll back order and pending-state changes

### Requirement: Next queued ambiguous product is promoted losslessly

After a definitive active outcome, pending execution SHALL promote the persisted FIFO queue head using its stored `ProcessedIntent` fields, derive its context type through the existing context-type resolver, make it active, and return exactly one clarification when it remains `pending_resolution`.

#### Scenario: Pizza promotion preserves persisted data

- **WHEN** Carne executes and queued Pizza stores quantity, candidate IDs, source text, resolved data, requirements, recognizer, and handler
- **THEN** promoted Pizza preserves those values, becomes active with `product_selection` context, and is returned once after the Carne outcome

#### Scenario: Rejected active still promotes Pizza

- **WHEN** the active addition receives a definitive rejected handler result and Pizza is queued
- **THEN** the rejection is returned first, Pizza is promoted and clarified second, and the session is not left on the rejected active item

### Requirement: Queue advancement remains deterministic and exactly once

Pending execution SHALL execute consecutive promoted ready additions in FIFO order and SHALL stop at queue exhaustion, a promoted `pending_resolution` intent, or a `failed` result. Each outcome and handler invocation SHALL occur exactly once.

#### Scenario: Pending ready pending sequence remains ordered

- **WHEN** resolving active A exposes ready B followed by ambiguous C
- **THEN** outcomes are A definitive, B definitive, and C pending in FIFO order, with C active and no duplicate outcomes

#### Scenario: Final promoted selection clears pending state

- **WHEN** the customer resolves the last promoted Pizza candidate and its handler executes
- **THEN** active and queue are empty, context is cleared, and both selected order lines exist exactly once

