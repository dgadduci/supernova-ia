## Why

Phase 1 of the supernova-ia roadmap establishes the SQLAlchemy model layer that underpins the multi-commerce WhatsApp ordering system. This change covers **Subphase 1.1 — EstadoComercio**, the first reference-data model needed before any other entity that references a commerce status (active, suspended, etc.) can be defined. Without this baseline, subsequent subphases cannot model foreign-key relationships or generate Alembic migrations against the local `supernova` and `supernova_test` databases.

## What Changes

- Introduce a new SQLAlchemy model `EstadoComercio` in `backend/models/` with two columns:
  - `id`: integer primary key
  - `estado`: non-null string representing the commerce status
- The model becomes the reference (lookup) table for the status of each commerce.
- No API, service, or migration code is added in this change — those belong to later subphases.

## Capabilities

### New Capabilities

- `estado-comercio`: Defines the `EstadoComercio` SQLAlchemy model (`id`, `estado`) used as the reference table for commerce status. Each commerce will eventually reference one of these states.

### Modified Capabilities

_None._ No existing spec-level requirements change with this proposal.

## Impact

- **New code** under `backend/models/estado_comercio.py` (or similar purpose-specific module).
- **Project tooling**: a project-local Python `venv` and SQLAlchemy installation are prerequisites (assumed already available from earlier setup; this change does not create them).
- **Databases**: `supernova` (development) and `supernova_test` (testing) — both must contain the table once migrations are applied in a later subphase. No migration is generated here.
- **No API or schema exposure yet**; consumers of this model will land in later subphases.
