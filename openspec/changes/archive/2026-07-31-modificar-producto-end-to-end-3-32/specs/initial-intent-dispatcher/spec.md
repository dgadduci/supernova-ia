## MODIFIED Requirements

### Requirement: Unsupported intent rejection

When the classifier returns a `ClassifiedIntent(intent=...)` for any `IntentName` other than `AGREGAR_PRODUCTO`, `QUITAR_PRODUCTO`, or `MODIFICAR_PRODUCTO` (and not `DESCONOCIDA`, which has its own rule), the dispatcher SHALL NOT invoke any orchestrator or handler and SHALL return a `ProcessedIntent` with `status="rejected"`, `intent=<intent string>`, `source_text=classified.mensaje`, `recognizer="intent_classifier"`, `handler=<intent string>`, and default empty `resolved_data`, `requirements`, and `candidate_ids`.

#### Scenario: saludo is rejected without execution

- **WHEN** the classifier returns one `ClassifiedIntent(intent=SALUDO, mensaje="hola")`
- **THEN** `process_initial_agregar_producto`, `process_initial_quitar_producto`, and `process_initial_modificar_producto` are not invoked and the returned list contains a single `ProcessedIntent(intent="saludo", source_text="hola", status="rejected", recognizer="intent_classifier", handler="saludo", resolved_data={}, requirements=[], candidate_ids=[])`

#### Scenario: Unknown intent names are not raised here

- **WHEN** the classifier returns a `ClassifiedIntent` with an `IntentName` that has no supported branch in the dispatcher
- **THEN** the dispatcher returns a `rejected` `ProcessedIntent` for that item instead of raising

## ADDED Requirements

### Requirement: modificar_producto dispatch

When `IntentClassifier.query(message)` returns an `IntentClassificationResult` that contains at least one `ClassifiedIntent(intent=IntentName.MODIFICAR_PRODUCTO, mensaje=...)`, the dispatcher SHALL call `process_initial_modificar_producto(db, session, classified.mensaje)` for each such item — in the order returned by the classifier — and SHALL append the resulting `ProcessedIntent` to the returned list. The orchestrator's returned `status` (`ready`, `pending_resolution`, `rejected`, `failed`) SHALL be propagated unchanged.

#### Scenario: modificar_producto returns the orchestrator's ProcessedIntent

- **WHEN** the classifier returns one `ClassifiedIntent(intent=MODIFICAR_PRODUCTO, mensaje="cambiá la pizza de muzzarella chica por una grande")`
- **THEN** `dispatch_initial_message` calls `process_initial_modificar_producto(db, session, "cambiá la pizza de muzzarella chica por una grande")` exactly once and returns a one-item list containing the orchestrator's `ProcessedIntent` unchanged

#### Scenario: modificar_producto preserves orchestrator status

- **WHEN** `process_initial_modificar_producto` returns a `ProcessedIntent(status="ready")` for unique source and destination matches
- **THEN** `dispatch_initial_message` returns that intent unchanged and does NOT auto-execute the handler

#### Scenario: modificar_producto pending_resolution is preserved

- **WHEN** `process_initial_modificar_producto` returns a `ProcessedIntent(status="pending_resolution", context_type="product_modification")`
- **THEN** `dispatch_initial_message` returns that intent unchanged

#### Scenario: modificar_producto rejected is preserved

- **WHEN** `process_initial_modificar_producto` returns a `ProcessedIntent(status="rejected")` for an absent source, an unavailable destination, or an equivalent source-and-destination case
- **THEN** `dispatch_initial_message` returns that intent unchanged

#### Scenario: modificar_producto does not invoke other orchestrators

- **WHEN** the classifier returns one `ClassifiedIntent(intent=MODIFICAR_PRODUCTO, mensaje="...")`
- **THEN** `process_initial_agregar_producto` and `process_initial_quitar_producto` are NOT invoked
