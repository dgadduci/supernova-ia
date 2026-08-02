## ADDED Requirements

### Requirement: Function exists
The system SHALL export a single function `resolve_product_selection(db, message: str, active_intent: ProcessedIntent) -> ProcessedIntent` from `backend.intents.context.product_selection_context_resolver`. The function SHALL be importable without side effects, errors, or required dependencies beyond SQLAlchemy, the existing Phase 3 modules, and the existing `detectar_productos` from subphase 3.11. The function SHALL NOT modify the `Session` model, SHALL NOT persist, SHALL NOT commit, SHALL NOT call handlers, and SHALL NOT generate responses.

#### Scenario: Function is importable
- **WHEN** any module executes `from backend.intents.context.product_selection_context_resolver import resolve_product_selection`
- **THEN** the import completes without raising and the binding is a callable

#### Scenario: Only one public symbol
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"resolve_product_selection"}`

### Requirement: Input validation
The function SHALL validate the input `active_intent`. If `active_intent.status` is not `"pending_resolution"` OR `active_intent.candidate_ids` is empty, the function SHALL return `active_intent` unchanged (same instance, `is` comparison).

#### Scenario: Returns unchanged when status is not pending_resolution
- **WHEN** the test calls `resolve_product_selection(db, "msg", intent_with_status_ready)`
- **THEN** the result is `intent_with_status_ready` (the same instance, with `is` comparison)

#### Scenario: Returns unchanged when candidate_ids is empty
- **WHEN** the test calls `resolve_product_selection(db, "msg", intent_with_empty_candidates)`
- **THEN** the result is `intent_with_empty_candidates` (the same instance)

### Requirement: Catalog restricted to candidate_ids
The function SHALL query only `producto_presentaciones` rows whose IDs are in `active_intent.candidate_ids`. The query SHALL join the related `productos`, `presentaciones`, and `categorias_productos` rows.

#### Scenario: Query restricted to candidate_ids
- **WHEN** the test calls the function with an `active_intent` whose `candidate_ids == [1, 2, 3]`
- **THEN** the function issues exactly one query against `producto_presentaciones` with a `where(id.in_([1, 2, 3]))` filter; rows with `id` outside this set are not returned

### Requirement: Catalog shape matches the recognizer's existing input contract
The function SHALL build `productos_presentaciones: list[dict]` with the existing 12-field shape that `ProductRecognizer.detectar_productos` reads: `producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `producto_activo`, `presentacion_activo`, `activo` (representing `producto_presentacion.activo`), `disponible` (representing `producto.disponible`).

#### Scenario: Catalog has the 12 fields in the recognizer's input contract
- **WHEN** the test inspects a single built catalog item
- **THEN** the key set is exactly the 12 spec'd fields
- **THEN** `producto_activo` equals `bool(pp.producto.activo)`
- **THEN** `presentacion_activo` equals `bool(pp.presentacion.activo)`
- **THEN** `activo` equals `bool(pp.activo)` (representing `producto_presentacion.activo`)
- **THEN** `disponible` equals `bool(pp.producto.disponible)`

### Requirement: Calls detectar_productos
The function SHALL call `detectar_productos(message, productos_presentaciones)` exactly once and pass the user `message` and the built catalog.

#### Scenario: Calls detectar_productos
- **WHEN** the test mocks `detectar_productos` and calls `resolve_product_selection`
- **THEN** the mock is called exactly once with the user `message` and the built catalog

### Requirement: Unique selection applies
When the recognizer returns exactly one item in `encontrados` AND the selected `producto_presentacion_id` is in the original `candidate_ids`, the function SHALL return a new `ProcessedIntent` with the selection applied.

#### Scenario: Unique selection by presentation
- **WHEN** the test calls the function with a message that uniquely matches one presentation of a candidate
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"]` set to the selected id, the `producto_presentacion_id` requirement is `completed`, `candidate_ids` is `[]`, and the other `resolved_data` fields (including the original `cantidad`) are preserved

#### Scenario: Original quantity is preserved
- **WHEN** the test calls the function with an `active_intent` whose `resolved_data` already contains `{"cantidad": 2}`
- **THEN** the returned intent's `resolved_data` retains `{"cantidad": 2, "producto_presentacion_id": <id>}`

### Requirement: Selection validates the original candidate_ids
The function SHALL reject selections whose `producto_presentacion_id` is not in the original `candidate_ids` (defense-in-depth in case the recognizer or DB returns an unexpected id).

#### Scenario: Selected ID outside original candidates is rejected
- **WHEN** the test mocks `detectar_productos` to return an item whose `producto_presentacion_id` is NOT in `active_intent.candidate_ids`
- **THEN** the function returns `active_intent` unchanged

### Requirement: Fully resolved intent becomes ready
After the selection, when every item in the returned `requirements` list has `status == "completed"`, the returned `ProcessedIntent.status` SHALL be `"ready"`. Otherwise it SHALL be explicitly set to `"pending_resolution"`.

