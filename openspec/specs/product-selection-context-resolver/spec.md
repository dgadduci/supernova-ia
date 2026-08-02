# Capability: product-selection-context-resolver

## Purpose

Define a single pure-with-respect-to-its-own-state function that resolves a pending `PRODUCT_SELECTION` `ProcessedIntent` by calling the existing `ProductRecognizer` (`detectar_productos`) with a catalog restricted to the intent's `candidate_ids`, and returns a new `ProcessedIntent` with the chosen `producto_presentacion_id` applied (when the recognizer picks a unique match within the original candidates) — exposing only the resolver function itself (no handler invocation, no `PendingIntentService` call, no session mutation, no `commit`, no `flush`, no `close`, no persistence, no schema change, no router, no endpoint) so the future dispatch path can apply a user's disambiguating reply without triggering any side effects in the resolver.
## Requirements
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

### Requirement: Catalog shape matches recognizer's existing input contract
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
When all required requirements are `completed` after the selection, the returned `ProcessedIntent.status` SHALL be `"ready"`. Otherwise the status SHALL be the input's `status` (typically `"pending_resolution"`).

#### Scenario: All required completed → status ready
- **WHEN** the test calls the function with an `active_intent` whose only required requirement is `producto_presentacion_id`
- **THEN** the returned intent's `status == "ready"`

#### Scenario: Another required still pending → status kept
- **WHEN** the test calls the function with an `active_intent` that has `cantidad` still `pending` and the selection resolves `producto_presentacion_id`
- **THEN** the returned intent's `status` is the input's `status` (e.g. `"pending_resolution"`), NOT `"ready"`

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

### Requirement: Real integration with the existing recognizer
The active subphase MUST include at least one integration test that calls the real `backend.recognizers.product_recognizer.detectar_productos` (not a mock). The integration test builds a restricted catalog using the exact 12-field shape produced by the resolver, calls the real `detectar_productos` (no mock), and verifies the end-to-end resolver-to-recognizer contract.

#### Scenario: Integration test calls real detectar_productos with two presentations
- **WHEN** the test inserts two `ProductoPresentacion` rows for the same product with different presentations ("chica" and "grande"), builds the 12-field catalog via the resolver, and calls the real `detectar_productos` with the message `"la grande"`
- **THEN** the real recognizer returns exactly one original candidate (the "grande" presentation) in `encontrados`; the integration test asserts that the resolver's output is a `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the "grande" presentation's `producto_presentacion_id`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids=[]`, the original `cantidad` in `resolved_data` preserved, and `status="ready"` (since the active_intent's only required requirement is `producto_presentacion_id`)

#### Scenario: Integration test verifies resolver-to-recognizer contract without mocks
- **WHEN** the test inspects the test module that contains the integration scenario
- **THEN** the test does NOT mock `backend.recognizers.product_recognizer.detectar_productos` (a `unittest.mock.patch` on that name is absent); the recognizer's real fuzzy logic and the resolver's real catalog-building code both run end-to-end

### Requirement: Resolver narrows candidate_ids on partial recognition

When `detectar_productos` returns zero items in `encontrados` AND at least one group in `encontrados_posibles` AND every `producto_presentacion_id` referenced by those groups is already in `active_intent.candidate_ids`, the function SHALL return a new `ProcessedIntent` whose `candidate_ids` is the intersection of the original `candidate_ids` and the set of `producto_presentacion_id`s from the recognizer output, preserving the original order. The narrowed intent SHALL keep `status == "pending_resolution"` when the intersection has more than one element. The narrowed intent SHALL preserve `resolved_data`, `requirements`, `intent`, `source_text`, `recognizer`, and `handler` verbatim from the input.

#### Scenario: Partial narrowing leaves multiple candidates

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaChica, PizzaMuzzarellaGrande, PizzaNapolitanaChica, PizzaNapolitanaGrande, PizzaMargheritaGrande]` and the message is `la grande` and the recognizer returns three `producto_presentacion_id`s in `encontrados_posibles` (`PizzaMuzzarellaGrande`, `PizzaNapolitanaGrande`, `PizzaMargheritaGrande`)
- **THEN** the returned intent has `candidate_ids == [PizzaMuzzarellaGrande, PizzaNapolitanaGrande, PizzaMargheritaGrande]` (in that order), `status == "pending_resolution"`, and the original `resolved_data`, `requirements`, `intent`, `source_text`, `recognizer`, and `handler` preserved

