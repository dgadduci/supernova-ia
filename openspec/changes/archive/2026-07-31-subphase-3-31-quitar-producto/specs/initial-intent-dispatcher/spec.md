## MODIFIED Requirements

### Requirement: agregar_producto dispatch
When `IntentClassifier.query(message)` returns an `IntentClassificationResult` that contains at least one `ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje=...)`, the dispatcher SHALL call `process_initial_agregar_producto(db, session, classified.mensaje)` for each such item — in the order returned by the classifier — and SHALL append the resulting `ProcessedIntent` to the returned list.

#### Scenario: agregar_producto returns the orchestrator's ProcessedIntent
- **WHEN** the classifier returns one `ClassifiedIntent(intent=AGREGAR_PRODUCTO, mensaje="una empanada")`
- **THEN** `dispatch_initial_message` calls `process_initial_agregar_producto(db, session, "una empanada")` exactly once and returns a one-item list containing the orchestrator's `ProcessedIntent` unchanged

#### Scenario: agregar_producto alongside other intents preserves order
- **WHEN** the classifier returns `agregar_producto` then `desconocida`
- **THEN** the returned list contains the `agregar_producto` orchestrator result in position 0 and the `desconocida` rejected `ProcessedIntent` in position 1, in that order

### Requirement: quitar_producto dispatch
When `IntentClassifier.query(message)` returns an `IntentClassificationResult` that contains at least one `ClassifiedIntent(intent=IntentName.QUITAR_PRODUCTO, mensaje=...)`, the dispatcher SHALL call `process_initial_quitar_producto(db, session, classified.mensaje)` for each such item — in the order returned by the classifier — and SHALL append the resulting `ProcessedIntent` to the returned list. The orchestrator's returned `status` (`ready`, `pending_resolution`, `rejected`, `failed`) SHALL be propagated unchanged.

#### Scenario: quitar_producto returns the orchestrator's ProcessedIntent
- **WHEN** the classifier returns one `ClassifiedIntent(intent=QUITAR_PRODUCTO, mensaje="quitá la pizza de muzzarella grande")`
- **THEN** `dispatch_initial_message` calls `process_initial_quitar_producto(db, session, "quitá la pizza de muzzarella grande")` exactly once and returns a one-item list containing the orchestrator's `ProcessedIntent` unchanged

#### Scenario: quitar_producto preserves orchestrator status
- **WHEN** `process_initial_quitar_producto` returns a `ProcessedIntent(status="ready")` for a unique match
- **THEN** `dispatch_initial_message` returns that intent unchanged and does NOT auto-execute the handler

#### Scenario: quitar_producto pending_resolution is preserved
- **WHEN** `process_initial_quitar_producto` returns a `ProcessedIntent(status="pending_resolution", context_type="order_line_selection")`
- **THEN** `dispatch_initial_message` returns that intent unchanged

### Requirement: Unsupported intent rejection
When the classifier returns a `ClassifiedIntent(intent=...)` for any `IntentName` other than `AGREGAR_PRODUCTO` or `QUITAR_PRODUCTO` (and not `DESCONOCIDA`, which has its own rule), the dispatcher SHALL NOT invoke any orchestrator or handler and SHALL return a `ProcessedIntent` with `status="rejected"`, `intent=<intent string>`, `source_text=classified.mensaje`, `recognizer="intent_classifier"`, `handler=<intent string>`, and default empty `resolved_data`, `requirements`, and `candidate_ids`.

#### Scenario: saludo is rejected without execution
- **WHEN** the classifier returns one `ClassifiedIntent(intent=SALUDO, mensaje="hola")`
- **THEN** `process_initial_agregar_producto` and `process_initial_quitar_producto` are not invoked and the returned list contains a single `ProcessedIntent(intent="saludo", source_text="hola", status="rejected", recognizer="intent_classifier", handler="saludo", resolved_data={}, requirements=[], candidate_ids=[])`

#### Scenario: Unknown intent names are not raised here
- **WHEN** the classifier returns a `ClassifiedIntent` with an `IntentName` that has no supported branch in the dispatcher
- **THEN** the dispatcher returns a `rejected` `ProcessedIntent` for that item instead of raising
