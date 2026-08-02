# Capability: seeds-estado-comercio

## Purpose

Define the seed operation that populates the `estado_comercio` table from a JSON data file, so that the `Comercio.estado_id` FK (Subphase 1.2) can be satisfied when any future code creates a `Comercio` row.

## Requirements

### Requirement: Seed script loads estado_comercio from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/estados.json` and inserts the rows it contains into the `estado_comercio` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty estado_comercio table
- **WHEN** the script is run against a database whose `estado_comercio` table is empty
- **THEN** every entry in the JSON file is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `estado_comercio` table already contains every value in the JSON file
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the `estado` value
The system SHALL determine whether a JSON entry already exists by comparing its `estado` field against the `estado` column of existing rows; entries with a matching value SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target table and others do not
- **THEN** only the missing entries are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
