# Capability: seeds-productos

## Purpose

Define the seed operation that populates the `productos` table from a JSON data file, so that downstream code (`producto_presentaciones.id_producto`, Subphase 1.7; `producto_precios.id_producto_presentacion`, Subphase 1.8) has a usable catalog set to attach to in both `supernova` and `supernova_test`.

## Requirements

### Requirement: Seed script loads productos from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/productos.json` and inserts the rows it contains into the `productos` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty productos table
- **WHEN** the script is run against a database whose `productos` table is empty and whose `comercios` and `categorias_productos` tables already contain the rows referenced by the JSON
- **THEN** every entry in the JSON file is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `productos` table already contains every JSON row's `(id_categoria_producto, nombre)` pair
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the composite `(id_categoria_producto, nombre)` pair
The system SHALL determine whether a JSON entry already exists by resolving both parent references to ids and comparing the composite pair against existing rows; entries whose pair is already present SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target table and others do not
- **THEN** only the missing pairs are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: Parent references resolved at insert time
The system SHALL look up `id_categoria_producto` for each row by first matching the JSON's `comercio_cuit` against the `cuit` column of `comercios`, then matching `categoria_descripcion` (case-insensitively, lower-folded on both sides) against the `descripcion` column of `categorias_productos` for that comercio, instead of hardcoding the parent id.

#### Scenario: Same JSON seeds both DBs without modification
- **WHEN** the same JSON is used to seed `supernova_test` and `supernova`
- **THEN** both databases end up with the same logical set of product rows
- **AND** the inserted `id_categoria_producto` values differ between the two DBs where the parent autoincrement histories differ

#### Scenario: Unknown business key fails loudly
- **WHEN** the JSON contains a `comercio_cuit` value that does not exist in `comercios`, or a `categoria_descripcion` that does not exist (case-insensitively) for that comercio in `categorias_productos`
- **THEN** the script raises an error and inserts no rows

### Requirement: Catalog lives in a separate reference file
The system SHALL source product names and descriptions from `backend/db/seeds/data/prod_json.json` at `productos.json` generation time, leaving that file unchanged by the seed script.

#### Scenario: Catalog edit requires explicit regeneration
- **WHEN** `prod_json.json` is edited to add or rename a product
- **THEN** the change does NOT affect the database until `productos.json` is regenerated and the seed is re-run
- **AND** the regeneration produces a fresh cross-reference between the updated catalog and each comercio's categories

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
