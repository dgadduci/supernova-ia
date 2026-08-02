## Context

Subphase 2.1 (Comercios) and Subphase 2.2 (EstadoComercio) shipped the FastAPI infrastructure and the first two vertical slices. Subphase 2.3 is the third vertical slice, anchored on the `MediosPago` model. `MediosPago` is a flat catalog (no FK parent) used as the parent of the `comercio_medios_pago` join table (Subphase 1.10); the catalog must be reachable through HTTP before any future slice exposes payment-method references on other resources.

The Phase 2 General Rules apply unchanged (sync stack; `Router → Service → Repository → Model`; tests against `supernova_test` only; minimum tests required; no model changes; no Alembic migrations; one resource per subphase).

Constraints inherited from prior subphases:

- Per-request SQLAlchemy session via FastAPI dependency using `yield` (`backend/dependencies.py`).
- Pydantic `from_attributes=True` on response schemas for ORM serialization.
- Domain exceptions in the service layer; router translates to HTTP status codes.
- Repository never calls `commit()` / `rollback()`; service owns both.
- Integration tests override `get_session` via `app.dependency_overrides` against `supernova_test`.
- Pydantic `extra="forbid"` on Create schemas (introduced in Subphase 2.2) to reject undeclared fields at the schema layer.

## Goals / Non-Goals

**Goals:**

- Expose three CRUD endpoints over `MediosPago` (`GET /medios-pago`, `GET /medios-pago/{medio_pago_id}`, `POST /medios-pago`) under the same layering and exception-mapping patterns as Subphases 2.1 and 2.2.
- Add the minimum integration tests against `supernova_test` to cover the scenarios listed in `tasks.md`.
- Add a condensed Subphase 2.3 entry in `openspec/specs/project.md`, following `completed-subphase-context-condensation` from day one.

**Non-Goals:**

- Update, delete, pagination, authentication, nested-resource endpoints.
- Exposing `medio_pago` references inside `ComercioResponse` or any other resource response.
- Modifying the `MediosPago` model.
- Generating a new Alembic migration.
- Generic repositories, generic CRUD services, or any other abstraction that would anticipate other resources.

## Decisions

- **D1 — Three endpoints, no more.** `GET /medios-pago` (list ordered by id), `GET /medios-pago/{medio_pago_id}` (one, 404 if missing), `POST /medios-pago` (create, 201 on success, 409 on duplicate `codigo`). No update, no delete, no `activo` toggle — the seed already loads the canonical catalog rows (Subphase `seeds-medios-pago`); runtime mutation is out of scope for this slice.
- **D2 — `codigo` uniqueness enforced at the service layer and by the DB.** The model declares `unique=True` on `codigo`. The service calls `repo.get_by_codigo(...)` before insert and raises `DuplicateMedioPago` (mapped to HTTP 409) on collision. Mirrors the `estado` and `whatsapp`/`slug` patterns in prior subphases.
- **D3 — Two Pydantic schemas.** `MediosPagoCreate` (required `codigo` and `descripcion` text fields; `extra="forbid"` per D5) and `MediosPagoResponse` (full persisted column set with `from_attributes=True`).
- **D4 — Three repository methods.** `list_all`, `get_by_id`, `get_by_codigo`, `create`. Four methods. (Each prior slice picked its own count based on what the service needed; this is the minimum here.) No `medios_pago_in_use` lookup — there is no DB-level FK to `MediosPago` that would block a future delete; the join table `comercio_medios_pago.id_medio_pago` FK is `ON DELETE RESTRICT`, but no delete endpoint exists in this slice, so the lookup is unnecessary until that future subphase materializes.
- **D5 — `extra="forbid"` on `MediosPagoCreate`.** Carried over from Subphase 2.2 (where it caught a real bug: `id` in the request body was silently ignored). The `descripcion` field is open text; no format constraint beyond `min_length=1` after whitespace trim.
- **D6 — `activo` is request-side optional.** `MediosPagoCreate` accepts an optional `activo` (Boolean, default `True`); the model default is also `True`, so omitting `activo` in the request leaves the field at `True` server-side. Including `activo: false` is allowed so future operations can deactivate a medio de pago, but no dedicated endpoint is added for it.
- **D7 — Same file layout as prior Phase 2 subphases.** `routers/medios_pago.py`, `schemas/medios_pago.py`, `repositories/medios_pago_repository.py`, `services/medios_pago_service.py`. Two new domain exceptions extend the existing `backend/services/exceptions.py`.
- **D8 — Tests live alongside prior tests.** `backend/tests/api_smoke.py` grows with the new scenarios. No new test module; one suite keeps the dependency-override fixture and the isolation helpers in one place.
- **D9 — `project.md` Subphase 2.3 entry condensed per `completed-subphase-context-condensation` from day one.** Mirrors the pattern used for Subphase 2.2.

**Alternatives considered:**

- Default `activo=True` server-side only (omit from request schema): rejected — explicit client control of the boolean is closer to the model contract; clients that want the default simply omit the field.
- `codigo` uppercase normalization (analogous to `estado` candidates considered in Subphase 2.2 design): rejected — the model does not store `codigo` in any normalized form; the existing seed rows use mixed case conventions in `descripcion` but uppercase snake_case in `codigo`. Adding normalization here would require a model change or a service-level rule; out of scope for this slice.

## Risks / Trade-offs

- **[Risk] `descripcion` has no format constraint.** → Mitigation: `min_length=1` after whitespace trim is the only contract; future subphases can add format validation if business rules emerge.
- **[Trade-off] No `medios_pago_in_use` repository method.** Acceptable — there is no current caller; the join table FK is `ON DELETE RESTRICT` and the DB itself enforces the restriction when a delete endpoint eventually arrives.
- **[Trade-off] `activo` mutation is not exposed.** Acceptable — runtime mutation is out of scope for this slice; the model default + seed scripts cover the current need.

## Migration Plan

Not applicable. No Alembic migration is generated by this change. The `medios_pago` table already exists from the initial Alembic migration (`7f9610191db8`).

## Open Questions

- None for this subphase. Future subphases (e.g., nested `medio_pago` reads inside `ComercioResponse`, an update endpoint) inherit the same layering and exception-mapping patterns established here.
