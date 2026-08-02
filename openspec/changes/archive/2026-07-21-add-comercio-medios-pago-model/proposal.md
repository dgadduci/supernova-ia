## Why

Subphase 1.3 introduced the `MediosPago` catalog (the reference list of payment methods a commerce may offer its customers) and — like `MetodosEntrega` (Subphase 1.4) — never landed a join table that ties a `Comercio` to the payment methods it accepts. Subphase 1.9 closed that gap for delivery methods by introducing `ComercioMetodoEntrega`. **Subphase 1.10** is the parallel for payment methods: it introduces `ComercioMedioPago`, the per-comercio payment-method row, and re-introduces the corresponding `Comercio.medios_pago` and `MediosPago.comercios` relationships so the navigation graph becomes symmetric.

This is a minimum, additive change. The new table carries only the columns the user supplied (`id_comercio`, `id_medio_pago`, `activo`, `titular`, `alias`, lifecycle timestamps) and one composite uniqueness rule. **Unlike** `ComercioMetodoEntrega` (1.9), this join has no `orden` column and therefore no `CheckConstraint` — payments are not sorted on display in the same way delivery methods are. Two per-comercio metadata columns (`titular`, `alias`) carry operator-facing display info that does not live on the global catalog. No denormalization, no API, no service, no migration, no seed data.

## What Changes

- Add a new SQLAlchemy model `ComercioMedioPago` in `backend/models/comercio_medios_pago.py` with `__tablename__ = "comercio_medios_pago"`, a `__table_args__` tuple declaring `UniqueConstraint("id_comercio", "id_medio_pago", name="comercio_medio_pago_unico")`, and the columns from the user's body: `id` (PK autoincrement); `id_comercio` (`ForeignKey("comercios.id", ondelete="CASCADE")`, non-null, indexed); `id_medio_pago` (`ForeignKey("medios_pago.id", ondelete="RESTRICT")`, non-null, indexed); `activo` (Boolean, non-null, `default=False`, `server_default="false"`); `titular` (String ≤ 150, nullable); `alias` (String ≤ 100, nullable); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime, `server_default=func.now()`, the latter additionally `onupdate=func.now()`).
- Add the two bidirectional relationships the join table enables:
  - `ComercioMedioPago.comercio = relationship(back_populates="medios_pago")`
  - `ComercioMedioPago.medio_pago = relationship(back_populates="comercios")`
- Re-introduce the previously-missing `Comercio.medios_pago = relationship(back_populates="comercio")` on `Comercio` (forward-ref string).
- Re-introduce the previously-missing `MediosPago.comercios = relationship(back_populates="medio_pago")` on `MediosPago` (forward-ref string + new `relationship` import).
- Re-export `ComercioMedioPago` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: Alembic migrations; seed rows; any service, repository, or API surface; per-comercio CVU/cbu/alias specifics (only the two user-supplied `titular` / `alias` text columns land); any `orden` or display-order column; any payment-method-type discriminator (debit/credit/etc.).

## Capabilities

### New Capabilities

- `comercio-medios-pago`: Defines the `ComercioMedioPago` SQLAlchemy model — the join table that ties a `Comercio` to the `MediosPago` catalog rows it accepts. Holds the two FKs, an opt-in `activo` flag (default `false`), two per-comercio metadata columns (`titular`, `alias`, both nullable), lifecycle timestamps, a composite uniqueness rule over `(id_comercio, id_medio_pago)`, and bidirectional `comercio` and `medio_pago` relationships.

### Modified Capabilities

- `medios-pago`: The existing `MediosPago` model gains a `comercios` relationship attribute pointing to the list of `ComercioMedioPago` rows where this catalog entry is selected. The relationship is implementation detail; no column set changes.
- `comercio`: The existing `Comercio` model gains a `medios_pago` relationship attribute (alongside the `metodos_entrega` relationship introduced in Subphase 1.9) pointing to the list of `ComercioMedioPago` rows for this commerce. The relationship is implementation detail; no column set changes.

## Impact

- **New file** `backend/models/comercio_medios_pago.py` containing the `ComercioMedioPago` class with `__table_args__`, the column set, and the two `relationship()` attributes.
- **Modified files**:
  - `backend/models/comercio.py` — add `medios_pago` relationship attribute (forward-ref string to break the cycle). The existing `metodos_entrega` attribute (from 1.9) is preserved unchanged.
  - `backend/models/medios_pago.py` — add `comercios` relationship attribute (forward-ref string) and the `relationship` import.
  - `backend/models/__init__.py` — re-export `ComercioMedioPago`.
- **Cross-model dependencies**: the two new FKs are the first edge in the model graph from `Comercio` toward the `MediosPago` catalog (via the join table). `ondelete="CASCADE"` on `id_comercio` mirrors the convention used by `CategoriaProducto`, `Presentacion`, and `ComercioMetodoEntrega`. `ondelete="RESTRICT"` on `id_medio_pago` mirrors the pattern used when a child FK should outlive its target (a catalog row cannot be deleted while a commerce still references it through the join).
- **Empty join table today** — no data is invalidated by the new constraints. If a future migration is run against a database that already contains `ComercioMedioPago` rows, the migration could fail with a constraint violation if duplicate `(id_comercio, id_medio_pago)` pairs exist. Mitigation: none required pre-merge; future audits can re-check.
- **No API, service, repository, or migration** introduced here.
