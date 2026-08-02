## Why

Subphase 2.9 needs a single read-only endpoint that returns the complete operational configuration of a commerce, including its status and configured payment and delivery methods. This avoids multiple client round trips while preserving the existing domain model and excluding product-catalog data.

## What Changes

- Add nested response schemas for complete commerce configuration.
- Add an eager-loading repository query that avoids N+1 access.
- Add a read-only service and `GET /comercios/{comercio_id}/configuracion` endpoint.
- Include commerce scalar fields, status, payment associations with catalog records, and delivery associations with catalog records.
- Add integration coverage against `supernova_test`.
- Mark and condense Subphase 2.9 in `openspec/specs/project.md` after implementation.

## Capabilities

### New Capabilities
- `comercio-configuracion-api`: Read the complete non-product configuration of a commerce in one structured response.

### Modified Capabilities

- None.

## Impact

- Adds schema, repository, service, and router modules for commerce configuration.
- Updates router registration, API smoke tests, and the project subphase summary.
- No model changes, migrations, writes, authentication, or product-related data access.
