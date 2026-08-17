# Capability: comercio

## Purpose

Define the `Comercio` SQLAlchemy model — the central entity of the multi-commerce WhatsApp ordering system. Each `Comercio` represents one business on the platform: it stores the business profile, the dispatch address, locale preferences, lifecycle timestamps, and a foreign-key reference to the `estado_comercio` lookup table that records its current status.
## Requirements
### Requirement: Comercio model definition
The system SHALL define a SQLAlchemy model named `Comercio` that exposes the column set required by Subphase 1.2: a primary-key integer `id`; business-profile fields (`nombre_fantasia`, `nombre_corto`, `razon_social`, `cuit`, `whatsapp`); address fields (`calle`, `numero`, `piso_departamento`, `localidad`, `provincia`, `codigo_postal`); a unique `slug`; a foreign-key `estado_id` referencing `estado_comercio.id` with a corresponding `estado` relationship; locale fields with defaults (`zona_horaria`, `moneda`, `idioma`); and lifecycle timestamps (`fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`).

#### Scenario: Comercio exposes the required column set
- **WHEN** the `Comercio` model is imported and its columns are inspected
- **THEN** it exposes `id` as an integer primary key with autoincrement
- **AND** it exposes `nombre_fantasia` (String ≤150, non-null), `nombre_corto` (String ≤80, non-null), `razon_social` (String ≤200, non-null), `cuit` (String ≤20, non-null, indexed), and `whatsapp` (String ≤30, non-null, unique, indexed)
- **AND** it exposes address columns `calle` (String ≤150, non-null), `numero` (String ≤20, non-null), `piso_departamento` (String ≤50, nullable), `localidad` (String ≤100, non-null), `provincia` (String ≤100, non-null), and `codigo_postal` (String ≤20, nullable)
- **AND** it exposes `slug` (String ≤150, non-null, unique, indexed)
- **AND** it exposes `zona_horaria` (String ≤100, non-null, default `"America/Argentina/Buenos_Aires"`), `moneda` (String ≤3, non-null, default `"ARS"`), and `idioma` (String ≤10, non-null, default `"es-AR"`)
- **AND** it exposes `fecha_alta` (timezone-aware DateTime, non-null, server-default `now()`), `fecha_ultima_modificacion` (timezone-aware DateTime, non-null, server-default `now()`, on-update `now()`), and `fecha_baja` (timezone-aware DateTime, nullable)

#### Scenario: Comercio references EstadoComercio via estado_id
- **WHEN** the `Comercio` model is imported and its columns and relationships are inspected
- **THEN** it exposes `estado_id` as a non-null integer ForeignKey to `estado_comercio.id`
- **AND** it exposes an `estado` relationship attribute that resolves to an `EstadoComercio` instance

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
