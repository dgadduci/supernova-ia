## ADDED Requirements

### Requirement: EstadoComercio model definition
The system SHALL define a SQLAlchemy model named `EstadoComercio` that exposes a primary-key integer column `id` and a non-null string column `estado`.

#### Scenario: EstadoComercio exposes the required columns
- **WHEN** the `EstadoComercio` model is imported and its columns are inspected
- **THEN** it exposes a column named `id` of integer type that is the table primary key
- **AND** it exposes a non-null column named `estado` of string type
