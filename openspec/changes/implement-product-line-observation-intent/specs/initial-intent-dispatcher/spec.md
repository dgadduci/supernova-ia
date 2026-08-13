## ADDED Requirements

### Requirement: set_observacion_producto dispatch

When `IntentClassifier.query(message)` returns
`ClassifiedIntent(intent=IntentName.SET_OBSERVACION_PRODUCTO, mensaje=...)`,
the dispatcher SHALL call
`process_initial_set_observacion_producto(db, session, classified.mensaje)`
once for that item in classifier order and return its `ProcessedIntent`
unchanged. The dispatcher itself SHALL not select a line, parse an observation,
write a row, or generate a response.

#### Scenario: Existing classified intent reaches its orchestrator

- **WHEN** the classifier returns one `set_observacion_producto` item
- **THEN** the dispatcher delegates to its initial orchestrator with the same
  classified message instead of the generic rejected fallback
