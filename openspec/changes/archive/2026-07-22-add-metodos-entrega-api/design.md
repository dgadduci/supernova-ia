## Context

Subphases 2.1 through 2.3 established the synchronous FastAPI infrastructure and three resource slices using `Router → Service → Repository → Model`. Subphase 2.4 applies that stable pattern to the existing `MetodosEntrega` catalog, whose rows contain a unique `codigo`, required `descripcion`, non-negative `orden`, `activo`, and database-managed lifecycle timestamps.

The Phase 2 constraints remain unchanged: per-request SQLAlchemy sessions, integration tests against `supernova_test`, domain exceptions translated by routers, service-owned transactions, no model changes, no migration, and one resource per subphase.

## Goals / Non-Goals

**Goals:**

- Expose list, retrieve-by-id, and create operations for `MetodosEntrega`.
- Validate and normalize create payloads consistently with prior catalog slices.
- Preserve the established layering, transaction ownership, and exception translation patterns.
- Add minimum integration coverage and condense the completed Subphase 2.4 entry in `project.md`.

**Non-Goals:**

- Update, delete, activation/deactivation, pagination, or authentication.
- Commerce-to-delivery-method association endpoints.
- Changes to the `MetodosEntrega` SQLAlchemy model or database schema.
- Generic repository or CRUD abstractions.

## Decisions

- **D1 — Implement exactly three endpoints.** `GET /metodos-entrega` lists rows ordered by `id`; `GET /metodos-entrega/{metodo_entrega_id}` returns one row or 404; `POST /metodos-entrega` creates one row and returns 201.
- **D2 — Mirror the MediosPago catalog slice.** The implementation uses `routers/metodos_entrega.py`, `schemas/metodo_entrega.py`, `repositories/metodo_entrega_repository.py`, and `services/metodo_entrega_service.py`, with router registration in `backend/main.py` and shared exceptions in `backend/services/exceptions.py`. A generic catalog abstraction is rejected because the project rules prohibit anticipatory abstractions.
- **D3 — Validate all client-owned columns.** `MetodoEntregaCreate` requires `codigo`, `descripcion`, and non-negative `orden`; `activo` is optional and defaults to `True`. It forbids undeclared fields. The service trims text and rejects values that become empty.
- **D4 — Enforce duplicate codigo consistently.** The repository provides `get_by_codigo`; the service checks it before insertion and raises a domain duplicate exception mapped to 409. The database unique constraint remains the final integrity guard.
- **D5 — Keep transaction ownership in the service.** The repository performs queries and `add`/`flush` work only. The service commits successful creation and rolls back database failures.
- **D6 — Return the complete persisted representation.** The response schema uses `from_attributes=True` and includes `id`, `codigo`, `descripcion`, `orden`, `activo`, `fecha_alta`, and `fecha_ultima_modificacion`.
- **D7 — Extend the existing integration suite.** Tests remain in `backend/tests/api_smoke.py` so they reuse the current dependency override and database isolation infrastructure.

## Risks / Trade-offs

- **[Risk] A concurrent duplicate insert can pass the pre-insert lookup.** → The database unique constraint rejects the second insert; the service rolls back and the router returns the established conflict response when identifiable as a duplicate.
- **[Risk] Negative order values violate a database check constraint.** → Validate `orden >= 0` in the request schema so invalid input is rejected before persistence.
- **[Trade-off] No runtime mutation beyond creation.** → This is intentional for Subphase 2.4; update, delete, and activation operations remain out of scope.
