# Capability: pending-intent-service

## Purpose

Persist and mutate the pending-intent state associated with a session through a focused service that loads, updates, queues, promotes, and clears `PendingIntents` values.

## Requirements

### Requirement: Session model exposes pending_intents column
The `Session` model SHALL expose a `pending_intents` column of type `Text`, nullable, with server default `"{}"`. The column stores a JSON-serialized `PendingIntents` value.

#### Scenario: New sessions have an empty JSON default
- **WHEN** the test creates a new `Session` instance and accesses `session.pending_intents` before any explicit write
- **THEN** the value is `"{}"` (or `None` for a pre-migration row, which the service treats as empty)

### Requirement: load returns the current PendingIntents
`load(session)` SHALL read `session.pending_intents`, treat `None` as `"{}"`, validate via `PendingIntents.model_validate(...)`, and return the typed instance.

#### Scenario: Loading an empty session returns a default PendingIntents
- **WHEN** the test calls `load(session)` on a session with `pending_intents == "{}"`
- **THEN** the result is a `PendingIntents` with `version == 1`, `active is None`, and `queue == []`

#### Scenario: Loading a None pending_intents returns a default
- **WHEN** the test calls `load(session)` on a session with `pending_intents is None` (pre-migration row)
- **THEN** the result is a default `PendingIntents`

#### Scenario: Loading a non-empty session returns the persisted state
- **WHEN** the test calls `load(session)` on a session with a previously-serialized `PendingIntents` JSON
- **THEN** the result is a `PendingIntents` with the same `version`, `active`, and `queue` as the original

### Requirement: set_active writes the new state
`set_active(session, intent)` SHALL set the `active` field to `intent`, leave the queue unchanged, serialize with `PendingIntents.model_dump(mode="json")`, write the JSON to `session.pending_intents`, and return the new `PendingIntents`.

#### Scenario: Setting the active intent persists
- **WHEN** the test calls `set_active(session, intent)` and then `load(session)`
- **THEN** the loaded `active` is the same `intent` and the loaded `queue == []` (or the prior queue if any)

#### Scenario: set_active returns the new state
- **WHEN** the test calls `set_active(session, intent)`
- **THEN** the return value is a `PendingIntents` whose `active is intent` and whose serialized form equals `session.pending_intents`

### Requirement: enqueue appends to the queue
`enqueue(session, intent)` SHALL append `intent` to `queue`, leave `active` unchanged, serialize, write, and return the new `PendingIntents`.

#### Scenario: Enqueueing adds to the queue
- **WHEN** the test calls `enqueue(session, intent_a)` then `enqueue(session, intent_b)`
- **THEN** the loaded `queue` is `[intent_a, intent_b]` and `active is None`

#### Scenario: Enqueue returns the new state
- **WHEN** the test calls `enqueue(session, intent)`
- **THEN** the return value is a `PendingIntents` whose `queue[-1] is intent` and whose serialized form equals `session.pending_intents`

### Requirement: remove_active promotes the queue head
`remove_active(session)` SHALL set `active = queue[0]` if `queue` is non-empty (and pop `queue[0]` off), or `active = None` if `queue` is empty, serialize, write, and return the new `PendingIntents`.

#### Scenario: Promoting the queue after removing the active intent
- **WHEN** the test sets `active = intent_a`, enqueues `[intent_b, intent_c]`, then calls `remove_active(session)`
- **THEN** the loaded `active is intent_b` and the loaded `queue == [intent_c]`

#### Scenario: Removing the active intent with an empty queue
- **WHEN** the test sets `active = intent_a` with an empty queue, then calls `remove_active(session)`
- **THEN** the loaded `active is None` and the loaded `queue == []`

#### Scenario: remove_active returns the new state
- **WHEN** the test calls `remove_active(session)` after the setup above
- **THEN** the return value is the new `PendingIntents` whose serialized form equals `session.pending_intents`

### Requirement: clear resets to the default
`clear(session)` SHALL reset the state to a default `PendingIntents()` (no `active`, empty `queue`), serialize, write, and return `None`.

#### Scenario: Clearing removes the active and empties the queue
- **WHEN** the test sets `active = intent_a` and `queue = [intent_b, intent_c]`, then calls `clear(session)`
- **THEN** the loaded `active is None` and the loaded `queue == []` and the return value is `None`

#### Scenario: clear persists the empty state
- **WHEN** the test calls `clear(session)` and then `load(session)`
- **THEN** the loaded state is a default `PendingIntents`

### Requirement: Every mutation serializes with model_dump(mode="json")
The service SHALL use `PendingIntents.model_dump(mode="json")` to serialize every mutation, and the resulting value SHALL be valid JSON that round-trips through `PendingIntents.model_validate(...)`.

#### Scenario: All mutations produce JSON-serializable strings
- **WHEN** the test inspects `session.pending_intents` after any of `set_active`, `enqueue`, `remove_active`, or `clear`
- **THEN** the value is a `str` and `import json; json.loads(session.pending_intents)` succeeds and `PendingIntents.model_validate(json.loads(session.pending_intents))` returns a `PendingIntents` equivalent to the in-memory state

### Requirement: Module is importable without side effects
The system SHALL make `load`, `set_active`, `enqueue`, `remove_active`, and `clear` importable from `backend.intents.services.pending_intent_service` without side effects, errors, or required dependencies beyond the standard library, the existing Pydantic, and the existing Phase 3 modules.

#### Scenario: Import succeeds and the five symbols are present
- **WHEN** any module executes `from backend.intents.services.pending_intent_service import load, set_active, enqueue, remove_active, clear`
- **THEN** the import completes without raising and all five bindings are callables

### Requirement: No additional implementation
The subphase SHALL NOT introduce a router, a FastAPI endpoint, a commit, a transaction manager, a handler invocation, a recognizer call, a `pedido_producto` HTTP call, or any other intent-related runtime code. The only new code is the `Session` model column, the Alembic migration, the service module, and the verification test.

#### Scenario: Only the service file is added
- **WHEN** the test lists Python files under `backend/intents/services/`
- **THEN** the file set is exactly `{"__init__.py", "pending_intent_service.py"}`

#### Scenario: Only the five public symbols are exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"load", "set_active", "enqueue", "remove_active", "clear"}`

### Requirement: Definitive active completion preserves and promotes queued work
The pending-intent lifecycle SHALL remove only the definitive active intent and SHALL promote the FIFO queue head through `remove_active`. It SHALL clear the complete pending state only when no active or queued item remains.

#### Scenario: Executed active promotes queue head
- **WHEN** an active addition reaches `executed` while two additions remain queued
- **THEN** the former queue head becomes active and only the remaining tail stays queued

#### Scenario: Rejected active promotes queue head
- **WHEN** an active addition reaches definitive `rejected` while another addition is queued
- **THEN** the rejected active is removed and the queued addition becomes active

#### Scenario: Last definitive item empties pending state
- **WHEN** the active addition reaches a definitive result and the queue is empty
- **THEN** pending state becomes the default with no active item and an empty queue

### Requirement: Non-definitive outcomes preserve the complete queue
A `pending_resolution` or `failed` active result SHALL remain active and SHALL NOT remove, reorder, or clear queued additions.

#### Scenario: Failed active retains later additions
- **WHEN** active execution returns `failed` with two queued additions
- **THEN** the failed active and both queued additions remain persisted in their original order
