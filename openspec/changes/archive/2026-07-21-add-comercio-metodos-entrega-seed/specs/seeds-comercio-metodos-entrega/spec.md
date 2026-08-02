# Capability: seeds-comercio-metodos-entrega

## Purpose

Define the seed operation that populates the `comercio_metodos_entrega` join table from a JSON data file, so that downstream code can answer "which métodos de entrega does this comercio offer?" against a non-empty join set in both `supernova` and `supernova_test`.

## Requirements

### Requirement: Seed script loads comercio_metodos_entrega from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/comercio_metodos_entrega.json` and inserts the rows it contains into the `comercio_metodos_entrega` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty join table
- **WHEN** the script is run against a database whose `comercio_metodos_entrega` table is empty and whose parent catalogs (`comercios`, `metodos_entrega`) already contain the rows referenced by the JSON
- **THEN** every entry in the JSON file is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `comercio_metodos_entrega` table already contains every JSON row's composite `(id_comercio, id_metodo_entrega)` pair
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the composite `(id_comercio, id_metodo_entrega)` pair
The system SHALL determine whether a JSON entry already exists by resolving both parent references to ids and comparing the composite pair against existing rows; entries whose composite pair is already present SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target join table and others do not
- **THEN** only the missing pairs are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: Parent references resolved at insert time
The system SHALL look up `id_comercio` and `id_metodo_entrega` for each row by matching the JSON's `comercio_cuit` against the `cuit` column of `comercios` and the JSON's `metodo_entrega_codigo` against the `codigo` column of `metodos_entrega`, instead of hardcoding parent ids.

#### Scenario: Same JSON seeds both DBs without modification
- **WHEN** the same JSON is used to seed `supernova_test` and `supernova`
- **THEN** both databases end up with the same logical set of join rows
- **AND** the inserted `id_comercio` and `id_metodo_entrega` values differ between the two DBs where their parent autoincrement histories differ

#### Scenario: Unknown business key fails loudly
- **WHEN** the JSON contains a `comercio_cuit` or `metodo_entrega_codigo` value that does not exist in the corresponding parent table of the target database
- **THEN** the script raises an error and inserts no rows

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
