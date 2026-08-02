## Context

Subphases 2.5 through 2.9 added lightweight product, presentation, price, and commerce-configuration endpoints. Subphase 2.10 adds read-only aggregate query endpoints that combine product, category, presentation, and price data, plus admin discovery of incomplete products. Existing lightweight routes remain available.

Product relationships chain `Comercio → CategoriaProducto → Producto → ProductoPresentacion → Presentacion` and `ProductoPresentacion → Precio` (1:1). These chains are read-only; we rely on `selectinload`/`joinedload` to avoid N+1 queries and the existing service/repository layering.

## Goals / Non-Goals

**Goals:**

- Provide read-only deep queries for product detail, catalog, presentations, prices, search, available, sellable, and incomplete products.
- Reuse or minimally extend the existing product repository, service, schemas, and router.
- Preserve deterministic ordering and `Decimal` precision for prices.
- Return 404 only for missing required parent records; return empty arrays for missing related collections.
- Distinguish active, available, sellable, and incomplete products through deterministic repository queries.

**Non-Goals:**

- Mutate products, presentations, or prices.
- Add commerce configuration or payment/delivery data to the query responses.
- Introduce fuzzy search.
- Modify models, migrations, lightweight routes, or authentication.

## Decisions

- **D1 — Reuse the existing product modules first.** When a required repository method, service method, schema, or route already exists, extend or expose it instead of duplicating.
- **D2 — Keep queries read-only.** Services raise existing domain exceptions for missing parents and return loaded data without commit/rollback.
- **D3 — Use eager loading to avoid N+1.** `selectinload` for collections, `joinedload` for scalar relationships, and explicit joins only when filtering requires them.
- **D4 — Encapsulate product-query routes in a new router module.** The new routes are query- and admin-specific, so they live in a separate router to keep the existing product router focused on create/list basics. Routes are placed before any conflicting dynamic patterns.
- **D5 — Catalog filters use boolean query parameters.** `solo_activos` and `solo_disponibles` default to `true`; passing `false` explicitly disables the corresponding filter.
- **D6 — Search and name endpoints are scoped to one commerce.** Filters, ordering, and case-insensitive matching are applied at the SQL layer.
- **D7 — Decimal precision is preserved end-to-end.** Prices are returned as `Decimal` and serialized through Pydantic decimal support; no binary-float conversion.
- **D8 — Incomplete-product detection is a pure query.** Repository methods compute the problem codes and return them; no write operations occur.

## Risks / Trade-offs

- **[Risk] Duplicate routes or schemas introduced by haste.** → Verify each candidate endpoint against existing routes, repository, and service before adding code; document reuse in the design and tasks.
- **[Risk] Eager-loading large catalogs causes memory pressure.** → Use `selectinload` for categories/products/associations and allow optional `solo_activos`/`solo_disponibles` filters to limit result sizes.
- **[Trade-off] Search is intentionally simple.** → No fuzzy match, ranking, or pagination; matches the existing explicit-query style.
- **[Trade-off] Incomplete detection is a coarse check.** → Only the configuration problems enumerated in the subphase are reported; finer-grained admin tooling is out of scope.
