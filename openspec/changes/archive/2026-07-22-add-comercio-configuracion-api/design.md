## Context

The API currently exposes commerce and related catalogs through separate endpoints. Subphase 2.9 adds a read-only aggregate view containing one commerce, its status, payment-method associations/catalog records, and delivery-method associations/catalog records.

The existing relationships support ORM eager loading. Product-related relationships must remain untouched and unqueried. The endpoint must preserve association ordering and return empty arrays without triggering lazy loads after the session closes.

## Goals / Non-Goals

**Goals:**

- Return all scalar commerce fields and required nested configuration in one request.
- Eagerly load related records without N+1 queries.
- Preserve deterministic payment and delivery association ordering.
- Return 404 for a missing commerce and empty arrays for missing associations.
- Keep the operation read-only.

**Non-Goals:**

- Product categories, products, presentations, prices, or product-presentation data.
- Create, update, delete, filtering, pagination, authentication, or activation behavior.
- Model or migration changes.
- Generic aggregate/repository abstractions.

## Decisions

- **D1 — Dedicated aggregate modules.** Separate schemas, repository, service, and router keep aggregate concerns out of existing single-resource slices.
- **D2 — Use eager loading for both association branches.** ORM loader options load status, payment associations/catalog records, and delivery associations/catalog records before serialization, avoiding N+1 access.
- **D3 — Enforce ordering in relationship loader criteria or normalized loaded collections.** Payment associations are ordered by ID; delivery associations by `orden`, then ID. No inactive rows are filtered.
- **D4 — Define explicit nested response schemas.** Each schema exposes only scalar fields required by the contract, preventing unrelated relationships from appearing.
- **D5 — Service remains transaction-free.** It performs one repository request, raises existing `ComercioNotFound` when absent, and returns the loaded object without commit or rollback.
- **D6 — Extend the shared integration suite.** Tests verify nested ownership, catalog inclusion, ordering, empty arrays, 404 behavior, and absence of product fields.

## Risks / Trade-offs

- **[Risk] Multiple eager-loaded collections can multiply joined rows.** → Prefer `selectinload` for collections and `joinedload` for scalar relationships.
- **[Risk] ORM relationship definitions do not declare ordering.** → Make ordering explicit in the aggregate query/load result and cover it with integration tests.
- **[Trade-off] Response schemas duplicate some existing catalog schema fields.** → Dedicated detail schemas avoid coupling aggregate output to unrelated endpoint contracts.
