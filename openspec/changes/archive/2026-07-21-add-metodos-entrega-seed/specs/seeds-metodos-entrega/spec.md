# Capability: seeds-metodos-entrega

## Purpose

Define the seed operation that populates the `metodos_entrega` catalog table from a JSON data file, so that downstream tables (`comercio_metodos_entrega.id_metodo_entrega`, Subphase 1.9) have a usable parent set to attach to in both `supernova` and `supernova_test`.

## Requirements

### Requirement: Seed script loads metodos_entrega from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/metodos_entrega.json` and inserts the rows it contains into the `metodos_entrega` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty metodos_entrega table
- **WHEN** the script is run against a database whose `metodos_entrega` table is empty
- **THEN** every entry in the JSON file is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `metodos_entrega` table already contains every row's `codigo`
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the `codigo` value
The system SHALL determine whether a JSON entry already exists by comparing its `codigo` field against the `codigo` column of existing rows; entries with a matching `codigo` SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target table and others do not
- **THEN** only the missing entries are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
