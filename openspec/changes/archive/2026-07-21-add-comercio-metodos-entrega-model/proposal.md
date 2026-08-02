## Why

Subphase 1.4 introduced the `MetodosEntrega` catalog (the reference list of delivery methods a commerce may offer) and explicitly deferred its consumer — a join table that ties each `Comercio` to the delivery methods it accepts — to a later subphase. The original `Comercio` spec (Subphase 1.2) likewise pointed a deferred relationship at a class called `ComercioMetodoEntrega`, which did not yet exist. **Subphase 1.9** closes that gap: it introduces the join table that lets a commerce opt-in to specific methods from the global catalog, and re-introduces the two deferred relationships on `Comercio` and `MetodosEntrega` so the navigation graph becomes symmetric.

This is a minimal, additive change: the new table carries only the columns the user supplied (`id_comercio`, `id_metodo_entrega`, `activo`, `orden`, lifecycle timestamps), one composite uniqueness rule, and one non-negative-order check constraint. No denormalization, no API, no service, no migration, no seed data.

## What Changes

- Add a new SQLAlchemy model `ComercioMetodoEntrega` in `backend/models/comercio_metodos_entrega.py` with `__tablename__ = "comercio_metodos_entrega"`, a `__table_args__` tuple declaring `UniqueConstraint("id_comercio", "id_metodo_entrega", name="comercio_metodo_unico")` and `CheckConstraint("orden >= 0", name="orden_no_negativo")`, and the columns from the user's body: `id` (PK autoincrement); `id_comercio` (`ForeignKey("comercios.id", ondelete="CASCADE")`, non-null, indexed); `id_metodo_entrega` (`ForeignKey("metodos_entrega.id", ondelete="RESTRICT")`, non-null, indexed); `activo` (Boolean, non-null, `default=False`, `server_default="false"`); `orden` (Integer, non-null, no default); and lifecycle timestamps `fecha_alta` and `fecha_ultima_modificacion` (timezone-aware DateTime, `server_default=func.now()`, the latter additionally `onupdate=func.now()`).
- Add the two bidirectional relationships the join table enables:
  - `ComercioMetodoEntrega.comercio = relationship(back_populates="metodos_entrega")`
  - `ComercioMetodoEntrega.metodo_entrega = relationship(back_populates="comercios")`
- Re-introduce the previously-deferred relationship on `Comercio`: `metodos_entrega: Mapped[list["ComercioMetodoEntrega"]] = relationship(back_populates="comercio")`.
- Re-introduce the previously-deferred relationship on `MetodosEntrega`: `comercios: Mapped[list["ComercioMetodoEntrega"]] = relationship(back_populates="metodo_entrega")`.
- Re-export `ComercioMetodoEntrega` from `backend/models/__init__.py`.
- **Explicitly out of scope** for this change: Alembic migrations; seed rows (`RETIRO_EN_LOCAL`, `DELIVERY_PROPIO`, `ENVIOS_CORREO`); any service, repository, or API surface; `MediosPago` equivalent (`ComercioMedioPago`) — a separate, future subphase; per-comercio customizations on top of the global `MetodosEntrega` catalog.

## Capabilities

### New Capabilities

- `comercio-metodos-entrega`: Defines the `ComercioMetodoEntrega` SQLAlchemy model — the join table that ties a `Comercio` to the `MetodosEntrega` catalog rows it accepts. Holds the two FKs, an opt-in `activo` flag (default `false`), a non-negative `orden`, lifecycle timestamps, a composite uniqueness rule over `(id_comercio, id_metodo_entrega)`, and a non-negative-order check constraint. Exposes bidirectional `comercio` and `metodo_entrega` relationships.

### Modified Capabilities

- `metodos-entrega`: The existing `MetodosEntrega` model gains a `comercios` relationship attribute pointing to the list of `ComercioMetodoEntrega` rows where this catalog entry is selected. The relationship is implementation detail; no column set changes.
- `comercio`: The existing `Comercio` model gains a `metodos_entrega` relationship attribute pointing to the list of `ComercioMetodoEntrega` rows for this commerce. The relationship is implementation detail; no column set changes.

## Impact

- **New file** `backend/models/comercio_metodos_entrega.py` containing the `ComercioMetodoEntrega` class with `__table_args__`, the column set, and the two `relationship()` attributes.
- **Modified files**:
  - `backend/models/comercio.py` — add `metodos_entrega` relationship attribute (forward-ref string to break the cycle).
  - `backend/models/metodos_entrega.py` — add `comercios` relationship attribute (forward-ref string to break the cycle).
  - `backend/models/__init__.py` — re-export `ComercioMetodoEntrega`.
- **Cross-model dependencies**: the two new FKs are the first edge in the model graph from `Comercio` toward the `MetodosEntrega` catalog (via the join table). `ondelete="CASCADE"` on `id_comercio` mirrors the convention used by `CategoriaProducto` and `Presentacion`; `ondelete="RESTRICT"` on `id_metodo_entrega` mirrors the pattern used when a child FK should outlive its target (a catalog row cannot be deleted while a commerce still references it through the join).
- **Empty join table today** — no data is invalidated by the new constraints. If a future migration is run against a database that already contains `ComercioMetodoEntrega` rows, the migration could fail with a constraint violation if duplicate `(id_comercio, id_metodo_entrega)` pairs or negative `orden` values exist. Mitigation: none required pre-merge; future audits can re-check.
- **No API, service, repository, or migration** introduced here.
