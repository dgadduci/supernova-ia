# Capability: pending-context-service

## Purpose

Provide the canonical entry-point service that combines `PendingIntentService`, `ContextTypeResolver`, and the `Session.context_type` column into two operations: start a pending-intent flow by validating, resolving, and persisting both the intent and its context type, and clear both fields when the flow ends. The service is an in-memory mutation; the caller is responsible for committing.

## Requirements

### Requirement: Session model exposes context_type column
The `Session` model SHALL expose a `context_type` column of type `String(50)`, nullable, with no server default. The column stores a `ContextType` string value (e.g. `"product_selection"`) or `NULL` if no context is currently active.

#### Scenario: New sessions have NULL context_type
- **WHEN** the test creates a new `Session` instance and accesses `session.context_type` before any explicit write
- **THEN** the value is `None`

### Requirement: set_pending_intent validates and persists
`set_pending_intent(session, intent)` SHALL validate the intent's status, resolve the context, store the intent as active, and write the context_type. It SHALL raise `ValueError` for either a non-`pending_resolution` status or a non-resolvable context.

#### Scenario: Saving a valid pending product-selection intent
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "pending_resolution"`, a pending `producto_presentacion_id` requirement, and non-empty `candidate_ids`
- **THEN** the result is a `PendingIntents` with `active` set to the intent, `session.context_type == "product_selection"`, and `session.pending_intents` round-trips to the same state

#### Scenario: Rejecting a non-pending intent
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "ready"`
- **THEN** the call raises `ValueError` and neither `session.context_type` nor `session.pending_intents` is mutated

#### Scenario: Rejecting a non-pending intent with status executed
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "executed"`
- **THEN** the call raises `ValueError` and neither `session.context_type` nor `session.pending_intents` is mutated

#### Scenario: Rejecting a non-pending intent with status rejected
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "rejected"`
- **THEN** the call raises `ValueError`

#### Scenario: Rejecting a non-pending intent with status failed
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "failed"`
- **THEN** the call raises `ValueError`

#### Scenario: Rejecting a pending intent without resolvable context
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "pending_resolution"` but the `producto_presentacion_id` requirement is `completed` (or missing)
- **THEN** the call raises `ValueError` and neither `session.context_type` nor `session.pending_intents` is mutated

#### Scenario: Rejecting a pending intent with empty candidate_ids
- **WHEN** the test calls `set_pending_intent(session, intent)` with `intent.status == "pending_resolution"`, the `producto_presentacion_id` requirement is `pending`, and `candidate_ids` is `[]`
- **THEN** the call raises `ValueError`

### Requirement: set_pending_intent returns the new PendingIntents
`set_pending_intent` SHALL return the `PendingIntents` state that was just stored on the session.

#### Scenario: Returned value matches session state
- **WHEN** the test calls `set_pending_intent(session, intent)` with a valid pending product-selection intent
- **THEN** the return value is a `PendingIntents` whose `active` is the intent, and `PendingIntentService.load(session)` returns an equivalent state

### Requirement: clear_pending_context resets both fields
`clear_pending_context(session)` SHALL call `clear(session)` to reset `pending_intents` to the default and SHALL set `session.context_type = None`.

#### Scenario: Clearing with both fields populated
- **WHEN** the test first calls `set_pending_intent(session, valid_intent)` and then `clear_pending_context(session)`
- **THEN** `session.context_type is None` and `session.pending_intents` represents a default `PendingIntents`

#### Scenario: Clearing with only context_type set
- **WHEN** the test sets `session.context_type = "product_selection"` directly and then calls `clear_pending_context(session)`
- **THEN** `session.context_type is None` and `session.pending_intents` is a default `PendingIntents` JSON

#### Scenario: Clearing with only pending_intents set
- **WHEN** the test calls `set_active(session, intent)` directly and then `clear_pending_context(session)`
- **THEN** `session.context_type is None` and `session.pending_intents` is a default `PendingIntents` JSON

#### Scenario: Clearing on a fresh session
- **WHEN** the test calls `clear_pending_context(session)` on a session with `context_type = None` and `pending_intents = "{}"`
- **THEN** the call returns `None` and the session state is unchanged (still `context_type = None`, default `pending_intents`)

### Requirement: Module is importable without side effects
The system SHALL make `set_pending_intent` and `clear_pending_context` importable from `backend.intents.context.pending_context_service` without side effects, errors, or required dependencies beyond the standard library, Pydantic, and the existing Phase 3 modules.

#### Scenario: Import succeeds and both symbols are present
- **WHEN** any module executes `from backend.intents.context.pending_context_service import set_pending_intent, clear_pending_context`
- **THEN** the import completes without raising and both bindings are callables

### Requirement: No additional implementation
The subphase SHALL NOT introduce a router, a FastAPI endpoint, a commit, a transaction manager, a recognizer call, a handler invocation, or any other intent-related runtime code. The only new code is the `Session` model column, the Alembic migration, the service module, and the verification test.

#### Scenario: Only the service file is added
- **WHEN** the test lists non-`__init__.py` files under `backend/intents/context/`
- **THEN** the file set is exactly `{"context_type_resolver.py", "pending_context_service.py"}`

#### Scenario: Only the two public symbols are exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"set_pending_intent", "clear_pending_context"}`