#### Scenario: Partial narrowing leaves one candidate and resolves to ready

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaGrande, PizzaNapolitanaGrande, PizzaMargheritaGrande]` and the message is `Pizza de Muzzarella Grande` and the recognizer returns exactly one `producto_presentacion_id` (`PizzaMuzzarellaGrande`) in `encontrados`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == PizzaMuzzarellaGrande`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, `status == "ready"`, and the original `cantidad` preserved in `resolved_data`

#### Scenario: Empty intersection returns the input unchanged

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaChica, PizzaNapolitanaChica]` and the message is `la grande` and the recognizer returns three `producto_presentacion_id`s in `encontrados_posibles` that are NOT in `active_intent.candidate_ids`
- **THEN** the function returns `active_intent` unchanged (same instance) — the narrowing does not collapse the candidate set to empty

### Requirement: Unique selection is reused when refinement leaves exactly one candidate

When the recognizer returns exactly one item in `encontrados` AND that item's `producto_presentacion_id` is in the original `active_intent.candidate_ids`, the function SHALL follow the existing unique-selection path: build a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the selected id, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed.

#### Scenario: Exact unique match resolves to ready without an extra confirmation

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaGrande]` and the message is `Pizza de Muzzarella Grande` and the recognizer returns exactly one `producto_presentacion_id` in `encontrados`
- **THEN** the returned intent has `status == "ready"`, `resolved_data["producto_presentacion_id"] == PizzaMuzzarellaGrande`, `candidate_ids == []`, and the original `cantidad` preserved — the dispatcher then routes the intent to `execute_ready_pending_context` in the SAME turn

### Requirement: Confident match takes priority over candidates

When the recognizer returns exactly one item in `encontrados` AND at least one group in `encontrados_posibles`, the function SHALL ignore the candidate groups and apply the unique-selection path against the single `encontrados` item. The candidate-narrowing branch SHALL NOT fire when a confident match is present.

