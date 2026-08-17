## ADDED Requirements

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
