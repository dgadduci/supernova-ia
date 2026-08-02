## ADDED Requirements

### Requirement: IntentName enum
The system SHALL export an `IntentName` `StrEnum` from `backend/intents/schemas/intent_classification.py` containing exactly the intent names currently declared in the legacy `IntentClassifier`, preserving their spelling and string values.

#### Scenario: Legacy intent names are preserved
- **WHEN** the `IntentName` enum is inspected
- **THEN** it contains the same set of names as the legacy classifier, including `saludo`, `agradecimiento`, `despedida`, `respuesta_afirmativa`, `respuesta_negativa`, `ver_menu`, `consultar_producto`, `ver_metodos_de_pago`, `ver_metodos_de_entrega`, `consultar_domicilio_comercio`, `consultar_horarios_comercio`, `iniciar_pedido`, `agregar_producto`, `quitar_producto`, `vaciar_pedido`, `set_observacion_producto`, `set_observacion_pedido`, `consultar_resumen_pedido`, `set_metodo_de_entrega`, `set_direccion_entrega`, `set_fecha_hora_entrega`, `set_metodo_de_pago`, `confirmar_pedido`, `consultar_estado_pedido`, `cancelar_pedido`, and `desconocida`

#### Scenario: New intents are not added
- **WHEN** an implementation requires an additional intent
- **THEN** this subphase does not extend `IntentName`; new names require a dedicated follow-up

### Requirement: ClassifiedIntent schema
The system SHALL export `ClassifiedIntent` with `intent: IntentName` and `mensaje: str`, rejecting extra fields, trimming `mensaje`, and rejecting empty-after-trim values.

#### Scenario: Valid ClassifiedIntent is accepted
- **WHEN** a `ClassifiedIntent` is constructed with a known `IntentName` and a non-empty trimmed message
- **THEN** validation passes

#### Scenario: Empty message is rejected
- **WHEN** a `ClassifiedIntent` is constructed with an empty or whitespace-only message
- **THEN** validation fails

#### Scenario: Extra fields are rejected
- **WHEN** a `ClassifiedIntent` includes any field outside `intent` and `mensaje`
- **THEN** validation fails

#### Scenario: Unsupported intent is rejected
- **WHEN** a `ClassifiedIntent` is constructed with an `intent` value outside the legacy enum
- **THEN** validation fails

### Requirement: IntentClassificationResult schema
The system SHALL export `IntentClassificationResult` with `intents: list[ClassifiedIntent]` and `mensaje: str`, rejecting extra fields, trimming and rejecting empty original messages, requiring at least one classified intent, and preserving the order of `intents`.

#### Scenario: Valid single-intent result is accepted
- **WHEN** an `IntentClassificationResult` is constructed with one `ClassifiedIntent` and a non-empty message
- **THEN** validation passes

#### Scenario: Multiple intents preserve order
- **WHEN** an `IntentClassificationResult` is constructed with several `ClassifiedIntent` values
- **THEN** the order is preserved and each entry validates against the legacy enum

#### Scenario: Empty intents list is rejected
- **WHEN** an `IntentClassificationResult` has no `intents`
- **THEN** validation fails

#### Scenario: Empty message is rejected
- **WHEN** an `IntentClassificationResult` has an empty or whitespace-only `mensaje`
- **THEN** validation fails

#### Scenario: Extra fields are rejected
- **WHEN** an `IntentClassificationResult` carries any additional field
- **THEN** validation fails

### Requirement: Public surface
The `intent_classification` module SHALL expose the schemas through `__all__` and SHALL NOT introduce LLM calls, prompt construction, HTTP requests, or session/pedido/context mutations.

#### Scenario: Module exports are limited to schemas
- **WHEN** the module is imported
- **THEN** `__all__` includes only `IntentName`, `ClassifiedIntent`, and `IntentClassificationResult`
