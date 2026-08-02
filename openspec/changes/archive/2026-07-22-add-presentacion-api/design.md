## Context

Subphases 2.1 through 2.5 established synchronous FastAPI slices and nested commerce ownership using `Router → Service → Repository → Model`. Subphase 2.6 applies that pattern to `Presentacion`, a commerce-owned catalog whose rows will later participate in `ProductoPresentacion` associations.

`Presentacion` has commerce-scoped unique constraints on `codigo` and `descripcion`, defaulted `activo=True` and `orden=0`, and a deferred product-presentation relationship. The API must enforce those uniqueness rules case-insensitively at the service layer while leaving the model and schema unchanged.

## Goals / Non-Goals

**Goals:**

- List presentations owned by an existing commerce, ordered by `orden` then `id`.
- Retrieve one presentation by ID without exposing product associations.
- Create a presentation under a commerce with normalized code, trimmed description, scoped duplicate checks, and preserved defaults.
- Preserve existing layering, exception translation, transaction, and integration-test conventions.
- Condense the completed Subphase 2.6 project entry.

**Non-Goals:**

- Update, delete, activation/deactivation, pagination, or authentication.
- Product or product-presentation association endpoints and automatic association creation.
- Changes to `Presentacion`, `Comercio`, or database schema.
- Generic repository or CRUD abstractions.

## Decisions

- **D1 — Use nested list/create and direct retrieval routes.** Commerce ownership is mandatory for listing and creation, so those operations use `/comercios/{comercio_id}/presentaciones`; globally unique presentation IDs support `/presentaciones/{presentacion_id}` for retrieval.
- **D2 — Derive ownership from the path.** The create schema omits `id_comercio` and forbids extra fields, preventing request-body ownership overrides.
- **D3 — Normalize code and compare duplicates case-insensitively.** The service trims and lowercases `codigo`, then checks scoped code and description lookups before creation. Duplicate code and description exceptions both map to 409; identical values in another commerce are allowed.
- **D4 — Preserve optional model defaults.** Omitted `activo` and `orden` are passed as unset to the repository so SQLAlchemy applies `True` and `0`; explicit values are retained.
- **D5 — Keep responsibility boundaries stable.** The repository performs scoped queries and creation without transactions or relationship loading. The service validates, commits, and rolls back. Routers only map domain exceptions.
- **D6 — Reuse the existing integration suite.** Tests extend `backend/tests/api_smoke.py` against `supernova_test`, covering scoped uniqueness, ownership isolation, defaults, validation, retrieval, listing, and rollback.

## Risks / Trade-offs

- **[Risk] Application-level duplicate checks can race.** → The existing database unique constraints remain the final guard; service transactions roll back failures.
- **[Risk] Normalized code differs from the client’s original casing.** → This is explicit API behavior and makes case-insensitive uniqueness deterministic.
- **[Trade-off] Product associations are not visible yet.** → Association behavior belongs to a later product-presentation subphase.
