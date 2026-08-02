## Context

Subphase 1.7 introduced a deliberately-thin `ProductoPresentacion` join table (FKs + `activo` + `orden` + timestamps) so that `Producto.presentaciones` would resolve. That decision left two open items in the original `design.md`: (a) the model needed real invariants — uniqueness between `(id_producto, id_presentacion)` and a non-negative-order check — and (b) `Presentacion` was never wired with the matching `productos_presentacion` back-reference. This change closes both.

This is the **minimal** refinement the user asked for: a composite unique + the same `orden_no_negativo` check pattern that `MetodosEntrega`, `Presentacion`, and `Producto` all carry. No denormalization, no extra indexes, no service-layer work.

After this change, the `Producto ↔ ProductoPresentacion ↔ Presentacion` graph becomes navigable symmetrically:

- `presentacion.productos` (already there as `cascade="all, delete-orphan"` from the `comercio.py` original spec) gives "presentations belonging to a comercio"
- `producto.presentaciones` (new in 1.7) gives "join rows for a product"
- `presentacion.productos_presentacion` (this change) gives "join rows for a presentation"
- `producto_presentacion.producto` and `.presentacion` (already there) close the loop

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supenova` and test DB `supenova_test`; both will eventually carry the new constraints once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Add a `__table_args__` tuple to `ProductoPresentacion` containing the composite `UniqueConstraint("id_producto", "id_presentacion", name="producto_presentacion_unico")` and the `CheckConstraint("orden >= 0", name="orden_no_negativo")`.
- Add `Presentacion.productos_presentacion = relationship("ProductoPresentacion", back_populates="presentacion")` so the bidirectional navigation matches.
- Preserve all existing columns and defaults on both models.

**Non-Goals:**

- The full `ProductoPresentacion` schema beyond minimal refinement — deferred.
- Any service, repository, API endpoint, or DTO layer.
- Migration of existing data (none exists today).
- `Presentacion` requirement changes (the back-ref is implementation detail).

## Decisions

**D1 — File: `backend/models/producto_presentacion.py` and `backend/models/presentaciones.py`.**
The change touches two files:
- `producto_presentacion.py`: add `UniqueConstraint`, `CheckConstraint` imports; declare `__table_args__`.
- `presentaciones.py`: add `productos_presentacion` relationship attribute.

`__init__.py` re-exports are unchanged.

**D2 — `__table_args__` order.**
```python
__table_args__ = (
    UniqueConstraint("id_producto", "id_presentacion", name="producto_presentacion_unico"),
    CheckConstraint("orden >= 0", name="orden_no_negativo"),
)
```
Uniqueness first, then the check. Rationale: matches the order used in `Producto` (composite unique first, check after) and avoids surprise.

Alternatives considered:
- Reverse order (check first): rejected — does not match the convention now used by `Producto` and `Presentacion`.
- `__table_args__` declared as a tuple of tuples: rejected — the user idiom is a flat tuple; SQLAlchemy accepts both.

**D3 — Back-reference attribute name: `productos_presentacion`.**
Naming rationale: `Presentacion` already has a `relationship()` called `productos` to `ComercioMetodosPago` per the original spec (in Subphase 1.2, that relationship was named `metodos_entrega`; the field `productos` is owned by `CategoriaProducto`, not `Presentacion`). The join-row collection is logically distinct, so we name it `productos_presentacion`. Mirrors the user's request that the relationship target a list of `ProductoPresentacion`.

Alternatives considered:
- `presentaciones` (matching `Producto.presentaciones`): rejected — would clash conceptually with the future direct Producto ↔ Presentacion collection if one ever materializes.
- `presentacion_links` / `vincular_presentaciones`: rejected — `productos_presentacion` is unambiguous about the join-row semantics.

**D4 — Forward-ref string `"ProductoPresentacion"` from `Presentacion`.**
The two models form a cycle (`Presentacion.productos_presentacion` ↔ `ProductoPresentacion.presentacion` ↔ `ProductoPresentacion.producto` ↔ `Producto.presentaciones` ↔ `Producto.categoria` ↔ `CategoriaProducto.productos` is a closed cycle through 1.7's renames). All relationships already use forward-ref strings. We preserve that pattern; no hard import is added in either direction.

**D5 — No `__repr__`, no validators, no extra `relationship()`.**
Per "Implement only what is explicitly requested" and "Avoid overengineering".

## Risks / Trade-offs

- **[Risk] A future migration applying the new constraints against a database with existing data could fail with constraint violations.** → Mitigation: documented. The join table is empty today; future audits can recheck before any migration runs.
- **[Risk] `ProductoPresentacion.producto` and `.presentacion` both use `back_populates`, which requires that the partner attribute exists at import time on the partner class.** → Mitigation: `Presentacion.productos_presentacion` is added in this same change; both load simultaneously via `Base.metadata`.
- **[Trade-off] Two-way navigation is implemented asymmetrically:** `Producto.presentaciones` and `Producto.categoria` already had back-references; now `Presentacion.productos_presentacion` joins them. Symmetric in the sense of `back_populates`; mildly redundant because three classes are involved instead of two.
- **[Trade-off] Lazy-loading default:** both new relationship and `ProductoPresentacion`'s existing two relationships load on first access. Acceptable for now; a future subphase may opt into `joinedload` / `selectinload` for read-heavy paths.

## Migration Plan

Not applicable in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`. That migration will need to add the two constraints to `producto_presentacion` (and any earlier tables that lacked their first migration yet).

## Open Questions

- **`ProductoPresentacion` denormalization.** A future subphase may denormalize `id_categoria_producto` from `Producto` into `ProductoPresentacion` to enable fast per-category queries without the join. **Out of scope for this refinement.**
- **`ComercioMetodoEntrega`.** Decision still open from earlier subphases: per-comercio config (matching `CategoriasProductos` / `Presentacion` pattern) or join to the global `metodos_entrega` catalog. **Out of scope here.**