#### Scenario: Confident match wins over candidates

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [PizzaMuzzarellaGrande, PizzaNapolitanaGrande, PizzaMargheritaGrande]` and the message is `Pizza de Muzzarella Grande` and the recognizer returns one `producto_presentacion_id` in `encontrados` (the muzzarella grande) AND groups in `encontrados_posibles`
- **THEN** the returned intent has `resolved_data["producto_presentacion_id"] == PizzaMuzzarellaGrande`, `status == "ready"`, `candidate_ids == []`, and the candidate groups are ignored

### Requirement: No new side effects from the narrowing branch

The narrowing branch SHALL NOT call `commit`, `flush`, `refresh`, `expire`, or `begin` on the database, SHALL NOT modify the `Session` model, SHALL NOT mutate `active_intent` in place, SHALL NOT log anything, and SHALL NOT call handlers. The narrowing branch SHALL only return a new `ProcessedIntent` instance (or the input unchanged when the narrowing is not applicable).

#### Scenario: Narrowing does not commit

- **WHEN** the narrowing branch fires
- **THEN** the `db.commit` is not called (verified by a mock) and the input `active_intent` instance is not mutated (`is` comparison preserved when the function returns the input unchanged)

#### Scenario: Narrowing does not load the catalog

- **WHEN** the function builds the candidate-ids intersection
- **THEN** the function uses the recognizer's `encontrados_posibles` output and `active_intent.candidate_ids` directly — no additional SQLAlchemy query is issued from the resolver

### Requirement: Discriminating fragments resolve only within persisted active candidates

The resolver SHALL evaluate a product-selection clarification only against the catalog restricted to the active intent's persisted `candidate_ids`. When `picante`, `la picante`, `carne picante`, `la común`, or `la de carne común` uniquely distinguishes one valid candidate, the resolver SHALL select that candidate without broadening recognition to the commerce catalog.

#### Scenario: Picante uniquely selects active Carne candidate

- **WHEN** the active candidates are Empanada de Carne Picante Unidad and Empanada de Carne Unidad and the message is `picante`
- **THEN** the resolver selects only Empanada de Carne Picante Unidad

#### Scenario: Selected ID must remain in active candidate domain

- **WHEN** recognition yields an ID that is not present in the active intent's original `candidate_ids`
- **THEN** the resolver returns the active intent unchanged and does not mutate the queue

### Requirement: Unique fragment resolution produces a ready intent without data loss

When a discriminating fragment leaves exactly one valid candidate, the resolver SHALL return a new intent with that `producto_presentacion_id`, mark the product requirement completed, clear `candidate_ids`, preserve existing `resolved_data` including `cantidad`, and set status to `ready` when all required requirements are complete.

#### Scenario: Quantity survives unique fragment resolution

- **WHEN** an active Carne intent has `cantidad == 4` and `picante` uniquely identifies its Picante candidate
- **THEN** the returned intent is `ready`, contains the selected ID, has empty candidate IDs, and preserves `cantidad == 4`

#### Scenario: Unique fragment does not return unchanged ambiguity

- **WHEN** one persisted active candidate uniquely matches the normalized clarification
- **THEN** the resolver does not return the unchanged `pending_resolution` intent or recreate its original candidate list

### Requirement: Partial and failed fragment refinement preserve valid pending state

When a fragment matches multiple active candidates, the resolver SHALL remain `pending_resolution` with only the valid refined candidates in original order. When it matches none, the resolver SHALL preserve the active intent unchanged. Neither path SHALL alter queued intents.

#### Scenario: Multiple matches retain refined ambiguity

- **WHEN** a fragment leaves more than one candidate from the active candidate catalog
- **THEN** the resolver returns `pending_resolution` with those candidate IDs and preserves quantity and other intent fields

#### Scenario: No match preserves active and queue

- **WHEN** a clarification matches no active candidate
- **THEN** the active intent remains unchanged and the queue is not altered

### Requirement: Product-selection resolver emits diagnostic events through a sink

The `resolve_product_selection` function SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The function SHALL emit a `ResolverCallStarted` event immediately before the catalog query and a `ResolverCallCompleted` event immediately after the recognizer result is consumed. The `Started` event SHALL carry the `call_id`, `turn_id`, the resolver class, the resolver method (`resolve_product_selection`), the resolver purpose (`product_selection_refinement`), the session id, the incoming text, the normalized text (if available), the intent, the source text, the quantity, the status before the call, the requirements before the call, the resolved data before the call, the candidate ids before the call, the candidate count, and a candidate catalog projection (the 12 fields already built for `detectar_productos`). The `Completed` event SHALL carry the call_id, the result type, the status after the call, the selected candidate id, the selected product name, the quantity after the call, the requirements after the call, the resolved data after the call, the candidate ids after the call, the candidate count after the call, the rejection reason (if any), the clarification message (if any), the raw result, and a matches list (one entry per `encontrados` / `encontrados_posibles` group with the candidate id, the candidate name, the score (if available), the match type, the matched text, and the accepted flag). The function SHALL NOT call `commit`, `rollback`, `flush`, `refresh`, `expire`, or `begin`; it SHALL NOT modify the session model; it SHALL NOT call handlers. The function SHALL NOT re-resolve the intent.

#### Scenario: Default sink is a no-op
- **WHEN** `resolve_product_selection(db, message, active_intent)` is called without a `sink` argument
- **THEN** the function returns the same `ProcessedIntent` it returned before this subphase and emits no event

#### Scenario: Started event captures the resolver input
- **WHEN** `resolve_product_selection(db, "picante", active_intent, *, sink=stub)` is called with `active_intent.status == "pending_resolution"` and `candidate_ids == [10, 11]`
- **THEN** the emitted `ResolverCallStarted` event carries `resolver_class="ProductSelectionContextResolver"`, `resolver_method="resolve_product_selection"`, `incoming_text="picante"`, `intent="agregar_producto"`, `status_before="pending_resolution"`, `candidate_ids_before=[10, 11]`, and the built candidate catalog

#### Scenario: Completed event captures the unique selection
- **WHEN** the recognizer returns exactly one candidate in `encontrados` and the resolver selects it
- **THEN** the emitted `ResolverCallCompleted` event carries `status_after="ready"`, `selected_candidate_id=<id>`, `candidate_ids_after=[]`, `candidate_count_after=0`, and the matches list with the single entry

#### Scenario: Completed event captures the narrowing branch
- **WHEN** the recognizer returns zero items in `encontrados` and three groups in `encontrados_posibles` that narrow the active candidates
- **THEN** the emitted `ResolverCallCompleted` event carries `status_after="pending_resolution"`, `candidate_ids_after=[<narrowed ids>]`, and the matches list with the three narrowed entries

#### Scenario: Completed event captures the unchanged branch
- **WHEN** the recognizer returns zero items in `encontrados` and an empty `encontrados_posibles`
- **THEN** the emitted `ResolverCallCompleted` event carries `result_type="ProcessedIntent"` (the same input), `status_after="pending_resolution"`, and `candidate_ids_after=[<original ids>]`
#### Scenario: Resolver does not re-resolve when sink is active

- **WHEN** the same `resolve_product_selection` is called with a `CollectingDiagnosticSink` and with a `NoopDiagnosticSink`
- **THEN** the `detectar_productos` call count is identical in both runs (1 call per resolve) and the catalog query runs exactly once

### Requirement: Presentacion-alias narrow step matches against producto_nombre

When `detectar_productos` returns zero items in `encontrados` AND an empty `encontrados_posibles`, the resolver SHALL call `_narrow_by_presentacion_alias` with the user message, the active intent, and the candidate catalog already built for the call. For each candidate row in the catalog, the resolver SHALL consider the row a match when the presentacion alias token returned by `_extraer_presentacion` (the canonical form, after the alias normalization) appears as a whole word (case-insensitive) in the candidate's `producto_nombre`. The whole-word test SHALL normalize the product name with `_normalizar_texto`, split on whitespace, and test set membership. The existing `presentacion_codigo` match path SHALL remain unchanged. The resolver SHALL then take the intersection of those matches with the active intent's `candidate_ids` (preserving the original order). When the intersection has exactly one element, the resolver SHALL return a new `ProcessedIntent` with that `producto_presentacion_id` set in `resolved_data`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed. When the intersection has more than one element, the resolver SHALL return a copy of the active intent with the reduced `candidate_ids`. When the intersection is empty, the resolver SHALL return the active intent unchanged. The alias table (`PRESENTACION_ALIASES`) and the `_extraer_presentacion` helper SHALL NOT be modified.

#### Scenario: Picante uniquely selects product-level alias candidate

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Empanada de Carne Unidad, Empanada de Carne Picante Unidad]` and the message is `picante` and the catalog contains both candidates with `producto_nombre` "Empanada de Carne" and "Empanada de Carne Picante" and `presentacion_codigo` "UNIDAD" for both
- **THEN** the resolver selects only Empanada de Carne Picante Unidad, returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: Tradicional narrows to a single product-level alias candidate

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Pizza Muzzarella Unidad, Pizza Muzzarella Tradicional Unidad]` and the message is `tradicional` and the catalog contains both candidates with the same `presentacion_codigo` "UNIDAD"
- **THEN** the resolver selects only Pizza Muzzarella Tradicional Unidad, returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"]` set to the tradicional id, `candidate_ids == []`, and the original `cantidad` preserved

