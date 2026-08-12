## MODIFIED Requirements

### Requirement: Separate protocol surface

The system SHALL define `ProductRecognizerProtocol` in
`backend/recognizers/product_recognizer_contract.py` with a recognition method
that accepts the caller-provided catalog and an optional additive recognition
context, returning `ProductRecognizerResult`. The module SHALL not import
SQLAlchemy, HTTP, LLM, or repository modules and shall remain separate from
the concrete fuzzy implementation. The context may carry catalog scope and the
naturally owned commerce ID, but never authorizes catalog expansion. The
recognizer SHALL preserve the exact four-key result, candidate ordering, and
caller-owned transaction boundary.

#### Scenario: Protocol is importable without infrastructure

- **WHEN** a consumer imports `ProductRecognizerProtocol` and contract types
- **THEN** the import succeeds without database, HTTP, LLM, or repository dependencies

#### Scenario: Protocol uses the frozen shape

- **WHEN** an implementation is checked against the protocol
- **THEN** it accepts the caller-provided catalog and returns the exact four-key result contract

#### Scenario: Restricted pending catalog stays authoritative

- **WHEN** a pending product-selection caller invokes the shared protocol with
  its restricted catalog and context
- **THEN** any returned candidate belongs to that catalog
- **AND** the recognizer has not committed, rolled back, or flushed the caller session
