## ADDED Requirements

### Requirement: Hybrid authoritative policy path setting

`backend.config.settings.Settings` SHALL expose a
`hybrid_authoritative_policy_path` attribute accepting either `None`
or a `str` path to a JSON calibration report. The default value SHALL
be `None`. The setting SHALL be overridable through an environment
variable of the same name. The validator SHALL run ONLY when the
effective `product_recognizer_mode` is `"hybrid_authoritative"`. In
that mode, the validator SHALL raise
`InvalidHybridAuthoritativePolicyPath(ValueError)` when the value is
anything other than `None` or a non-empty `str`. When the effective
mode is `"fuzzy"` (including the safe-fuzzy fallback case) or
`"shadow"`, the validator SHALL NOT run and a non-`None` value SHALL
be silently ignored.

#### Scenario: Default policy path is None

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.hybrid_authoritative_policy_path is None`

#### Scenario: Explicit path override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=/tmp/report.json` are set before
  `Settings.load()` is called
- **THEN** `settings.hybrid_authoritative_policy_path ==
  "/tmp/report.json"`

#### Scenario: Empty path override is rejected at load time in hybrid_authoritative mode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=` (empty string) are set before
  `Settings.load()` is called
- **THEN** `Settings.load()` raises
  `InvalidHybridAuthoritativePolicyPath`

#### Scenario: Path override is ignored in fuzzy mode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=fuzzy` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=/tmp/report.json` are set before
  `Settings.load()` is called
- **THEN** `Settings.load()` completes without raising
- **AND** the factory does NOT read the policy path

### Requirement: Safe-fuzzy fallback for unrecognised `PRODUCT_RECOGNIZER_MODE` literals

The `PRODUCT_RECOGNIZER_MODE` env-var resolver in
`backend.config.settings` SHALL treat any literal other than
`"fuzzy"`, `"shadow"`, and `"hybrid_authoritative"` as an unrecognised
value. The resolver SHALL return `"fuzzy"` as the effective mode and
SHALL emit exactly one sanitized structured log record through the
standard `logging` mechanism carrying the fields
`configured_mode` (the raw env-var literal the operator set),
`effective_mode` (the literal `"fuzzy"`), and `reason` (the sanitized
literal `"invalid_mode"`). The resolver SHALL NOT raise
`InvalidProductRecognizerMode(ValueError)`. The application SHALL
continue loading so the module-import-time
`get_product_recognizer(load_settings())` call resolves to the
`fuzzy` branch. The hybrid authoritative policy file SHALL NOT be
loaded and the `HybridAuthoritativeProductRecognizer` SHALL NOT be
constructed. The `InvalidProductRecognizerMode(ValueError)` class
SHALL remain defined as a reserved internal marker for callers that
want to validate settings coming from a non-env source; the env-var
resolver SHALL NOT raise it.

#### Scenario: Invalid literal falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` completes without raising
- **AND** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured log record is emitted carrying
  `configured_mode == "hybrid_active"`,
  `effective_mode == "fuzzy"`, and `reason == "invalid_mode"`
- **AND** the log record does NOT carry the raw exception text, a
  Python stack trace, the customer message, the database
  credentials, the host name, or any internal exception detail

#### Scenario: Capitalised typo falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=HybridAuthoritative` is set
  before `Settings.load()` is called
- **THEN** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured log record is emitted carrying
  `configured_mode == "HybridAuthoritative"`,
  `effective_mode == "fuzzy"`, and `reason == "invalid_mode"`

#### Scenario: Empty value falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=` (empty string) is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` treats the empty string as an
  unrecognised literal and falls back to `"fuzzy"` with the same
  warning shape as the documented invalid-literal scenario

#### Scenario: Safe-fuzzy fallback does not raise InvalidProductRecognizerMode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` does NOT raise
  `InvalidProductRecognizerMode(ValueError)`

### Requirement: Hybrid authoritative mode records `mode` and `hybrid_non_authoritative=False` through the existing recorder

The `ShadowMetricsRecorder` SHALL accept a new optional `mode` argument
on `record(...)`. The recorder SHALL emit a new `mode` log field on
every record whose value equals the `mode` argument (defaulting to
`"shadow"` when the argument is omitted, so existing shadow-mode
callers do not have to change). When `mode == "hybrid_authoritative"`,
the recorder SHALL emit `hybrid_non_authoritative=False`; otherwise the
recorder SHALL emit `hybrid_non_authoritative` as the value carried by
the `ProductRecognitionHybridObservation.non_authoritative` field
(preserving the 4.10 shadow-mode semantics). The recorder SHALL NOT
emit `hybrid_non_authoritative=False` for `mode == "shadow"` or any
other mode.

#### Scenario: Recorder defaults mode to shadow

