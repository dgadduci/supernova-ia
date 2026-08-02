## ADDED Requirements

### Requirement: IntentProcessor function exists
The system SHALL export a single function `process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent` from `backend.intents.processor`. The function SHALL be pure: no I/O, no recognizer call, no handler invocation, no DB write, no persistence.

#### Scenario: Function is importable and returns a ProcessedIntent
- **WHEN** any module calls `process_agregar_producto("add 2 pizzas", {"resolved_data": {"producto_presentacion_id": 42, "cantidad": 2}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []})`
- **THEN** the result is an instance of `ProcessedIntent` whose `intent == "agregar_producto"`, `source_text == "add 2 pizzas"`, `recognizer == "recognizer_productos"`, `handler == "agregar_producto"`, `status == "ready"`, `resolved_data == {"producto_presentacion_id": 42, "cantidad": 2}`, and `candidate_ids == []`

### Requirement: All required requirements completed returns `ready`
When the resolver supplies a value for every required requirement, the processor SHALL mark every `RequirementState` as `completed` and return `status == "ready"`.

#### Scenario: All required values supplied
- **WHEN** the test calls `process_agregar_producto("add 2 pizzas", {"resolved_data": {"producto_presentacion_id": 42, "cantidad": 2}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []})`
- **THEN** `result.status == "ready"`, both `RequirementState` entries have `status == "completed"`, and `result.requirements[0].name == "producto_presentacion_id"` and `result.requirements[1].name == "cantidad"` (in any order)

### Requirement: Missing product-presentation returns `pending_resolution`
When the resolver does not supply a value for a required requirement, the processor SHALL mark the corresponding `RequirementState` as `pending` and return `status == "pending_resolution"`.

#### Scenario: Missing producto_presentacion_id
- **WHEN** the test calls `process_agregar_producto("add 2 pizzas", {"resolved_data": {"cantidad": 2}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []})`
- **THEN** `result.status == "pending_resolution"` and the `RequirementState` for `producto_presentacion_id` has `status == "pending"` and `value is None` (the contract default)

#### Scenario: Missing cantidad
- **WHEN** the test calls `process_agregar_producto("add a pizza", {"resolved_data": {"producto_presentacion_id": 42}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []})`
- **THEN** `result.status == "pending_resolution"` and the `RequirementState` for `cantidad` has `status == "pending"` and `value == 1` (the contract default)

### Requirement: Contract defaults are applied to missing requirements
When a required requirement is missing from `resolved_data`, the processor SHALL set the `RequirementState.value` to the contract's `default` for that requirement.

#### Scenario: cantidad default of 1 is applied
- **WHEN** the test calls `process_agregar_producto("add a pizza", {"resolved_data": {"producto_presentacion_id": 42}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []})`
- **THEN** the `cantidad` `RequirementState` has `value == 1`

#### Scenario: producto_presentacion_id default of None is applied
- **WHEN** the test calls `process_agregar_producto("add 2 pizzas", {"resolved_data": {"cantidad": 2}, "candidate_ids": [], "unavailable_items": [], "not_found_items": []})`
- **THEN** the `producto_presentacion_id` `RequirementState` has `value is None`

### Requirement: Candidate IDs are preserved
The processor SHALL preserve the `candidate_ids` list from the input `normalized_result` verbatim on the returned `ProcessedIntent`.

#### Scenario: Candidate IDs round-trip
- **WHEN** the test calls `process_agregar_producto("add pizza", {"resolved_data": {"producto_presentacion_id": 1, "cantidad": 1}, "candidate_ids": [10, 11, 12], "unavailable_items": [], "not_found_items": []})`
- **THEN** `result.candidate_ids == [10, 11, 12]` in that order

#### Scenario: Empty candidate list
- **WHEN** the test calls the function with `candidate_ids: []`
- **THEN** `result.candidate_ids == []`

### Requirement: Unavailable and not-found items are preserved
The processor SHALL preserve the `unavailable_items` and `not_found_items` lists from the input on the returned `ProcessedIntent`. The active subphase does NOT add them as `RequirementState` entries; the future handler reads them off the envelope directly.

#### Scenario: Unavailable and not-found round-trip
- **WHEN** the test calls the function with `unavailable_items: ["x"]` and `not_found_items: ["y"]`
- **THEN** `result.unavailable_items == ["x"]` and `result.not_found_items == ["y"]`

### Requirement: Source text is preserved
The processor SHALL set the returned `ProcessedIntent.source_text` to the first argument.

#### Scenario: Source text is preserved
- **WHEN** the test calls `process_agregar_producto("add 2 pizzas", {...})`
- **THEN** `result.source_text == "add 2 pizzas"`

### Requirement: Recognizer and handler come from the contract
The processor SHALL set `result.recognizer == "recognizer_productos"` and `result.handler == "agregar_producto"` (the values declared in `AGREGAR_PRODUCTO_CONTRACT`).

#### Scenario: Recognizer and handler identifiers
- **WHEN** the test inspects `result.recognizer` and `result.handler`
- **THEN** they equal `"recognizer_productos"` and `"agregar_producto"` respectively

### Requirement: Returned value passes Pydantic validation
The processor SHALL return a value that, when re-validated by `ProcessedIntent.model_validate(result.model_dump())`, produces an equivalent instance.

#### Scenario: Round-trip is valid
- **WHEN** the test calls `round_tripped = ProcessedIntent.model_validate(result.model_dump())`
- **THEN** the test asserts that `round_tripped.status == result.status`, `round_tripped.intent == result.intent`, `round_tripped.handler == result.handler`, `round_tripped.resolved_data == result.resolved_data`, and `round_tripped.candidate_ids == result.candidate_ids`

### Requirement: Module is importable without side effects
The system SHALL make `process_agregar_producto` importable from `backend.intents.processor` without side effects, errors, or required dependencies beyond the standard library, the existing Pydantic, and the existing Phase 3 modules.

#### Scenario: Import succeeds and the symbol is present
- **WHEN** any module executes `from backend.intents.processor import process_agregar_producto`
- **THEN** the import completes without raising and the binding is a callable

### Requirement: No additional implementation
The subphase SHALL NOT introduce a recognizer call, an HTTP call, a DB write, persistence, a handler invocation, a `pedido_producto` HTTP call, additional processors for other intents, or any other intent-related runtime code. The only new code is the processor function and the verification test.

#### Scenario: Only the processor module is added
- **WHEN** the test lists files under `backend/intents/`
- **THEN** the only new file (relative to the prior subphase state) is `processor.py`

#### Scenario: Only the one public symbol is exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"process_agregar_producto"}`