#### Scenario: All required completed → status ready
- **WHEN** the test calls the function with an `active_intent` whose only required requirement is `producto_presentacion_id`
- **THEN** the returned intent's `status == "ready"`

#### Scenario: Another requirement still pending → status pending_resolution
- **WHEN** the test calls the function with an `active_intent` that has another requirement still `pending` and the selection resolves `producto_presentacion_id`
- **THEN** the returned intent's `status` is explicitly `"pending_resolution"`, NOT `"ready"`

### Requirement: Ambiguous or unavailable results leave the intent unchanged
When the recognizer returns 0, 2+, or more items in `encontrados`, OR the selection is in `encontrados_no_disponibles`, OR the original `candidate_ids` is empty, the function SHALL return `active_intent` unchanged.

#### Scenario: Ambiguous recognizer result leaves the intent unchanged
- **WHEN** the test mocks `detectar_productos` to return 2+ items in `encontrados`
- **THEN** the function returns `active_intent` unchanged

#### Scenario: Unavailable recognizer result leaves the intent unchanged
- **WHEN** the test mocks `detectar_productos` to return the only item in `encontrados_no_disponibles`
- **THEN** the function returns `active_intent` unchanged

#### Scenario: Unknown recognizer result leaves the intent unchanged
- **WHEN** the test mocks `detectar_productos` to return empty `encontrados` and a non-empty `no_encontrados`
- **THEN** the function returns `active_intent` unchanged

### Requirement: No side effects
The function SHALL NOT call `commit` on the session, SHALL NOT call `flush` on the session, SHALL NOT call `close` on the session, SHALL NOT modify the `Session` model, and SHALL NOT log anything.

#### Scenario: Function does not commit
- **WHEN** the test calls the function
- **THEN** the session's `commit` is not called (verified by a mock)

#### Scenario: Function does not modify the session model
- **WHEN** the test calls the function with a sample `active_intent`
- **THEN** the `active_intent` instance returned is the same object passed in (no mutation), OR a new instance with the selection applied

### Requirement: Real integration with the existing recognizer
The active subphase MUST include at least one integration test that calls the real `backend.recognizers.product_recognizer.detectar_productos` (not a mock). The integration test builds a restricted catalog using the exact 12-field shape produced by the resolver, calls the real `detectar_productos` (no mock), and verifies the end-to-end resolver-to-recognizer contract.

#### Scenario: Integration test calls real detectar_productos with two presentations
- **WHEN** the test inserts two `ProductoPresentacion` rows for the same product with different presentations ("chica" and "grande"), builds the 12-field catalog via the resolver, and calls the real `detectar_productos` with the message `"la grande"`
- **THEN** the real recognizer returns exactly one original candidate (the "grande" presentation) in `encontrados`; the integration test asserts that the resolver's output is a `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the "grande" presentation's `producto_presentacion_id`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids=[]`, the original `cantidad` in `resolved_data` preserved, and `status="ready"` (since the active_intent's only required requirement is `producto_presentacion_id`)

#### Scenario: Integration test verifies resolver-to-recognizer contract without mocks
- **WHEN** the test inspects the test module that contains the integration scenario
- **THEN** the test does NOT mock `backend.recognizers.product_recognizer.detectar_productos` (a `unittest.mock.patch` on that name is absent); the recognizer's real fuzzy logic and the resolver's real catalog-building code both run end-to-end

### Requirement: Module is importable without side effects
The system SHALL make `resolve_product_selection` importable from `backend.intents.context.product_selection_context_resolver` without side effects, errors, or required dependencies beyond the standard library, SQLAlchemy, the existing Phase 3 modules, and the existing `detectar_productos` from subphase 3.11.

#### Scenario: Import succeeds and the symbol is present
- **WHEN** any module executes `from backend.intents.context.product_selection_context_resolver import resolve_product_selection`
- **THEN** the import completes without raising and the binding is the function

### Requirement: No additional implementation
The subphase SHALL NOT introduce a router, a FastAPI endpoint, a service class, a handler invocation, a recognizer replacement, a model change, a migration, persistence, or any other intent-related runtime code. The only new code is the resolver module and the verification test.

#### Scenario: Only the resolver module is added
- **WHEN** the test lists Python files under `backend/intents/context/`
- **THEN** the file set is exactly `{"__init__.py", "context_type_resolver.py", "pending_context_service.py", "product_selection_context_resolver.py"}`

#### Scenario: Only the one public symbol is exported
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"resolve_product_selection"}`

## Rationale (non-normative)

The active subphase requires a real-integration scenario (not just a unit test that mocks the recognizer) to catch contract drift between the resolver and the recognizer. If a future change renames a field in `detectar_productos`'s input contract, the integration scenario fails immediately because the real recognizer reads a different key. Unit tests with `unittest.mock.patch("detectar_productos", ...)` would mask that drift because they replace the recognizer with a stub that accepts whatever shape the test passes. The integration scenario is the safety net.