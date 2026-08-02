## Context

The seed layer separates generated data from persistence. Category and presentation rules are resolved when producing the JSON dataset; the runtime seed script remains policy-free and only validates references, decimal values, and idempotency.

## Goals / Non-Goals

**Goals:**

- Cover every seeded product-presentation with one category-appropriate price.
- Preserve the pizza size relationship and configured category ranges in generated data.
- Insert prices idempotently into either configured database.
- Fail atomically when JSON references or values are invalid.

**Non-Goals:**

- Generate prices dynamically during seed execution.
- Update existing prices.
- Create product-presentation rows.
- Modify models or migrations.

## Decisions

- **D1 — JSON uses model-facing fields.** Each entry contains `id_producto_presentacion` and a decimal-safe `precio` string.
- **D2 — Price policy belongs to generation.** Database traversal determines product category and presentation, then generates deterministic values in the configured ranges. The persistence script does not contain category pricing rules.
- **D3 — Idempotency uses `id_producto_presentacion`.** Existing prices are skipped, matching the table's unique index.
- **D4 — One database per invocation.** `SUPERNOVA_DATABASE_URL` selects the target and defaults to `supernova_test`, matching existing seed scripts.
- **D5 — Validate before each insert within one transaction.** Missing parent IDs, negative/out-of-range values, or excess decimal scale raise `ValueError` and roll back the invocation.

## Risks / Trade-offs

- **[Risk] IDs diverge between databases.** → Verification runs against both databases; the seed fails clearly if a referenced product-presentation is absent.
- **[Trade-off] Existing prices are not updated.** → This preserves idempotency and avoids silently changing operator-managed values.
