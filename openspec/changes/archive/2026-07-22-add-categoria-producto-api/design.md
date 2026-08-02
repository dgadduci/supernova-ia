## Context

Subphases 2.1 through 2.4 established synchronous FastAPI slices for commerce and global catalogs using `Router → Service → Repository → Model`. Subphase 2.5 applies that pattern to `CategoriaProducto`, the first commerce-owned child resource exposed through nested commerce routes.

`CategoriaProducto` stores `id_comercio`, required `descripcion`, defaulted `activo=True` and `orden=0`, lifecycle timestamps, and a deferred products relationship. The API must enforce commerce ownership from the path while excluding products and preserving model defaults.

## Goals / Non-Goals

**Goals:**

- List categories belonging to an existing commerce, ordered by `orden` and then `id`.
- Retrieve one category by its global category ID.
- Create a category under the commerce identified by the route.
- Preserve established validation, exception translation, transaction ownership, and integration-test patterns.
- Condense the completed Subphase 2.5 project entry after implementation.

**Non-Goals:**

- Update, delete, activation/deactivation, pagination, or authentication.
- Product endpoints, nested products, or automatic product creation.
- Duplicate-description enforcement.
- Changes to `CategoriaProducto`, `Comercio`, or the database schema.
- Generic repository or CRUD abstractions.

## Decisions

- **D1 — Use two nested commerce routes and one direct category route.** Listing and creation use `/comercios/{comercio_id}/categorias-productos` because commerce ownership is mandatory; retrieval uses `/categorias-productos/{categoria_producto_id}` because category IDs are globally unique.
- **D2 — Verify commerce existence before nested operations.** The repository checks `Comercio` by ID. The service raises the existing `ComercioNotFound` exception when absent, producing 404 for both list and create operations. Returning an empty list is reserved for an existing commerce with no categories.
- **D3 — Derive ownership exclusively from the path.** `CategoriaProductoCreate` omits `id_comercio` and forbids extra fields, preventing request bodies from overriding route ownership.
- **D4 — Preserve optional model defaults deliberately.** Create accepts required `descripcion` plus optional `activo` and `orden`. The service and repository omit optional values when absent so SQLAlchemy applies `True` and `0`; explicit values, including `activo=False`, are preserved.
- **D5 — Validate at schema and service boundaries.** Pydantic enforces maximum description length and non-negative supplied `orden`; the service trims `descripcion` and raises an invalid-category domain exception when it becomes empty.
- **D6 — Do not add duplicate-description handling.** The model defines no corresponding uniqueness constraint, and duplicate descriptions may be meaningful within a commerce.
- **D7 — Keep query and transaction ownership consistent.** The repository verifies commerce existence, lists, retrieves, and creates without commit/rollback. The service commits successful creation and rolls back failures. Routers only translate domain exceptions.
- **D8 — Reuse the existing integration suite.** Tests extend `backend/tests/api_smoke.py` against `supernova_test`, covering ownership isolation, ordering, defaults, validation, 404 cases, and rollback.

## Risks / Trade-offs

- **[Risk] Optional values can accidentally bypass model defaults if passed as `None`.** → Use unset-aware payload handling and omit absent optional fields from model construction.
- **[Risk] Category retrieval is not nested under commerce.** → Category IDs are globally unique, and the specified direct route intentionally returns the owning `id_comercio` without loading products.
- **[Trade-off] Duplicate descriptions are allowed.** → This matches the current model and explicit Subphase 2.5 scope; a future requirement can add a constraint and conflict behavior.
- **[Trade-off] The integration suite remains a single growing file.** → This follows the established Phase 2 test-fixture reuse pattern and avoids premature test abstractions.