- **WHEN** `record(...)` is called without a `mode` argument
- **THEN** the emitted log record carries `mode="shadow"`
- **AND** the emitted log record carries
  `hybrid_non_authoritative` matching
  `hybrid_observation.non_authoritative`

#### Scenario: Recorder marks hybrid_authoritative decisions as authoritative

- **WHEN** `record(..., mode="hybrid_authoritative")` is called
- **THEN** the emitted log record carries
  `mode="hybrid_authoritative"`
- **AND** the emitted log record carries
  `hybrid_non_authoritative=False`

#### Scenario: Recorder preserves existing shadow-mode semantics

- **WHEN** `record(..., mode="shadow")` is called
- **THEN** the emitted log record carries `mode="shadow"`
- **AND** the emitted log record carries
  `hybrid_non_authoritative` matching
  `hybrid_observation.non_authoritative`

### Requirement: Backward-compatible shared boundary carries the catalog scope to the hybrid recognizer

The `ProductRecognizerProtocol.recognize` method SHALL gain a
keyword-only optional `intent_metadata` argument that callers use to
declare the catalog scope of the recognition call. The argument
SHALL carry a `RecognizeContext` TypedDict defined in
`backend/recognizers/product_recognizer_contract.py` with the
documented field
`catalog_scope: Literal["pending_product_selection_restricted",
"commerce_dynamic_database"]`. The `FuzzyProductRecognizer.recognize`
and `ShadowedProductRecognizer.recognize` methods SHALL accept the
new keyword argument and SHALL ignore it. The new
`HybridAuthoritativeProductRecognizer.recognize` (added by
`controlled-hybrid-product-recognition`) SHALL read `catalog_scope`
from the argument to fire the 4.11.5 guard. Every call site that
omits the argument SHALL continue to work without modification. The
change SHALL NOT add any intent-specific import inside any
recognizer. The single call site that passes
`intent_metadata={"catalog_scope": "pending_product_selection_restricted"}`
SHALL be the `detect` call inside
`backend/intents/context/product_selection_context_resolver.py`. The
local `detectar_productos` symbol in each affected module SHALL be
rewritten as a thin wrapper that accepts and forwards
`intent_metadata`. The change SHALL NOT move caller-owned
transactions and SHALL NOT re-query the full commerce catalog.

#### Scenario: Fuzzy recognizer accepts the new intent_metadata argument

- **WHEN** `FuzzyProductRecognizer.recognize(text, catalog,
  intent_metadata=RecognizeContext(catalog_scope=
  "pending_product_selection_restricted"))` is called
- **THEN** the call succeeds
- **AND** the fuzzy result is byte-for-byte equivalent to the call
  without the argument
- **AND** no intent-specific import is added to the recognizer

#### Scenario: Shadowed recognizer accepts the new intent_metadata argument

- **WHEN** `ShadowedProductRecognizer.recognize(text, catalog,
  intent_metadata=RecognizeContext(catalog_scope=
  "pending_product_selection_restricted"))` is called
- **THEN** the call succeeds
- **AND** the shadow service does not read `intent_metadata`
- **AND** the fuzzy result returned to the caller is unchanged
- **AND** the shadow comparison payload is recorded with the
  existing `mode="shadow"` semantics

#### Scenario: Product recognizer protocol accepts the new intent_metadata argument

- **WHEN** `ProductRecognizerProtocol` is inspected
- **THEN** the `recognize` method signature includes a keyword-only
  optional `intent_metadata: RecognizeContext | None = None`
  argument
- **AND** every implementation of the protocol accepts the argument

#### Scenario: Product selection context resolver passes the restricted catalog scope

- **WHEN** the resolver inside
  `backend/intents/context/product_selection_context_resolver.py`
  invokes `detectar_productos` against the restricted candidate
  catalog for the active pending intent
- **THEN** the call passes
  `intent_metadata={"catalog_scope":
  "pending_product_selection_restricted"}`

#### Scenario: Other call sites omit the intent_metadata argument

- **WHEN** the `agregar_producto` orchestrator's initial commerce-
  catalog call, the `modificar_producto` destination selection call,
  or the `quitar_producto` order-line call invokes `detectar_productos`
- **THEN** the call omits the `intent_metadata` argument (or passes
  `None`)
- **AND** the call is unaffected by the new argument

## MODIFIED Requirements

### Requirement: Product recognizer mode setting

`backend.config.settings.Settings` SHALL expose a `product_recognizer_mode`
attribute accepting the literals `"fuzzy"`, `"shadow"`, or
`"hybrid_authoritative"`. The default value SHALL be `"fuzzy"`. The
setting SHALL be overridable through an environment variable of the
same name. When the env value is one of the three documented
literals, `Settings.load()` SHALL accept the literal verbatim. When
the env value is any other literal (including the empty string), the
env-var resolver SHALL return `"fuzzy"` as the effective mode and
SHALL emit a single sanitized structured warning; the resolver SHALL
NOT raise an exception that prevents application startup or
customer processing. The fuzzy recognizer SHALL remain the sole
authoritative recognizer in the `"fuzzy"` mode; the `"shadow"` value
SHALL remain purely observational; the `"hybrid_authoritative"`
value SHALL be the opt-in mode documented in
`controlled-hybrid-product-recognition`. The
`InvalidProductRecognizerMode(ValueError)` class SHALL remain defined
as a reserved internal marker for callers that want to validate
settings coming from a non-env source; the env-var resolver SHALL
NOT raise it.

