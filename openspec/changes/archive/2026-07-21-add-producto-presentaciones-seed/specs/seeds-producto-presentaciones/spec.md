# Capability: seeds-producto-presentaciones

## Purpose

Define the seed operation that populates the `producto_presentaciones` join table from a JSON data file, so that downstream code (`producto_precios.id_producto_presentacion`, Subphase 1.8) has a usable parent set to attach prices to in both `supernova` and `supernova_test`. The join enforces a four-way data-integrity invariant: every row must reference a comercio, a categoria, a producto, and a presentacion that all belong to the same comercio.

## Requirements

### Requirement: Seed script loads producto_presentaciones from JSON
The system SHALL provide a runnable script that reads `backend/db/seeds/data/producto_presentaciones.json` and inserts the rows it contains into the `producto_presentaciones` table of the database selected by the `SUPERNOVA_DATABASE_URL` environment variable, defaulting to `supernova_test` when the variable is unset.

#### Scenario: First run against an empty join table
- **WHEN** the script is run against a database whose `producto_presentaciones` table is empty and whose `comercios`, `categorias_productos`, `productos`, and `presentaciones` tables already contain the rows referenced by the JSON
- **THEN** every entry in the JSON file whose four references resolve cleanly is inserted
- **AND** the script reports `inserted=<N> skipped=0` where `<N>` is the JSON row count

#### Scenario: Re-run against an already-seeded table is a no-op
- **WHEN** the script is run a second time against a database whose `producto_presentaciones` table already contains every JSON row's composite `(id_producto, id_presentacion)` pair
- **THEN** no new rows are inserted
- **AND** the script reports `inserted=0 skipped=<N>`

### Requirement: Idempotency key is the composite `(id_producto, id_presentacion)` pair
The system SHALL determine whether a JSON entry already exists by resolving both parent references to ids and comparing the composite pair against existing rows; entries whose composite pair is already present SHALL be skipped.

#### Scenario: Partial overlap is handled correctly
- **WHEN** some JSON entries already exist in the target join table and others do not
- **THEN** only the missing pairs are inserted
- **AND** the script reports `inserted=<missing>` and `skipped=<already-present>`

### Requirement: All four parent references resolved at insert time, scoped to one comercio
The system SHALL look up, for each row: `id_comercio` from `comercio_cuit`; `id_categoria_producto` from the categoria that belongs to that comercio and matches the JSON's `categoria_descripcion` (case-insensitive); `id_producto` from the product that belongs to that categoria and matches the JSON's `producto_nombre`; and `id_presentacion` from the presentation that belongs to that comercio and matches the JSON's `presentacion_codigo`.

#### Scenario: All references resolve to the same comercio
- **WHEN** all four business keys map to rows that share one `comercio_id`
- **THEN** the row is eligible for insertion

#### Scenario: Any reference fails to resolve
- **WHEN** any of the four business keys does not map to a row in the target comercio's hierarchy
- **THEN** the script raises a `ValueError` naming the offending key and inserts no rows (the transaction is rolled back)

#### Scenario: Product belongs to a different comercio than the row's `comercio_cuit`
- **WHEN** the JSON's `producto_nombre` resolves to a product whose categoria belongs to a different comercio than the one named by `comercio_cuit`
- **THEN** the script raises a `ValueError` and inserts no rows

#### Scenario: Presentation belongs to a different comercio than the row's `comercio_cuit`
- **WHEN** the JSON's `presentacion_codigo` resolves to a presentation owned by a different comercio than the one named by `comercio_cuit`
- **THEN** the script raises a `ValueError` and inserts no rows

### Requirement: Per-category presentation policy lives in the generator
The system SHALL source the per-category presentation mapping (which presentation codigos apply to which categoria) from the JSON-generation step, not from the script. The script is policy-free.

#### Scenario: Catalog edit requires explicit regeneration
- **WHEN** `prod_json.json` is edited to add or rename a product, or the presentation policy changes
- **THEN** the change does NOT affect the database until `producto_presentaciones.json` is regenerated and the seed is re-run

### Requirement: Script targets one DB per invocation
The system SHALL NOT connect to multiple databases in a single invocation; the operator selects the target by setting `SUPERNOVA_DATABASE_URL` before running the script.

#### Scenario: Default target when env var is unset
- **WHEN** the script is run without `SUPERNOVA_DATABASE_URL` set
- **THEN** it connects to `postgresql+psycopg:///supernova_test`
