# Capability: seeds-comercios

## Purpose

Define the seed operation that populates the `comercios` table from a JSON data file, so that downstream tables (`comercio_metodos_entrega`, `comercio_medios_pago`, `categoria_producto`, `presentacion`) — all of which FK to `comercios.id` — have a usable parent set to attach to in both `supernova` and `supernova_test`.

## Requirements

### Requirement: Seed script loads comercios from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/comercio.json` and inserts the rows it contains into the `comercios` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty comercios table
- **WHEN** the script is run against a database whose `comercios` table is empty
- **THEN** every entry in the JSON file is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `comercios` table already contains every row's `cuit`
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the `cuit` value
The system SHALL determine whether a JSON entry already exists by comparing its `cuit` field against the `cuit` column of existing rows; entries with a matching CUIT SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target table and others do not
- **THEN** only the missing entries are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: Estado is referenced by code, resolved at insert time
The system SHALL look up the `estado_id` foreign key for each row by matching the JSON's `estado_codigo` field against the `estado` column of the live `estado_comercio` table in the target database, instead of hardcoding `estado_id` values.

#### Scenario: Same JSON seeds both DBs without modification
- **WHEN** the same JSON is used to seed `supernova_test` and `supernova`
- **THEN** both databases end up with the same logical set of comercios
- **AND** the `estado_id` values written differ between the two DBs if their `estado_comercio` id sequences differ

#### Scenario: Unknown estado_codigo fails loudly
- **WHEN** the JSON contains an `estado_codigo` value that does not exist in the target database's `estado_comercio` table
- **THEN** the script raises an error and inserts no rows

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
