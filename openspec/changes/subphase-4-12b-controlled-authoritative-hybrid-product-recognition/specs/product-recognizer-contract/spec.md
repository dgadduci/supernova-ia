## MODIFIED Requirements

### Requirement: Shared protocol preserves scoped caller contracts

Every implementation of `ProductRecognizerProtocol` SHALL accept the existing
caller-supplied catalog and optional recognition context without changing the
four-key result contract, candidate ordering, or preserved catalog fields.
The context may identify a restricted pending-product-selection catalog; it
shall not authorize expansion of that catalog. The recognizer is a pure
decision collaborator with respect to caller transactions.

#### Scenario: Restricted pending catalog stays authoritative

- **WHEN** a pending product-selection caller invokes the shared protocol with
  its restricted catalog and context
- **THEN** any returned candidate belongs to that catalog
- **AND** the recognizer has not committed, rolled back, or flushed the caller
  session
