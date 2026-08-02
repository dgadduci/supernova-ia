## ADDED Requirements

### Requirement: IntentStatus is a five-state Literal
The system SHALL export a single Python type alias `IntentStatus` from `backend.intents.schemas.processed_intent`. The alias SHALL be `typing.Literal["pending_resolution", "ready", "executed", "rejected", "failed"]`.

#### Scenario: Type alias accepts the five values and rejects everything else
- **WHEN** the test inspects the exported `IntentStatus`
- **THEN** the value is a `Literal` alias accepting exactly the five strings and rejecting every other string

### Requirement: ProcessedIntent envelope
The system SHALL export a Pydantic `BaseModel` subclass named `ProcessedIntent` from `backend.intents.schemas.processed_intent`. The model SHALL declare exactly eight fields in this order, with the type annotations and default factories shown.

| Field            | Type                          | Default                |
|------------------|-------------------------------|------------------------|
| `intent`         | `str`                         | required               |
| `source_text`    | `str`                         | required               |
| `status`         | `IntentStatus`                | required               |
| `recognizer`     | `str \| None`                 | `None`                 |
| `handler`        | `str`                         | required               |
| `resolved_data`  | `dict[str, Any]`              | `default_factory=dict` |
| `requirements`   | `list[RequirementState]`     | `default_factory=list` |
| `candidate_ids`  | `list[int]`                   | `default_factory=list` |

#### Scenario: Valid creation with all fields
- **WHEN** the test instantiates `ProcessedIntent` with every field supplied
- **THEN** the resulting instance exposes the values as supplied, the `requirements` list contains the supplied `RequirementState` objects, and `candidate_ids` is the supplied list of ints

#### Scenario: Default empty collections
- **WHEN** the test instantiates `ProcessedIntent` with only the four required fields (`intent`, `source_text`, `status`, `handler`) and a `recognizer` value
- **THEN** the resulting instance exposes `resolved_data == {}`, `requirements == []`, and `candidate_ids == []`

#### Scenario: Default recognizer is None
- **WHEN** the test instantiates `ProcessedIntent` without a `recognizer`
- **THEN** the resulting instance exposes `recognizer is None`

#### Scenario: Default collections are not shared across instances
- **WHEN** the test creates two `ProcessedIntent` instances with the same required fields
- **THEN** mutating `instance_a.resolved_data["x"] = 1` does NOT cause `instance_b.resolved_data` to contain `"x"`

#### Scenario: Nested RequirementState is validated
- **WHEN** the test instantiates `ProcessedIntent` with a `requirements` list containing a `RequirementState` with an invalid `status`
- **THEN** the constructor raises `pydantic.ValidationError`

#### Scenario: Nested RequirementState accepts a valid one
- **WHEN** the test instantiates `ProcessedIntent` with a `requirements` list containing a valid `RequirementState(name="cantidad", status="ready", value=3)`
- **THEN** the constructor succeeds and `result.requirements[0].value == 3`

#### Scenario: Invalid status is rejected
- **WHEN** the test instantiates `ProcessedIntent` with a `status` value that is not one of the five `IntentStatus` strings
- **THEN** the constructor raises `pydantic.ValidationError`

#### Scenario: Missing required field is rejected
- **WHEN** the test instantiates `ProcessedIntent` without one of the four required fields (`intent`, `source_text`, `status`, `handler`)
- **THEN** the constructor raises `pydantic.ValidationError`

### Requirement: Module is importable without side effects
The system SHALL make `ProcessedIntent` and `IntentStatus` importable from `backend.intents.schemas.processed_intent` without side effects, errors, or required dependencies beyond the standard library and the already-installed Pydantic.

#### Scenario: Import succeeds and the two symbols are present
- **WHEN** any module executes `from backend.intents.schemas.processed_intent import ProcessedIntent, IntentStatus`
- **THEN** the import completes without raising and both bindings are available

### Requirement: No additional implementation
The subphase SHALL NOT introduce business logic, methods, validators beyond type checks, other schemas, a registry, a recognizer, a handler, a processor, a DB model, a migration, or a FastAPI endpoint. The only new code is the schema file and the verification test.

#### Scenario: Only the schema file is added
- **WHEN** the test lists non-`__init__.py` files under `backend/intents/schemas/`
- **THEN** the file set is exactly `{"requirement_state.py", "processed_intent.py"}`

#### Scenario: Only the two public symbols are exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"IntentStatus", "ProcessedIntent"}`