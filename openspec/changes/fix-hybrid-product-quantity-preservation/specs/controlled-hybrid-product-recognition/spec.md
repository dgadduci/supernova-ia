## MODIFIED Requirements

### Requirement: Hybrid authoritative recognizer returns the hybrid decision with the 4.11.5 guard operational at runtime

The system SHALL expose `HybridAuthoritativeProductRecognizer` in
`backend/services/hybrid_authoritative_recognizer.py` that implements
`ProductRecognizerProtocol` and exposes a
`recognize(text, catalog, *, intent_metadata=None) ->
ProductRecognizerResult` method. It SHALL preserve every existing candidate
scope, vector filtering, decision, ranking, technical fuzzy fallback and
transaction-free invariant of this requirement.

When it translates a `unique` hybrid decision, its one `encontrados` entry
SHALL retain the top id from the existing filtered hybrid ranking and use the
positive quantity produced by the existing deterministic product-text quantity
extractor for the input. When it translates an `ambiguous` hybrid decision,
every existing candidate in its one `encontrados_posibles` group SHALL retain
its existing id/order and carry that same extracted quantity. An omitted
quantity SHALL retain the extractor's existing default of `1`. This parsing
SHALL NOT consult or select a candidate, alter the hybrid policy/decision/
ranking, widen the passed catalog, invoke an LLM, infer a quantity from a
later customer selection reply, alter the ambiguous result shape, or alter a
technical fuzzy fallback.

#### Scenario: Hybrid unique preserves an explicit word quantity

- **WHEN** the hybrid policy decides `unique` for an in-catalog presentation
  and the input contains `dos` or `tres`
- **THEN** the single translated `encontrados` entry keeps the existing top
  ranked presentation id and carries `cantidad == 2` or `cantidad == 3`
- **AND THEN** the other three result collections retain their existing shapes

#### Scenario: Hybrid unique defaults only when quantity is absent

- **WHEN** the hybrid policy decides `unique` and the input contains no valid
  explicit quantity
- **THEN** the translated entry carries `cantidad == 1`

#### Scenario: Hybrid ambiguity preserves quantity until a bounded selection

- **WHEN** the hybrid policy decides `ambiguous` for the in-catalog Carne
  Picante / Carne Suave presentations and the input is `quiero 2 empanadas de
  carne`
- **THEN** its one `encontrados_posibles` group contains only the existing
  ranked candidate ids in their existing order
- **AND THEN** every candidate carries `cantidad == 2`
- **AND THEN** the result remains ambiguous and does not select a presentation

#### Scenario: Hybrid ambiguity defaults only when quantity is absent

- **WHEN** the hybrid policy decides `ambiguous` and the input contains no
  valid explicit quantity
- **THEN** every existing candidate in that group carries `cantidad == 1`

#### Scenario: Hybrid technical fallback preserves fuzzy quantity

- **WHEN** the embedding or vector pipeline fails after the inner fuzzy
  recognizer supplied a result with a quantity
- **THEN** the recognizer returns that fuzzy result unchanged, including the
  original quantity