#### Scenario: Discriminating fragment with a product noun narrows to single candidate

- **WHEN** the active intent is `pending_resolution` with `source_text == "1 empanada de carne"` and `candidate_ids == [Empanada de Carne Unidad, Empanada de Carne Picante Unidad]` and the message is `carne picante` and the active intent's extraneous-token guard passes (because `carne` is in the active intent's source_text)
- **THEN** the resolver returns a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the Empanada de Carne Picante id, `candidate_ids == []`, `status == "ready"`, the original `cantidad == 1` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: Whole-word product name match rejects substring false positive

- **WHEN** the catalog contains a candidate whose normalized `producto_nombre` token list includes a token such as "picantes" (a non-canonical plural form) but does not include the exact token "picante"
- **THEN** the alias `picante` does NOT match that candidate, and the resolver's `matching_ids` excludes that candidate

#### Scenario: Existing presentacion_codigo path remains unchanged

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Pizza Muzzarella Chica, Pizza Muzzarella Grande]` and the message is `la grande` and the catalog contains both candidates with the same `producto_nombre` "Pizza Muzzarella" and `presentacion_codigo` "CHICA" and "GRANDE"
- **THEN** the resolver matches via the existing `presentacion_codigo` path, selects Pizza Muzzarella Grande, returns a new `ProcessedIntent` with `status == "ready"`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: Empty intersection returns the active intent unchanged

- **WHEN** the alias token does not appear in any candidate's normalized `producto_nombre` AND no candidate's `presentacion_codigo` matches the alias
- **THEN** the resolver returns the active intent unchanged (same instance), and the diagnostic `Completed` event records `status_after="pending_resolution"` and `candidate_ids_after` equal to the original `candidate_ids`

#### Scenario: Alias normalization applies to the product-name match

- **WHEN** the user message is `grandi` and the alias normalization maps `grandi` to `grande` and a candidate's `producto_nombre` contains the token "grande" as a whole word
- **THEN** the alias `grande` (the canonical form returned by `_extraer_presentacion`) matches the candidate's `producto_nombre`, and the resolver narrows to that candidate

#### Scenario: Multiple narrowed candidates keep pending_resolution

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Empanada de Carne Picante Unidad, Empanada de Carne Picante Docena]` and the message is `picante` and both candidates have `presentacion_codigo` "UNIDAD" and "DOCENA" respectively and both have `producto_nombre` "Empanada de Carne Picante"
- **THEN** the resolver returns a copy of the active intent with `candidate_ids` reduced to both ids, `status == "pending_resolution"`, the original `cantidad` preserved, and the diagnostic `Completed` event records the narrowing

