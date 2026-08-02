## Why

`ProductSelectionContextResolver` currently owns a SQLAlchemy query and database session, violating the project's internal layering rule and making the context resolver harder to test as a pure decision component. Subphase 3.14 separates catalog loading from selection resolution so database access belongs to repositories and services while the resolver remains reusable and side-effect free.

## What Changes

- Move candidate-restricted product-presentation loading out of `ProductSelectionContextResolver`.
- Reuse or extend the existing product repository and service with the minimum method needed to load candidate presentations and eager-load product, presentation, and category data.
- Change the context resolver to accept an already-built restricted recognizer catalog.
- Add a thin orchestration service that loads the catalog through the service and invokes the pure resolver.
- Preserve the exact 12-field recognizer catalog contract, candidate filtering, quantity preservation, selection validation, and result behavior.
- Add tests for repository filtering, service catalog construction, resolver purity, and real recognizer orchestration.

## Capabilities

### New Capabilities
- `product-selection-context-orchestration`: Defines the service boundary between database-backed catalog loading and pure product selection resolution.

### Modified Capabilities
- `product-selection-context-resolver-3-12`: Change the resolver API and purity requirements so it receives a restricted catalog instead of a database session.

## Impact

- `backend/intents/context/product_selection_context_resolver.py`
- Existing product repository/service modules under `backend/repositories/` and `backend/services/`
- New orchestration service under the appropriate existing intent/service layer
- Resolver and integration tests in `backend/tests/api_smoke.py`
- OpenSpec capability specs and project roadmap
- No database schema, recognizer fuzzy logic, handler, persistence, or external dependency changes.
