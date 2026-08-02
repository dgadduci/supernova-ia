# Capability: pending-intents-schema

## Purpose

Define a Pydantic schema that represents the conversation-wide state of one or more processed intents in flight at a single moment — exposing only the schema itself (no registry, recognizer, handler, or model) so future subphases can introspect the typed shape of the pending-intents state, serialize it to JSON for persistence, and resume after an interruption without importing implementation code.

## Requirements

### Requirement: PendingIntents conversation state
The system SHALL export a Pydantic `BaseModel` subclass named `PendingIntents` from `backend.intents.schemas.pending_intents`. The model SHALL declare exactly three fields in this order, with the type annotations and default factories shown.

| Field      | Type                    | Default                |
|------------|-------------------------|------------------------|
| `version`  | `int`                   | `1`                    |
| `active`   | `ProcessedIntent \| None` | `None`                 |
| `queue`    | `list[ProcessedIntent]` | `default_factory=list` |

The `version` field is reserved for forward compatibility — a future subphase may add migration logic. The current subphase does NOT enforce any version check.

#### Scenario: Default creation
- **WHEN** the test instantiates `PendingIntents` with no arguments
- **THEN** the resulting instance exposes `version == 1`, `active is None`, and `queue == []`

#### Scenario: Default queue is not shared across instances
- **WHEN** the test creates two `PendingIntents` instances and appends to one instance's `queue`
- **THEN** the other instance's `queue` is still `[]`

#### Scenario: Creation with an active intent
- **WHEN** the test instantiates `PendingIntents` with a single `ProcessedIntent` passed as `active`
- **THEN** the resulting instance exposes `active.intent == <that intent>` and `queue == []`

#### Scenario: Creation with queued intents
- **WHEN** the test instantiates `PendingIntents` with a list of two `ProcessedIntent` instances passed as `queue`
- **THEN** the resulting instance exposes `queue[0].intent == <first intent>` and `queue[1].intent == <second intent>`, and `active is None`

#### Scenario: Creation with both active and queued intents
- **WHEN** the test instantiates `PendingIntents` with both an `active` and a non-empty `queue`
- **THEN** both fields are populated independently and `version == 1`

### Requirement: Nested ProcessedIntent is validated
The model SHALL validate the nested `ProcessedIntent` instances: an invalid `status` on any nested intent must surface as a `pydantic.ValidationError` on the parent `PendingIntents` constructor.

#### Scenario: Invalid active status is rejected
- **WHEN** the test instantiates `PendingIntents` with an `active` whose `status` is not one of the five `IntentStatus` strings
- **THEN** the constructor raises `pydantic.ValidationError`

#### Scenario: Invalid queued status is rejected
- **WHEN** the test instantiates `PendingIntents` with a `queue` containing a `ProcessedIntent` whose `status` is not one of the five `IntentStatus` strings
- **THEN** the constructor raises `pydantic.ValidationError`

#### Scenario: Missing required field on active is rejected
- **WHEN** the test instantiates `PendingIntents` with an `active` missing a required field (e.g. `intent`)
- **THEN** the constructor raises `pydantic.ValidationError`

### Requirement: JSON serialization round-trip
The schema SHALL be JSON-round-trippable: serializing a `PendingIntents` instance via `model_dump(mode="json")` and re-parsing the result via `model_validate(...)` SHALL produce an equivalent instance.

#### Scenario: Round-trip preserves all fields
- **WHEN** the test creates a `PendingIntents` with an `active` and a non-empty `queue`, then `dumps = original.model_dump(mode="json")` and `restored = PendingIntents.model_validate(dumps)`
- **THEN** the test asserts that `restored.version == original.version`, `restored.active.intent == original.active.intent`, `restored.active.status == original.active.status`, and `len(restored.queue) == len(original.queue)` with the same intent names in the same order

#### Scenario: Round-trip of default instance
- **WHEN** the test creates a default `PendingIntents()` and round-trips it
- **THEN** the test asserts the restored instance has `version == 1`, `active is None`, and `queue == []`

#### Scenario: Round-trip output is JSON-serializable to plain dict
- **WHEN** the test calls `instance.model_dump(mode="json")`
- **THEN** the result is a plain `dict` whose values are JSON-serializable (no `Decimal`, `datetime`, `UUID`, or other non-JSON-native types in the output)

### Requirement: Module is importable without side effects
The system SHALL make `PendingIntents` importable from `backend.intents.schemas.pending_intents` without side effects, errors, or required dependencies beyond the standard library and the already-installed Pydantic.

#### Scenario: Import succeeds and the symbol is present
- **WHEN** any module executes `from backend.intents.schemas.pending_intents import PendingIntents`
- **THEN** the import completes without raising and the binding is the model class

### Requirement: No additional implementation
The subphase SHALL NOT introduce business logic, methods, validators beyond type checks, other schemas, a registry, a recognizer, a handler, a processor, a DB model, a migration, a FastAPI endpoint, or persistence of the state to a `Session` row. The only new code is the schema file and the verification test.

#### Scenario: Only the schema file is added
- **WHEN** the test lists non-`__init__.py` files under `backend/intents/schemas/`
- **THEN** the file set is exactly `{"requirement_state.py", "processed_intent.py", "pending_intents.py"}`

#### Scenario: Only the one public symbol is exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"PendingIntents"}`