#### Scenario: Default mode is fuzzy

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.product_recognizer_mode == "fuzzy"`
- **AND** no warning is emitted

#### Scenario: Shadow mode override is accepted

- **WHEN** the environment variable `PRODUCT_RECOGNIZER_MODE=shadow`
  is set before `Settings.load()` is called
- **THEN** `settings.product_recognizer_mode == "shadow"`
- **AND** no warning is emitted

#### Scenario: Hybrid authoritative mode override is accepted

- **WHEN** the environment variable
  `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` is set before
  `Settings.load()` is called
- **THEN** `settings.product_recognizer_mode ==
  "hybrid_authoritative"`
- **AND** no warning is emitted

#### Scenario: Invalid mode falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` completes without raising
- **AND** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured log record is emitted carrying
  `configured_mode`, `effective_mode`, and `reason`
- **AND** the hybrid authoritative policy file is NOT loaded

### Requirement: Settings-driven factory resolves the shared recognizer boundary

The system SHALL expose a `get_product_recognizer(settings:
Settings) -> ProductRecognizerProtocol` factory in
`backend/services/product_recognition_factory.py`. The factory SHALL:

1. Construct a `FuzzyProductRecognizer` instance.
2. When `settings.product_recognizer_mode == "fuzzy"`, return the
   fuzzy recognizer unchanged.
3. When `settings.product_recognizer_mode == "shadow"`, return a
   `ShadowedProductRecognizer` that wraps the fuzzy recognizer and
   delegates comparison to a `ProductRecognitionShadowService`
   constructed from the same settings and an injected
   `ShadowMetricsRecorder` instance.
4. When `settings.product_recognizer_mode == "hybrid_authoritative"`,
   return a `HybridAuthoritativeProductRecognizer` that wraps the
   fuzzy recognizer and delegates the hybrid decision to a
   `HybridAuthoritativeProductRecognizer` constructed from the same
   settings, the calibrated `HybridDecisionPolicy` loaded by
   `HybridAuthoritativePolicySource.load(settings)`, an injected
   `ShadowMetricsRecorder` instance, and the existing
   `embedding_client`, `session_provider`, and
   `commerce_id_resolver` injection points. A failure from the policy
   loader SHALL propagate as `HybridAuthoritativePolicyError` before
   any recognizer is built.

`backend/intents/orchestration/agregar_producto_orchestrator.py`
SHALL resolve its module-level `_product_recognizer` through
`get_product_recognizer(load_settings())` once at module import
time and SHALL continue to re-export `detectar_productos =
_product_recognizer.recognize` as the shared product-recognition
boundary used by the `agregar_producto`, `quitar_producto`, and
`modificar_producto` orchestrators. The local `detectar_productos`
symbol in `product_selection_context_resolver`,
`product_modification_resolver`, `quitar_producto_recognizer`, and
`modificar_producto_recognizer` SHALL be a thin wrapper that accepts
and forwards `intent_metadata`.

#### Scenario: Fuzzy mode resolves to the fuzzy recognizer

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "fuzzy"`
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Shadow mode resolves to the shadowed recognizer

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "shadow"`
- **THEN** the returned recognizer is a `ShadowedProductRecognizer`
  instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Hybrid authoritative mode resolves to the hybrid authoritative recognizer

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "hybrid_authoritative"` and
  `settings.hybrid_authoritative_policy_path` pointing at a valid
  eligible calibration report
- **THEN** the returned recognizer is a
  `HybridAuthoritativeProductRecognizer` instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Safe-fuzzy fallback resolves the factory to the fuzzy recognizer

- **WHEN** `get_product_recognizer(load_settings())` is called after
  `PRODUCT_RECOGNIZER_MODE=hybrid_active` resolved the effective mode
  to `"fuzzy"` through the safe-fuzzy fallback
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance
- **AND** no hybrid policy file is read

#### Scenario: Orchestrator binding uses the factory

- **WHEN** the orchestrator module is imported
- **THEN** `_product_recognizer` is the result of
  `get_product_recognizer(load_settings())`
- **AND** `detectar_productos = _product_recognizer.recognize` is
  re-exported from the orchestrator module as a thin wrapper that
  forwards `intent_metadata`
- **AND** the import fails closed with `HybridAuthoritativePolicyError`
  when the policy path is missing or non-eligible in
  `hybrid_authoritative` mode
