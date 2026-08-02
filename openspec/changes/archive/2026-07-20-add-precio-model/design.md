## Context

Phase 1 / Subphase 1.8 introduces **Precio** — the price-per-product-presentation row. Pricing is a leaf-level concept (one row per `ProductoPresentacion` join row, enforced 1:1 by a unique index). It is the **first numeric/decimal column** in the model layer and the **first `Index("col", unique=True)`** entry.

The user's FK target (`"producto_presentaciones.id"`, plural) is incompatible with the live `ProductoPresentacion` tablename (singular `producto_presentacion`, set during Subphase 1.7's refinement). The user has confirmed the rename `producto_presentacion` → `producto_presentaciones`. That rename is Python-side only — the table is empty today, so no `ALTER TABLE` is required at runtime.

Two enabling changes land in lock-step:

1. The `ProductoPresentacion` table name flips to plural `producto_presentaciones`.
2. A `precios` relationship back-reference lands on `ProductoPresentacion`.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supenova` and test DB `supenova_test`; both will eventually contain `producto_precios` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `Precio` model whose columns and `__table_args__` exactly match the user-supplied body.
- Refactor `ProductoPresentacion.__tablename__` to plural `producto_presentaciones` so the FK literal resolves.
- Add `precios` relationship back-reference on `ProductoPresentacion` so `Precio.producto_presentacion` resolves with `back_populates`.
- Re-export `Precio` from `backend/models/__init__.py`.
- Use forward-ref strings to avoid the now three-deep cycle (`Producto` ↔ `ProductoPresentacion` ↔ `Precio` ↔ `Presentacion`).

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Currency columns, multi-currency math, exchange rate handling.
- Per-commerce price overrides — `Precio` is a global price per `(producto, presentacion)` pair; per-commerce overrides would need a join with `comercios.id` and land in a dedicated subphase.
- Seed data; service/repository/API/DTO layer.

## Decisions

**D1 — File: `backend/models/precio.py` (new); `backend/models/producto_presentacion.py` (refactor).**

The new file is `backend/models/precio.py`. The refactor modifies the existing `ProductoPresentacion` file:
- `__tablename__`: `producto_presentacion` → `producto_presentaciones` (Python-side only).
- New attribute: `precios: Mapped[list["Precio"]] = relationship(back_populates="producto_presentacion")`.

The pattern of keeping the class name `ProductoPresentacion` and updating only the tablename mirrors the historic `Comercio` (singular) ↔ `comercios` (plural) rename in Subphase 1.5.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2, 1.3, 1.4, 1.5, 1.6, 1.7. Imports:
```python
from decimal import Decimal
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
```
`Decimal` (PEP-style Python type) and `Numeric` (SA's generic type) cooperate via `Mapped[Decimal] = mapped_column(Numeric(12, 2), …)` — the standard pattern for monetary columns in SA 2.0.

**D3 — `Numeric(12, 2)` precision/scale.**
12 total digits, 2 decimal places → max value `9,999,999,999.99`. Allows gross-revenue and small-payment support within one column. We pick this over `Numeric(10, 2)` (`99,999,999.99`) because the user supplied the value and we preserve it verbatim; the wider choice is rarely a problem.

Alternatives considered:
- `Numeric` without precision/scale: rejected — disallows rounding with arbitrary length, surprising in arithmetic.
- `Decimal` stored as `String`: rejected — defeats indexed range queries and arithmetic; only justified for arbitrary-precision audit logs.

**D4 — `__table_args__` with explicit `Index`, **not** `unique=True` on the column.**
```python
__table_args__ = (
    CheckConstraint("precio >= 0", name="precio_no_negativo"),
    Index("id_producto_presentacion", unique=True),
)
```

The user wrote the unique constraint as `Index("id_producto_presentacion", unique=True)`. We preserve that form. **Note**: the resulting index name is `"id_producto_presentacion"` (PostgreSQL prefixes unique indexes with `ix_` automatically; the operational name is `ix_id_producto_presentacion`). The spec scenario asserts the index name `id_producto_presentacion` literally to match the user's source; runtime introspection will return `ix_<name>` because PostgreSQL auto-prefixes.

Alternatives considered:
- `Column(…, unique=True, index=True)` on the column itself: rejected — the user supplied the form; auto-form would lose the expressivity of `__table_args__`.
- `UniqueConstraint("id_producto_presentacion", name="<name>")`: rejected — different from the user's `Index("…", unique=True)` style; would not surface the index opt-in.

**D5 — Unique 1:1 between `ProductoPresentacion` and `Precio`.**
A row in `precio` belongs to exactly one `producto_presentacion` row, and vice versa. Enforced by the unique index on `id_producto_presentacion` (D4). The model is **not** an "append-only price history" — a single current price per `ProductoPresentacion` lives here. A price-history table is a future subphase.

Alternatives considered:
- One-to-many (`Precio` has multiple per `ProductoPresentacion` for historical prices): rejected — the user-supplied unique index is explicit one-to-one.

**D6 — `ondelete="RESTRICT"` on `id_producto_presentacion`.**
The user supplied `RESTRICT`. Rationale: a `ProductoPresentacion` row's meaning collapses without its price; we don't want a price deletion to orphan-remove a presentation. This mirrors the `CategoriaProducto`-`Producto` pattern (Subphase 1.7).

**D7 — Only `fecha_alta` lifecycle column, no `fecha_ultima_modificacion`.**
The user-supplied model has only `fecha_alta`. We don't add an `onupdate=func.now()` modification timestamp because there's no `fecha_ultima_modificacion` column to apply it to. A future subphase that wants a price-history pattern (multiple rows per presentation) would carry both timestamps per row.

**D8 — No `__repr__`, no validators, no extra relationship.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". The `precios` back-reference uses `lazy="select"` (default).

**D9 — Forward-ref string `"Precio"` on `ProductoPresentacion`.**
The deep cycle `Producto` ↔ `ProductoPresentacion` ↔ `Precio` ↔ `Presentacion` cannot be broken with hard imports without restructuring the modules. All relationships use forward-ref strings per the established pattern.

## Risks / Trade-offs

- **[Risk] A future migration applying the table-name rename against a populated database could fail.** → Mitigation: documented. The join table is empty today; any future migration can `ALTER TABLE … RENAME TO producto_presentaciones` to apply the rename to existing data.
- **[Risk] Unique index over `id_producto_presentacion` plus `ondelete="RESTRICT"` means an existing `ProductoPresentacion` cannot be deleted if a `Precio` row references it.** → Mitigation: intentional. The application layer is responsible for removing `Precio` rows before removing the join row.
- **[Trade-off] No `fecha_ultima_modificacion`.** A future change must add the column or move to a price-history pattern (one row per (presentation, valid_range)) to capture edits. Acceptable: matches user's spec.
- **[Trade-off] Plain `Decimal` arithmetic.** Without an explicit precision policy or rounding rules at the application layer, total prices may not match the user's mental model. Out of scope here; document in Open Questions.

## Migration Plan

Not applicable in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`. That migration must:
- Drop the old `producto_presentacion` table if any DB has it.
- Create `producto_presentaciones` (renamed version of what was there) plus the new `producto_precios` table.
- Add the `precio_no_negativo` check constraint and the unique index on `id_producto_presentacion`.

## Open Questions

- **Price history.** Will future requirements need an explicit `Precio` history table (with `fecha_desde`/`fecha_hasta` or a temporal validity pattern)? Adds a lot of design surface; defer.
- **Currency / FX.** Currently amounts are pure `Decimal`. A future subphase may add `moneda` and an FX translation layer.
- **`ProductoPresentacion` history.** Same temporal question for the join row itself — out of scope here.
- **`ComercioMetodoEntrega`.** Open question carried from earlier: per-comercio config vs. join to global catalog. The `Precio` table is global for now; if a per-commerce override is needed, that lands in its own change and uses its own lineage.
