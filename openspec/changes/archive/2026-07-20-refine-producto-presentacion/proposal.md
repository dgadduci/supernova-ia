## Why

Phase 1 left two implementation-deferred items open when Subphase 1.7 shipped the `ProductoPresentacion` stub: (a) the model was deliberately thin — only FKs plus minimal defaults, no uniqueness or ordering invariants — and (b) `Presentacion` was never wired with a `productos_presentacion` back-reference, so navigation from a presentation to its product pairings required manual joins. This change closes both gaps in one pass so that `ProductoPresentacion` is a real join table (not a stub), and so that `Presentacion` exposes its pairings the same way `Producto` does.

The refinement is the minimal one: a composite uniqueness rule (no two rows pair the same product with the same presentation) and the same `orden >= 0` check constraint pattern that other child tables already carry. No denormalized `id_categoria_producto` materialization, no extra indexes — those remain future-work options.

## What Changes

- Extend `backend/models/producto_presentacion.py` with a `__table_args__` tuple declaring:
  - `UniqueConstraint("id_producto", "id_presentacion", name="producto_presentacion_unico")`
  - `CheckConstraint("orden >= 0", name="orden_no_negativo")`
- Add a `Presentacion.productos_presentacion = relationship("ProductoPresentacion", back_populates="presentacion")` attribute to `Presentacion` so the bidirectional navigation `Producto.presentaciones ↔ Presentacion.productos_presentacion` is symmetric.
- **No other side effects.** No service, API, migration, or seed changes. The new constraints add behavior — including a potential runtime failure when existing data (none today; the join table is empty) violates the new rules. The change does not delete or modify any existing rows.
- The back-reference relationship is purely implementation detail: it does not introduce behavior changes to `Presentacion`. No `MODIFIED Requirements` are needed for the `presentaciones` capability; only `producto-presentacion` is affected at the spec level.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `producto-presentacion`: The existing `ProductoPresentacion model definition` requirement gains two table-level invariants — a composite `(id_producto, id_presentacion)` unique constraint named `producto_presentacion_unico`, and a non-negative-order check constraint named `orden_no_negativo`.

## Impact

- **Modified files**: `backend/models/producto_presentacion.py` (new `__table_args__`), `backend/models/presentaciones.py` (new `productos_presentacion` relationship attribute).
- **`__init__.py` re-exports** unchanged — both classes are already exported.
- **Cross-model dependencies** (table level): none new; the existing two FKs (`productos.id` and `presentaciones.id`, both `CASCADE`) are unchanged.
- **Empty join table today** — no data is invalidated by the new constraints. If a future migration is run against a database that already contains `ProductoPresentacion` rows, the migration could fail with a constraint violation if duplicate `(id_producto, id_presentacion)` pairs or negative `orden` values exist. Mitigation: none required pre-merge; future audits can re-check.
- **Back-reference plumbing**: the new `Presentacion.productos_presentacion` relationship has `lazy="select"` by default — i.e., a separate `SELECT` on access. Cardinally equivalent to how `Producto.presentaciones` and `CategoriaProducto.productos` already work in this codebase.
- **No API, service, repository, or migration** introduced here.
