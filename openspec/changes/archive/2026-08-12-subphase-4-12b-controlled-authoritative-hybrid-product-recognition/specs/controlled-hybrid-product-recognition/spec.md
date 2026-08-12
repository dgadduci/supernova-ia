## MODIFIED Requirements

### Requirement: Recognizer is wired into the shared product-recognition boundary

The system SHALL extend `backend/services/product_recognition_factory.py` so
that `get_product_recognizer(settings)` returns a
`HybridAuthoritativeProductRecognizer` when the effective mode is
`"hybrid_authoritative"`. The factory SHALL construct a
`FuzzyProductRecognizer`, load the calibrated policy exactly once at factory
call time, construct the embedding client and per-call vector-search factory,
and wrap them in the hybrid recognizer with the recorder.

All production recognition callers — agregar_producto, quitar_producto,
modificar_producto, pending product selection, and pending modification
destination resolution — SHALL bind through this factory and retain ownership
of their already scoped catalog. They SHALL pass their naturally owned
`id_comercio` through the additive recognition context. The factory and
recognizers SHALL NOT reload a broader catalog, introduce a per-commerce
rollout setting, or create a second pipeline.

When the effective mode is `"fuzzy"`, including safe fallback for an invalid
mode, the factory SHALL return an observable fuzzy recognizer that remains a
`FuzzyProductRecognizer` instance, does not load hybrid policy or invoke
embedding/vector work, and emits the documented safe observation. In shadow,
fuzzy remains authoritative. A hybrid `unique` selects only an ID in the
passed catalog; `ambiguous` retains the existing pending path; and `unknown`
retains caller unknown behavior. Only hybrid infrastructure failures may return
fuzzy; semantic hybrid results MUST NOT fallback.

#### Scenario: Factory returns a HybridAuthoritativeProductRecognizer in hybrid_authoritative mode

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "hybrid_authoritative"` and a valid
  `hybrid_authoritative_policy_path`
- **THEN** the returned recognizer is a `HybridAuthoritativeProductRecognizer`
  instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer` instance

#### Scenario: Factory fails closed on a missing or non-eligible policy file

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "hybrid_authoritative"` and a missing
  or non-eligible policy path
- **THEN** the factory raises `HybridAuthoritativePolicyError`
- **AND** no recognizer is built and returned

#### Scenario: Factory returns a FuzzyProductRecognizer in fuzzy mode (unchanged)

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "fuzzy"`
- **THEN** the returned recognizer is a `FuzzyProductRecognizer` instance
- **AND** no hybrid wiring is invoked

#### Scenario: Factory returns a FuzzyProductRecognizer after the safe-fuzzy fallback

- **WHEN** `get_product_recognizer(load_settings())` is called after
  `PRODUCT_RECOGNIZER_MODE=hybrid_active` resolved effective mode to `"fuzzy"`
- **THEN** the returned recognizer is a `FuzzyProductRecognizer` instance
- **AND** no hybrid policy file is read
- **AND** no `HybridAuthoritativeProductRecognizer` is constructed

#### Scenario: Factory returns a ShadowedProductRecognizer in shadow mode (unchanged)

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "shadow"`
- **THEN** the returned recognizer is a `ShadowedProductRecognizer` instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer` instance

#### Scenario: Orchestrator binding uses the factory

- **WHEN** a production recognition entry point is imported
- **THEN** its `_product_recognizer` is bound through
  `get_product_recognizer(load_settings())`
- **AND** its thin wrapper forwards its scoped catalog and optional context
- **AND** hybrid mode fails closed with `HybridAuthoritativePolicyError` when
  the policy path is missing or non-eligible

#### Scenario: Quitar uses the configured boundary without broadening order lines

- **WHEN** quitar_producto recognizes a message while hybrid mode is configured
- **THEN** it uses the factory-selected recognizer against only active Pedido lines
- **AND** it does not query the commerce catalog to recognize the line

#### Scenario: Hybrid ambiguity remains pending

- **WHEN** hybrid returns an ambiguous decision for a scoped catalog
- **THEN** the caller creates or preserves its current pending context
- **AND** it does not substitute fuzzy merely to avoid ambiguity

#### Scenario: Vector query failure falls back safely

- **WHEN** vector search raises a technical exception
- **THEN** the returned recognition result equals the fuzzy result
- **AND** telemetry records `fallback=true` and a safe vector failure category

#### Scenario: Cross-commerce vector candidate is discarded

- **WHEN** vector search returns an ID absent from the caller catalog
- **THEN** that ID cannot appear in the hybrid result or pending candidates
