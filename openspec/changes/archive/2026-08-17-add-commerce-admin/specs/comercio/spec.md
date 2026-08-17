## ADDED Requirements

### Requirement: Update permitted commerce profile fields atomically

The system SHALL provide a typed update operation for one exact `Comercio`
that may modify business profile, address, `estado_id`, `zona_horaria`,
`moneda`, and `idioma`. It SHALL validate normalized required text and the
exact selected `EstadoComercio`, commit atomically, and roll back on failure.
It SHALL NOT mutate `whatsapp`, `slug`, channels, orders, flavor, catalog,
or commerce associations.

#### Scenario: Valid profile update preserves routing identity and relations

- **WHEN** an operator updates permitted profile fields of commerce A
- **THEN** only those scalar fields of A are persisted
- **AND** A's `whatsapp` and `slug` retain their prior values
- **AND** A's flavor, catalog, payment/delivery associations, orders, and
  channel-routing state remain unchanged

#### Scenario: Invalid or failed update is atomic

- **WHEN** the update has invalid normalized data, unknown status/commerce, or
  a persistence failure
- **THEN** the prior commerce row remains unchanged
- **AND** no related row is modified
- **AND** a failed persistence transaction is rolled back
