## ADDED Requirements

### Requirement: Version-controlled baseline dataset schema

The system SHALL include a version-controlled product-recognition baseline dataset at `backend/tests/fixtures/product_recognizer_baseline.json` or the project’s established equivalent fixture location. Each case SHALL contain a unique `case_id`, input `text` or product fragment, a catalog fixture reference or catalog context, an expected `result_type` of `unique`, `ambiguous`, or `unknown`, and a short `reason` or `category`. A case may include `expected_producto_presentacion_id`, `expected_candidate_ids`, and `expected_quantity` according to its result type.

#### Scenario: Dataset contains required fields
- **WHEN** the dataset is loaded and each case is inspected
- **THEN** every case has the required fields and no case omits its expected result type

#### Scenario: Dataset case IDs are unique
- **WHEN** the dataset validator checks all cases
- **THEN** no `case_id` occurs more than once

### Requirement: Baseline covers representative current behavior

The baseline dataset SHALL include representative cases for exact product names, product plus presentation, fuzzy misspellings, supported aliases, ambiguous `empanada de carne`, `picante` refinement, ambiguous `pizza` or `pizza de muzarela`, `grande` presentation refinement, an unknown product such as `caramelo`, and a multi-word product such as `empanada de jamón y queso`.

#### Scenario: Unique case records its expected identifier
- **WHEN** a dataset case has `result_type == "unique"`
- **THEN** it records `expected_producto_presentacion_id` and that identifier exists in the referenced test catalog

#### Scenario: Ambiguous case records candidate identifiers
- **WHEN** a dataset case has `result_type == "ambiguous"`
- **THEN** it records a non-empty `expected_candidate_ids` collection and every ID exists in the referenced test catalog

#### Scenario: Unknown case records no product identifier
- **WHEN** a dataset case has `result_type == "unknown"`
- **THEN** it records no selected or candidate product identifier and expects an unmatched fragment

### Requirement: Refinement cases use pending-flow restricted catalogs

Every refinement case such as `picante` or `grande` SHALL identify that it uses a restricted pending-flow catalog and SHALL use the same candidate catalog and candidate IDs as the corresponding real pending product-selection or product-modification flow. The case SHALL NOT broaden the catalog to the full commerce catalog or introduce synthetic candidate IDs.

#### Scenario: Picante uses the real restricted candidate set
- **WHEN** the dataset executes the `picante` refinement case
- **THEN** the input catalog and candidate IDs match the restricted catalog used by the pending-context integration flow

#### Scenario: Grande uses the real restricted candidate set
- **WHEN** the dataset executes the `grande` presentation-refinement case
- **THEN** the input catalog and candidate IDs match the restricted pending candidate set rather than the full commerce catalog

### Requirement: Dataset uses existing test fixtures

The baseline dataset SHALL reference or embed catalog entries using actual identifiers from existing project test fixtures. The dataset validator SHALL reject a case whose expected identifier is absent from its catalog context, and the change SHALL NOT invent production identifiers solely for baseline coverage.

#### Scenario: Referenced IDs exist
- **WHEN** the validator resolves a case’s catalog fixture and expected IDs
- **THEN** every expected ID is present in that catalog

#### Scenario: Stale fixture reference fails validation
- **WHEN** a case references a missing catalog fixture, a wrong restricted candidate set, or an unavailable expected identifier
- **THEN** dataset validation fails with the case ID and the missing reference or scope mismatch

### Requirement: Known fuzzy limitations are explicit

A baseline case that records an accepted limitation of the current fuzzy recognizer SHALL include `known_fuzzy_limitation: true` and a non-empty `limitation_note`. Its expected result SHALL describe current fuzzy behavior only; the dataset SHALL NOT encode a desired future semantic result or treat the limitation as a requirement for the hybrid recognizer.

#### Scenario: Limitation metadata distinguishes current behavior
- **WHEN** a case is known to expose a fuzzy limitation
- **THEN** its metadata states the limitation and the validator reports it as current-behavior context rather than a desired future outcome

#### Scenario: Ordinary baseline case is not mislabeled
- **WHEN** a case is fully representative without a known fuzzy limitation
- **THEN** it omits or sets `known_fuzzy_limitation` to false and does not require a limitation note

### Requirement: Every baseline case executes against fuzzy recognition

The dataset validation suite SHALL execute every baseline case through the real fuzzy recognizer or its protocol-compatible `FuzzyProductRecognizer` without mocking the recognition call. It SHALL validate result type, expected IDs, restricted-catalog scope, and expected quantity where specified.

#### Scenario: Baseline execution succeeds
- **WHEN** all dataset cases run against the fuzzy recognizer
- **THEN** every case matches its declared unique, ambiguous, or unknown current-behavior expectation

#### Scenario: Quantity expectation is validated
- **WHEN** a case declares an expected quantity
- **THEN** the selected or candidate result exposes that quantity exactly as declared
