## ADDED Requirements

### Requirement: Seed prices from JSON
The system SHALL provide a runnable seed script that reads the price dataset and inserts one price for each referenced product-presentation into the database selected by `SUPERNOVA_DATABASE_URL`, defaulting to `supernova_test`.

#### Scenario: First run inserts missing prices
- **WHEN** every referenced product-presentation exists and has no price
- **THEN** the script inserts all dataset entries and reports the inserted count

### Requirement: Seed execution is idempotent
The system SHALL use `id_producto_presentacion` as the idempotency key and SHALL skip associations that already have a price without updating them.

#### Scenario: Re-run is a no-op
- **WHEN** every dataset entry already exists in the target table
- **THEN** the script inserts no rows and reports every entry as skipped

#### Scenario: Partial overlap inserts only missing prices
- **WHEN** only some referenced associations already have prices
- **THEN** only missing prices are inserted

### Requirement: Dataset reflects category pricing policy
The generated dataset SHALL assign category-appropriate values to every seeded product-presentation and SHALL preserve presentation-dependent relationships defined by the pricing policy.

#### Scenario: Generated dataset is validated
- **WHEN** the dataset is checked against the product, category, and presentation hierarchy
- **THEN** every entry satisfies its category range and any required presentation relationship

### Requirement: Seed validation is atomic
The script SHALL reject missing product-presentation references, invalid decimal scale, negative values, and values outside the model precision, rolling back the entire transaction.

#### Scenario: Invalid entry aborts the seed
- **WHEN** any JSON entry fails validation
- **THEN** the script raises `ValueError` and persists no rows from that invocation

### Requirement: Script targets one database per invocation
The script SHALL connect only to the database selected by `SUPERNOVA_DATABASE_URL` and SHALL default to `supernova_test` when unset.

#### Scenario: Operator selects production-like database
- **WHEN** the environment variable points to `supernova`
- **THEN** only `supernova` is seeded by that invocation