### Requirement: Discriminating fragments that span the active intent and product-level alias

When a message combines a token from the active intent's `source_text` or `resolved_data` (a "narrowing noun" such as `carne`) with a presentacion alias that lives in `producto_nombre` (such as `picante`), the extraneous-token guard added in 3.32.5 SHALL permit the narrowing, and the new product-name match predicate SHALL then resolve the candidate set. The resolver SHALL return a new `ProcessedIntent` with the single remaining `producto_presentacion_id` set, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed.

#### Scenario: carne picante resolves to Empanada de Carne Picante

- **WHEN** the active intent is `pending_resolution` with `source_text == "1 empanada de carne"`, `candidate_ids == [31, 32]` (Empanada de Carne Unidad and Empanada de Carne Picante Unidad), and the message is `carne picante`
- **THEN** the resolver returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, `cantidad == 1` preserved, and the diagnostic `Completed` event records the unique selection with the active intent's `source_text` echoed back

#### Scenario: la picante resolves to Empanada de Carne Picante

- **WHEN** the active intent is `pending_resolution` with `source_text == "una empanada de carne"`, `candidate_ids == [31, 32]`, and the message is `la picante`
- **THEN** the resolver returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: la de carne picante resolves to Empanada de Carne Picante

- **WHEN** the active intent is `pending_resolution` with `source_text == "una empanada de carne"`, `candidate_ids == [31, 32]`, and the message is `la de carne picante`
- **THEN** the resolver returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

