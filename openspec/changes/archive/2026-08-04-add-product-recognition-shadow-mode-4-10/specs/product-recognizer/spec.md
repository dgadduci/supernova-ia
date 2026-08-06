## MODIFIED Requirements

### Requirement: Complete backend recognizer consumers retain their contracts

All production result consumers and lifecycle paths across `backend/`
SHALL continue receiving the current recognizer result shape and
identifiers after practical composition boundaries adopt the
abstraction. This includes initial `agregar_producto`, pending
product selection, `quitar_producto`, `modificar_producto` source
and destination recognition, product-intent resolution,
pending-context dispatch, ready execution, and FIFO queued-intent
promotion.

The integration boundary at
`backend/intents/orchestration/agregar_producto_orchestrator.py`
SHALL resolve the recognizer through a settings-driven factory
exposed as
`backend.services.product_recognition_factory.get_product_recognizer(settings)`.
The factory SHALL return a `FuzzyProductRecognizer` when
`settings.product_recognizer_mode == "fuzzy"` and a
`ShadowedProductRecognizer` (decorating a `FuzzyProductRecognizer`)
when `settings.product_recognizer_mode == "shadow"`. The factory
SHALL be invoked once at orchestrator module import time with
`load_settings()`; the resulting recognizer is bound to the
module-level `_product_recognizer` symbol and re-exported as
`detectar_productos = _product_recognizer.recognize`. In both
modes the recognizer result observed by the listed consumers
SHALL be byte-for-byte equivalent to the fuzzy recognizer output.
The orchestrator module SHALL continue to expose
`detectar_productos` as the shared product-recognition boundary
used by `agregar_producto`, `quitar_producto`, and
`modificar_producto` orchestrators; the handlers and the intent
interpreter SHALL NOT be rewritten to consume a different
recognizer surface.

#### Scenario: Initial agregar producto remains compatible

- **WHEN** an existing `agregar_producto` recognition flow runs through the abstraction
- **THEN** its unique or pending result preserves the current product ID, candidate IDs, quantity, result keys, and status behavior

#### Scenario: Pending product selection remains compatible

- **WHEN** an active pending product-selection intent is refined through the abstraction using its restricted catalog
- **THEN** the resolver and dispatcher receive the same recognized IDs and produce the same ready or pending outcome

#### Scenario: Removal and modification remain compatible

- **WHEN** `quitar_producto` or either source/destination recognition stage of `modificar_producto` runs through the abstraction
- **THEN** the current order-line and commerce-catalog boundaries and recognized identifiers are preserved

#### Scenario: Queue promotion remains compatible

- **WHEN** a ready pending result is executed and the FIFO queue promotes the next intent
- **THEN** the promoted intent and its candidate state remain unchanged by the recognizer abstraction

#### Scenario: Fuzzy mode returns the exact fuzzy result

- **WHEN** `product_recognizer_mode == "fuzzy"` and the
  `agregar_producto` orchestrator invokes `detectar_productos`
- **THEN** the shared boundary invokes the `FuzzyProductRecognizer`
  directly
- **AND** the returned `ProductRecognizerResult` is byte-for-byte
  equivalent to the output of
  `backend.recognizers.product_recognizer.detectar_productos`
- **AND** no shadow service, embedding client, or vector search
  service is invoked

#### Scenario: Shadow mode returns the exact fuzzy result

- **WHEN** `product_recognizer_mode == "shadow"` and the
  `agregar_producto` orchestrator invokes `detectar_productos`
- **THEN** the shared boundary invokes a `ShadowedProductRecognizer`
  that wraps the `FuzzyProductRecognizer`
- **AND** the `FuzzyProductRecognizer.recognize` method is invoked
  **exactly once** per call
- **AND** the `ShadowedProductRecognizer` forwards the
  already-computed fuzzy result and the measured fuzzy latency to
  the shadow service
- **AND** the shadow service does NOT invoke the fuzzy recognizer
- **AND** the returned `ProductRecognizerResult` is byte-for-byte
  equivalent to the underlying fuzzy recognizer output
- **AND** the `agregar_producto` orchestrator receives the same
  product ID, candidate IDs, quantity, and result keys as in
  fuzzy mode

#### Scenario: Shadow mode does not rewrite handlers

- **WHEN** the `agregar_producto`, `quitar_producto`, and
  `modificar_producto` orchestrators are inspected
- **THEN** they continue to import `detectar_productos` from
  `backend.intents.orchestration.agregar_producto_orchestrator`
- **AND** no handler, resolver, or intent-orchestration module
  imports the shadow service, the shadowed recognizer, the
  factory, the recorder, or the embedding client directly

#### Scenario: Orchestrator binding uses the settings-driven factory

- **WHEN** the orchestrator module is imported
- **THEN** `_product_recognizer` is the result of
  `get_product_recognizer(load_settings())`
- **AND** `detectar_productos = _product_recognizer.recognize` is
  re-exported from the orchestrator module
