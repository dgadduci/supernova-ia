## Context

Subphases 2.1 through 2.7 established synchronous FastAPI slices and product catalog access using `Router → Service → Repository → Model`. Subphase 2.8 exposes `Precio`, the one-to-one current price attached to a `ProductoPresentacion` record.

`Precio.precio` uses PostgreSQL `Numeric(12, 2)` and Python `Decimal`, has a non-negative check, and has a unique index on `id_producto_presentacion`. The HTTP layer must preserve decimal precision, reject excess scale/precision, and avoid creating or loading product-presentation relationships.

## Goals / Non-Goals

**Goals:**

- Retrieve a price by ID or by product-presentation ID.
- Create exactly one non-negative, two-decimal price for an existing product-presentation.
- Preserve decimal values end-to-end without binary floating-point conversion.
- Maintain established exception translation, transaction ownership, and integration-test patterns.
- Condense the completed Subphase 2.8 project entry.

**Non-Goals:**

- Update, delete, price history, discounts, promotions, bulk operations, pagination, or authentication.
- Product-presentation creation or modification.
- Changes to `Precio`, `ProductoPresentacion`, or database schema.
- Generic repository or CRUD abstractions.

## Decisions

- **D1 — Use one nested singleton route plus direct retrieval.** `/producto-presentaciones/{id}/precio` represents the single current price for an association; `/precios/{id}` provides direct lookup.
- **D2 — Validate decimals in Pydantic before persistence.** `PrecioCreate.precio` uses `Decimal` with non-negative, maximum 12 digits, and maximum two decimal places. Floats are never introduced by application code.
- **D3 — Quantize to two places in the service.** Accepted values are normalized with `Decimal("0.01")` before repository creation; responses remain `Decimal` and serialize through Pydantic's decimal support.
- **D4 — Distinguish missing association, missing price, and duplicate price.** Missing `ProductoPresentacion` and missing `Precio` map to 404; an existing price on the association maps to 409.
- **D5 — Keep responsibility boundaries stable.** The repository performs existence checks, lookups, and flush-only creation. The service validates, quantizes, checks uniqueness, commits, and rolls back. The router maps domain exceptions.
- **D6 — Extend the shared integration suite.** Tests against `supernova_test` cover decimal preservation, validation, singleton uniqueness, both retrieval routes, missing resources, and rollback.

## Risks / Trade-offs

- **[Risk] JSON clients may parse decimal output as binary floating point.** → The server serializes from `Decimal` without internal float conversion; client parsing is outside this API contract.
- **[Risk] Concurrent creates can pass the service lookup.** → The unique index remains the final integrity guard; the service rolls back failed writes.
- **[Trade-off] There is no way to change an existing price.** → Update/history semantics are intentionally deferred.
