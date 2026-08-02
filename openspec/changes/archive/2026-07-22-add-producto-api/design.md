## Context

Subphases 2.1 through 2.6 established synchronous FastAPI slices, nested commerce-owned resources, and consistent `Router → Service → Repository → Model` boundaries. Subphase 2.7 applies those patterns to `Producto`, which belongs to `CategoriaProducto` and is indirectly owned by a commerce.

`Producto` has category-scoped name uniqueness, optional description, defaulted `activo=True`, `disponible=True`, and `orden=0`, plus deferred presentation relationships. This slice must support both category and commerce listings without loading category or presentation relationships into responses.

## Goals / Non-Goals

**Goals:**

- List products by category and by commerce with the specified stable ordering.
- Retrieve one product by ID.
- Create a product under a route-derived category with scoped duplicate-name checks and preserved defaults.
- Normalize optional descriptions and enforce ownership without exposing relationships.
- Preserve established exception, transaction, and integration-test conventions.

**Non-Goals:**

- Update, delete, availability mutations, pagination, or authentication.
- Presentation associations, presentation data, or prices.
- Changes to `Producto`, `CategoriaProducto`, `Comercio`, or database schema.
- Generic repository or CRUD abstractions.

## Decisions

- **D1 — Four routes reflect two ownership views.** Category listing and creation use `/categorias-productos/{categoria_producto_id}/productos`; commerce listing joins products through categories; direct retrieval uses `/productos/{producto_id}`.
- **D2 — Commerce listing uses an explicit SQL join and scalar product selection.** Joining `Producto` to `CategoriaProducto` supports commerce filtering and ordering by category `orden`, product `orden`, and product `id` without eager-loading category details.
- **D3 — Derive category ownership exclusively from the path.** `ProductoCreate` omits `id_categoria_producto` and forbids extra fields.
- **D4 — Enforce name uniqueness case-insensitively within a category.** The service trims `nombre` and uses a scoped lowercase lookup; identical names in another category remain valid.
- **D5 — Normalize optional descriptions.** Supplied descriptions are trimmed; empty results become `None`. Omitted descriptions remain absent/`None`.
- **D6 — Preserve model defaults.** Omitted `activo`, `disponible`, and `orden` are excluded from model construction so SQLAlchemy applies existing defaults; explicit values are preserved.
- **D7 — Keep transactions in the service.** Repositories query and flush only. The service validates, commits successful creation, and rolls back persistence errors. Routers translate domain exceptions.
- **D8 — Extend the shared integration suite.** Tests run against `supernova_test` and cover both listing paths, ordering, ownership isolation, defaults, normalization, duplicates, missing resources, and rollback.

## Risks / Trade-offs

- **[Risk] Commerce listings depend on category ordering.** → Keep the join and complete ordering expression in one repository method and cover it with integration tests.
- **[Risk] Application-level duplicate checks can race.** → The database category/name unique constraint remains the final integrity guard; failed writes roll back.
- **[Trade-off] Responses contain only category IDs.** → This is intentional; category details and presentation associations are separate concerns.
