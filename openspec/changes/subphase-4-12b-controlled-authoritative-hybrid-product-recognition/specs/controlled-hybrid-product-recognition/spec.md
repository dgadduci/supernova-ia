## ADDED Requirements

### Requirement: One factory-selected authoritative recognition boundary serves all product flows

The system SHALL select the product recognition strategy only through the
existing settings-driven factory for agregar_producto, quitar_producto,
modificar_producto, pending product selection, and pending modification
destination resolution. Each caller SHALL retain ownership of its existing
catalog and SHALL pass that catalog to the shared boundary. The system SHALL
NOT add a second recognition pipeline, reload a broader catalog, or use a
per-commerce rollout setting.

#### Scenario: Quitar uses the configured boundary without broadening order lines

- **WHEN** quitar_producto recognizes a message while hybrid mode is configured
- **THEN** it uses the factory-selected recognizer against only active Pedido
  lines
- **AND** it does not query the commerce catalog to recognize the line

### Requirement: Hybrid authoritative semantic outcomes are returned without semantic fallback

In `hybrid_authoritative` mode, `unique` SHALL select the chosen
`producto_presentacion_id`; `ambiguous` SHALL preserve/create the existing
pending candidate context; and `unknown` SHALL follow each caller's existing
unknown behavior. `unknown`, `ambiguous`, low confidence, no strong candidate,
or a valid empty filtered vector result SHALL NOT trigger fallback to fuzzy.

#### Scenario: Hybrid ambiguity remains pending

- **WHEN** hybrid returns an ambiguous decision for a scoped catalog
- **THEN** the caller creates or preserves its current pending context
- **AND** it does not substitute the fuzzy result merely to avoid ambiguity

### Requirement: Fuzzy fallback is technical-only and safe

The hybrid recognizer SHALL return the already computed fuzzy result only for
embedding unavailable/failure, vector repository/query unavailable/failure,
malformed hybrid dependency output, or an unexpected technical exception. It
SHALL record a sanitized fallback category and SHALL not expose raw exception
details. No recognizer collaborator SHALL commit, rollback, flush, begin, or
close the caller transaction.

#### Scenario: Vector query failure falls back safely

- **WHEN** vector search raises a technical exception
- **THEN** the returned recognition result equals the fuzzy result
- **AND** telemetry records `fallback=true` and a safe vector failure category

### Requirement: Hybrid ranking remains scoped to the caller catalog

The hybrid recognizer SHALL derive allowed IDs exclusively from the supplied
catalog and discard vector results outside that set before guards, scoring,
ranking, or result translation. Restricted pending candidate sets SHALL not be
widened and candidate ordering contracts SHALL remain unchanged.

#### Scenario: Cross-commerce vector candidate is discarded

- **WHEN** vector search returns an ID absent from the caller catalog
- **THEN** that ID cannot appear in the hybrid result or pending candidates
