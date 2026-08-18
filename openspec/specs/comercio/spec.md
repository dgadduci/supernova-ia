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

### Requirement: Commerce stores its own trial limits

A `Comercio` SHALL store nullable timezone-aware `prueba_hasta`, nullable
positive `prueba_max_pedidos`, and non-negative
`prueba_pedidos_consumidos`. Deadline and maximum SHALL be present when its
state mode is PRUEBA. Consumption belongs to the commerce, not to the shared
state row.

#### Scenario: Entering a trial initializes consumption

- **WHEN** an operator changes a non-trial commerce to PRUEBA with valid
  deadline and quota
- **THEN** the configuration is persisted atomically
- **AND** `prueba_pedidos_consumidos` becomes zero

#### Scenario: Editing active trial limits preserves consumption

- **WHEN** an operator changes deadline and/or quota of a commerce already in
  PRUEBA
- **THEN** the new limits are persisted atomically
- **AND** its existing consumed counter is unchanged

### Requirement: Availability is centralized and fail-closed

The system SHALL evaluate a commerce through one typed availability policy.
HABILITADO is available; BLOQUEADO, missing, and legacy states are unavailable;
PRUEBA is available only before its deadline and below its quota.

#### Scenario: Trial expiration wins over unused quota

- **WHEN** current time is at or after `prueba_hasta` and consumption remains
  below the configured maximum
- **THEN** the commerce is unavailable

#### Scenario: Trial quota exhaustion wins before deadline

- **WHEN** consumption equals the configured maximum before `prueba_hasta`
- **THEN** the commerce is unavailable
