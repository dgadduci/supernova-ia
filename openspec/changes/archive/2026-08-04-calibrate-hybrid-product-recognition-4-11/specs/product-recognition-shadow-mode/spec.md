## ADDED Requirements

### Requirement: Offline calibration preserves shadow-mode authority and contracts

Subphase 4.11 SHALL reuse the observational ranking and decision semantics established by product-recognition shadow mode only inside the offline calibration runner. It SHALL NOT change `ProductRecognitionShadowComparison`, `ProductRecognitionHybridObservation`, `ShadowMetricsRecorder`, `ProductRecognitionShadowService`, the recognizer factory, runtime settings, provisional values, or any runtime call site.

Fuzzy recognition SHALL remain authoritative, shadow mode SHALL remain observational, and no `hybrid` runtime mode SHALL be added. The selected offline policy and its dataset fingerprint SHALL NOT be promoted automatically into runtime defaults or settings. Handlers, resolvers, pending contexts, intents, orders, responses, and persistence contracts SHALL remain unchanged.

#### Scenario: Calibration does not alter runtime behavior

- **WHEN** the offline calibration runner evaluates one or more policies
- **THEN** runtime fuzzy and shadow behavior remains byte-for-byte equivalent to Subphase 4.10.1
- **AND** `PRODUCT_RECOGNIZER_MODE` is neither read for policy authority nor modified
- **AND** no selected policy is installed as a runtime default

#### Scenario: Existing shadow failures remain observational

- **WHEN** an embedding or vector failure occurs during offline calibration
- **THEN** the runner records a sanitized calibration failure and continues
- **AND** no runtime comparison, observation, recorder, response, pending context, or persistence contract is changed

#### Scenario: Existing subphase regressions remain green

- **WHEN** Subphase 4.11 implementation is verified
- **THEN** focused tests for Subphases 4.5 through 4.10.1 pass unchanged except for test harness reuse needed by the offline calibration tests
- **AND** fuzzy remains authoritative in existing agregar, quitar, and modificar flows
