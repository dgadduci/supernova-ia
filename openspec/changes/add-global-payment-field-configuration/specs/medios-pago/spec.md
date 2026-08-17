## ADDED Requirements

### Requirement: Global availability of commerce payment details

The `MediosPago` catalog SHALL expose non-null Boolean fields
`habilita_titular` and `habilita_alias`, each defaulting to `false` at both
the ORM and database levels. Each field SHALL mean that a future
commerce-specific configuration form may edit the corresponding value on its
`ComercioMedioPago` association; it SHALL NOT make that value required.

#### Scenario: Existing payment methods receive safe defaults

- **WHEN** the schema migration is applied to a database containing existing
  `medios_pago` rows
- **THEN** every existing row has `habilita_titular = false` and
  `habilita_alias = false`
- **AND** no `comercio_medios_pago` or `pedidos` row is changed

#### Scenario: A method can independently allow alias only

- **WHEN** an administrator sets `habilita_alias = true` and
  `habilita_titular = false` on a payment method
- **THEN** the persisted global method exposes exactly those values
- **AND** a later commerce form may permit alias input but not titular input

#### Scenario: Disabling a field preserves per-commerce data

- **WHEN** a global method changes either availability field from `true` to
  `false`
- **THEN** no existing `ComercioMedioPago.titular` or `.alias` value is
  deleted or altered

### Requirement: Global payment configuration remains separate from commerce values

The global `MediosPago` catalog SHALL NOT store a concrete `titular` or
`alias` value. Those values SHALL remain owned by `ComercioMedioPago`, so two
commerces using the same global method may retain different payment details.

#### Scenario: Two commerces retain distinct transfer aliases

- **WHEN** two `ComercioMedioPago` associations reference the same global
  payment method
- **THEN** each association may retain an independent alias value
- **AND** changing either global availability flag does not copy either value
  between the associations
