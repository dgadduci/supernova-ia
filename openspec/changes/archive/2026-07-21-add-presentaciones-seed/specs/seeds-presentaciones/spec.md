# Capability: seeds-presentaciones

## Purpose

Define the seed operation that populates the `presentaciones` table from a JSON data file, so that downstream code (`producto_presentaciones.id_presentacion`, Subphase 1.7) has a usable parent set to attach products to in both `supernova` and `supernova_test`.

## Requirements

### Requirement: Seed script loads presentaciones from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/presentaciones.json` and inserts the rows it contains into the `presentaciones` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty presentaciones table
- **WHEN** the script is run against a database whose `presentaciones` table is empty and whose `comercios` table already contains the rows referenced by the JSON
- **THEN** every entry in the JSON file is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `presentaciones` table already contains every JSON row's `(id_comercio, codigo)` pair
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the composite `(id_comercio, codigo)` pair
The system SHALL determine whether a JSON entry already exists by resolving the comercio reference to its id and comparing the `(id_comercio, codigo)` pair against existing rows; entries whose pair is already present SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target table and others do not
- **THEN** only the missing pairs are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: Parent reference resolved at insert time
The system SHALL look up `id_comercio` for each row by matching the JSON's `comercio_cuit` against the `cuit` column of `comercios`, instead of hardcoding the parent id.

#### Scenario: Same JSON seeds both DBs without modification
- **WHEN** the same JSON is used to seed `supernova_test` and `supernova`
- **THEN** both databases end up with the same logical set of presentation rows
- **AND** the inserted `id_comercio` values differ between the two DBs where the `comercios` autoincrement history differs

#### Scenario: Unknown business key fails loudly
- **WHEN** the JSON contains a `comercio_cuit` value that does not exist in the `comercios` table of the target database
- **THEN** the script raises an error and inserts no rows

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
