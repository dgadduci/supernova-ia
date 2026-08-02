# Product Selection Context Resolver

## Purpose

Resolve a uniquely recognized product presentation against an active intent's candidate catalog using a prebuilt, restricted catalog supplied by the caller, keeping the resolver a pure decision function independent of database and service layers.

## Requirements

### Requirement: Function exists
The system SHALL export `resolve_product_selection(message: str, active_intent: ProcessedIntent, productos_presentaciones: list[dict]) -> ProcessedIntent` from `backend.intents.context.product_selection_context_resolver`. The function SHALL be importable without SQLAlchemy, database session, repository, or service dependencies and SHALL remain pure: no persistence, commits, handlers, responses, or session mutation.

#### Scenario: Function is importable
- **WHEN** any module executes `from backend.intents.context.product_selection_context_resolver import resolve_product_selection`
- **THEN** the import completes without raising and the binding is a callable

#### Scenario: Only one public symbol
- **WHEN** the test introspects the module's `__all__`
- **THEN** the public symbol set is exactly `{"resolve_product_selection"}`

#### Scenario: Pure resolver is importable
- **WHEN** a module imports `resolve_product_selection`
- **THEN** the import succeeds without requiring a database session or SQLAlchemy query setup

#### Scenario: Pure resolver accepts a prebuilt catalog
- **WHEN** the resolver receives a restricted 12-field catalog and a pending intent
- **THEN** it invokes the existing recognizer and returns the selection result without database access

### Requirement: Input validation
The function SHALL validate the input `active_intent`. If `active_intent.status` is not `"pending_resolution"` OR `active_intent.candidate_ids` is empty, the function SHALL return `active_intent` unchanged (same instance, `is` comparison). The function SHALL also return `active_intent` unchanged when the supplied catalog cannot produce a unique valid selection.

#### Scenario: Returns unchanged when status is not pending_resolution
- **WHEN** the test calls `resolve_product_selection("msg", intent_with_status_ready, catalog)`
- **THEN** the result is `intent_with_status_ready` (the same instance, with `is` comparison)

#### Scenario: Returns unchanged when candidate_ids is empty
- **WHEN** the test calls `resolve_product_selection("msg", intent_with_empty_candidates, catalog)`
- **THEN** the result is `intent_with_empty_candidates` (the same instance)

#### Scenario: Invalid pending context is unchanged
- **WHEN** the resolver receives a ready intent or an intent with no candidates
- **THEN** it returns the same intent instance without invoking the recognizer

### Requirement: Calls detectar_productos
The function SHALL call `detectar_productos(message, productos_presentaciones)` exactly once using the user `message` and the supplied catalog.

#### Scenario: Calls detectar_productos
- **WHEN** the test mocks `detectar_productos` and calls `resolve_product_selection("msg", intent, catalog)`
- **THEN** the mock is called exactly once with the user `message` and the supplied catalog

### Requirement: Unique selection applies
When the recognizer returns exactly one item in `encontrados` AND its `producto_presentacion_id` is in the original `candidate_ids`, the resolver SHALL return a new `ProcessedIntent` with the selected presentation applied, the original resolved data preserved, the selection requirement completed, and `candidate_ids` cleared.

#### Scenario: Unique selection by presentation
- **WHEN** the test calls the function with a message that uniquely matches one presentation of a candidate
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"]` set to the selected id, the `producto_presentacion_id` requirement is `completed`, `candidate_ids` is `[]`, and the other `resolved_data` fields (including the original `cantidad`) are preserved

#### Scenario: Original quantity is preserved
- **WHEN** the test calls the function with an `active_intent` whose `resolved_data` already contains `{"cantidad": 2}`
- **THEN** the returned intent's `resolved_data` retains `{"cantidad": 2, "producto_presentacion_id": <id>}`

#### Scenario: Unique selection from prebuilt catalog
- **WHEN** the resolver receives a catalog restricted to the active intent candidates and the real recognizer uniquely matches `la grande`
- **THEN** the result contains the selected `producto_presentacion_id`, preserves `cantidad`, marks the selection requirement completed, and clears candidates

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

### Requirement: No database access in context resolver
The context resolver SHALL contain no SQLAlchemy imports, database session parameter, repository calls, service calls, commits, persistence, or model loading. Database access SHALL be performed outside the resolver.

#### Scenario: Resolver source has no database dependency
- **WHEN** the resolver module is inspected
- **THEN** it contains no SQLAlchemy or database-session access

### Requirement: No side effects
The function SHALL NOT call `commit` on any session, SHALL NOT call `flush` on any session, SHALL NOT call `close` on any session, SHALL NOT mutate session state, SHALL NOT persist pending context, and SHALL NOT log anything.

#### Scenario: Function does not commit
- **WHEN** the test calls the function
- **THEN** no session's `commit` is called (verified by a mock)

### Requirement: Real integration with the existing recognizer
The active subphase MUST include at least one integration test that calls the real `backend.recognizers.product_recognizer.detectar_productos` (not a mock), supplies the exact 12-field restricted catalog, and verifies the resolver-to-recognizer contract end to end.

#### Scenario: Resolver-to-recognizer contract
- **WHEN** the integration test resolves a uniquely matched presentation using the real recognizer
- **THEN** the returned intent contains the selected candidate and preserves the original resolved data

### Requirement: Module is importable without side effects
The system SHALL make `resolve_product_selection` importable from `backend.intents.context.product_selection_context_resolver` without side effects, errors, or required dependencies beyond the standard library, the existing Phase 3 modules, and the existing `detectar_productos` from subphase 3.11.

#### Scenario: Import succeeds
- **WHEN** a module imports `resolve_product_selection`
- **THEN** the import succeeds and the binding is callable

### Requirement: Candidate catalog repository access
The product repository SHALL provide a query operation that loads only `producto_presentaciones` whose IDs are supplied by the caller and eagerly loads product, presentation, and category relationships.

#### Scenario: Repository restricts candidate IDs
- **WHEN** the repository is asked to load candidate IDs `[1, 2, 3]`
- **THEN** its query filters by those IDs and does not return other presentations

### Requirement: Product service builds recognizer catalog
The product service SHALL load the restricted candidate presentations through the repository and build the exact 12-field catalog consumed by `detectar_productos`, preserving real activation and availability values.

#### Scenario: Service returns exact catalog shape
- **WHEN** the service loads candidate presentations
- **THEN** each catalog item contains exactly the recognizer fields and values for identifiers, product, category, presentation, activation, and availability

### Requirement: Product selection orchestration
An orchestration service SHALL receive the database session, load the restricted catalog through the product service, and invoke the pure context resolver with the message, active intent, and catalog. It SHALL not commit, persist pending context, execute handlers, or generate responses.

#### Scenario: Orchestration resolves a presentation
- **WHEN** the orchestration service receives an active intent with candidate IDs and the message `la grande`
- **THEN** it loads only those candidates, invokes the real resolver/recognizer path, and returns the resolved intent with original quantity preserved

#### Scenario: Orchestration has no side effects
- **WHEN** the orchestration service completes resolution
- **THEN** it has not committed, modified session state, invoked a handler, or generated a response
