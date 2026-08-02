## ADDED Requirements

### Requirement: RequirementStatus is a closed string Literal
The system SHALL export a single Python type alias `RequirementStatus` from `backend.intents.schemas.requirement_state`. The alias SHALL be `typing.Literal["pending", "completed"]`.

#### Scenario: Type alias exists and is the Literal form
- **WHEN** the test inspects the exported `RequirementStatus`
- **THEN** the value is a `Literal` alias accepting exactly the two strings `"pending"` and `"completed"` and rejecting every other string

### Requirement: RequirementState schema
The system SHALL export a Pydantic `BaseModel` subclass named `RequirementState` from `backend.intents.schemas.requirement_state`. The model SHALL declare exactly three fields in this order: `name: str`, `status: RequirementStatus`, and `value: Any | None = None`.

#### Scenario: Valid creation with explicit fields
- **WHEN** the test instantiates `RequirementState` with `name="cantidad"`, `status="pending"`, and `value=2`
- **THEN** the resulting instance exposes `name == "cantidad"`, `status == "pending"`, and `value == 2`

#### Scenario: Default value is None
- **WHEN** the test instantiates `RequirementState` with only `name` and `status`
- **THEN** the resulting instance exposes `value is None`

#### Scenario: Default value is None for both statuses
- **WHEN** the test instantiates `RequirementState` with `status="pending"` and `status="completed"` (separately) and no `value`
- **THEN** both instances expose `value is None`

#### Scenario: Invalid status is rejected
- **WHEN** the test instantiates `RequirementState` with a `status` value that is neither `"pending"` nor `"completed"`
- **THEN** the constructor raises `pydantic.ValidationError`

#### Scenario: Missing name is rejected
- **WHEN** the test instantiates `RequirementState` without a `name` field
- **THEN** the constructor raises `pydantic.ValidationError`

#### Scenario: name must be a string
- **WHEN** the test instantiates `RequirementState` with a non-string `name` (e.g. `123`)
- **THEN** the constructor raises `pydantic.ValidationError`

### Requirement: Module is importable without side effects
The system SHALL make `RequirementState` and `RequirementStatus` importable from `backend.intents.schemas.requirement_state` without side effects, errors, or required dependencies beyond the standard library and the already-installed Pydantic.

#### Scenario: Import succeeds and the two symbols are present
- **WHEN** any module executes `from backend.intents.schemas.requirement_state import RequirementState, RequirementStatus`
- **THEN** the import completes without raising and both bindings are available

### Requirement: No additional implementation
The subphase SHALL NOT introduce business logic, methods beyond the Pydantic default, validators beyond type checks, other schemas, a registry, a recognizer, a handler, a processor, a DB model, a migration, or a FastAPI endpoint. The only new code is the schema file, the empty `__init__.py`, and the verification test.

#### Scenario: Only the schema module is added
- **WHEN** the test lists Python files under `backend/intents/schemas/`
- **THEN** the only file present is `requirement_state.py` (alongside `__init__.py`)

#### Scenario: Only the two public symbols are exported
- **WHEN** the test introspects the module
- **THEN** the only public symbols are `RequirementState` and `RequirementStatus`