# Capability: controlled-railway-calibration-identity

## Purpose

Make the frozen product-recognition calibration semantics portable to the
controlled Railway fixture catalog without treating historical database primary
keys as portable business identity.

## ADDED Requirements

### Requirement: Explicit logical identity manifest

The system SHALL define a versioned, explicit manifest mapping every dynamic
calibration reference to one stable controlled-fixture business identity:
fixture commerce, category, product and presentation. The manifest SHALL cover
every expected, allowed, restricted and symbolic seed reference used by a
`commerce_dynamic_database` case. It SHALL not infer identity from customer
text or from numeric primary-key position.

#### Scenario: A historical candidate ID is resolved portably

- **WHEN** a dynamic case carries a historical candidate ID
- **THEN** the adapter resolves its documented logical token to exactly one
  active fixture `producto_presentacion` in the case commerce
- **AND** it uses that runtime ID only in the in-memory execution copy

The manifest SHALL omit no semantic distinction by substitution: when the
controlled fixture lacks the exact commerce, category, canonical product or
presentation, resolution SHALL fail closed. Extending fixture coverage is a
separate change and SHALL NOT be achieved by aliases, nearest matches,
round-robin assignment or cross-category mapping.


The adaptation SHALL run only when explicitly selected for the controlled
fixture catalog. It SHALL query only, shall not control transactions, and
shall fail before embeddings or vector search if a mapping is missing,
ambiguous, inactive, cross-commerce or inconsistent with candidate boundaries.

#### Scenario: Cross-commerce mapping is rejected

- **WHEN** a resolved candidate belongs to a commerce other than the case
  commerce
- **THEN** calibration stops with a typed safe alignment error
- **AND** no embedding/vector call and no database mutation occurs

### Requirement: Frozen source semantics are preserved

The adapter SHALL not modify the source dataset file or alter case text,
expected decision, expected logical target, candidate ordering, candidate
boundary, category or eligibility policy. It SHALL report a separate execution
fingerprint for the materialized runtime-ID copy and preserve the source
dataset version/fingerprint for audit.

#### Scenario: Materialization preserves a restricted boundary

- **WHEN** a restricted dynamic case is materialized for the fixture catalog
- **THEN** its runtime candidate IDs retain the source ordering and disjoint
  allowed/restricted boundary
- **AND** no candidate outside the resolved allowed set is passed to vector
  search
