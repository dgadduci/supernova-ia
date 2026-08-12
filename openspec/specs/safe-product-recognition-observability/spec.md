# safe-product-recognition-observability Specification

## Purpose
Provide a single, privacy-safe and bounded operational event for existing
product-recognition observations. It lets authorized operators distinguish
normal hybrid business outcomes from approved technical fallback through the
shared production-observability catalogue, without exposing customer, commerce
or decision-input data and without changing recognition behavior.
## Requirements
### Requirement: Recognition observations use the shared safe event catalogue

The system SHALL emit each existing product-recognition observation through the
versioned operational-event catalogue as `shadow_product_recognition`, with a
closed recognition-specific allowlist. It SHALL include only configured and
effective mode, authoritative strategy, hybrid decision category, fallback
boolean/category and bounded aggregate latency fields.

#### Scenario: Hybrid business outcome is observed without fallback

- **WHEN** hybrid recognition produces `unique`, `ambiguous` or `unknown`
- **THEN** the catalogue emits the corresponding safe decision category
- **AND** `ambiguous` or `unknown` SHALL NOT be recorded as technical fallback.

#### Scenario: Technical fallback is observed safely

- **WHEN** the existing recognizer takes an approved technical fallback
- **THEN** the catalogue emits `fallback=true` with its allowlisted category
- **AND** no exception text, customer value or candidate data is emitted.

### Requirement: Recognition observations exclude sensitive decision inputs

The recognition event schema SHALL reject unknown fields and SHALL NOT emit or
return customer text, E.164 addresses, commerce IDs, product/candidate IDs,
correlation IDs, scores, vectors, prompts, payloads, policy values or raw
exceptions.

#### Scenario: Unsafe recorder field is supplied

- **WHEN** a recognition event carries a forbidden field
- **THEN** shared event validation SHALL reject it
- **AND** the bounded CLI SHALL not expose its raw Railway line.

### Requirement: Operators query recognition observations only through bounds

The existing production-log CLI SHALL accept the recognition event through its
normal catalogue parsing and preserve explicit target, time and finite-limit
bounds. An empty result SHALL be inconclusive.

#### Scenario: Bounded recognition query has no results

- **WHEN** an authorized query finds no catalogued recognition events in its
  requested window
- **THEN** it SHALL return a valid empty bounded result
- **AND** it SHALL not infer recognition success, failure or business traffic.
