## Context

Phase 1 / Subphase 1.7 introduces **Producto** — the per-category product row — plus two enabling changes in lock-step:

1. The class currently named `CategoriasProductos` (Subphase 1.5) is renamed to singular `CategoriaProducto` to match the user's forward-ref, and gains a `productos` relationship so `Producto.categoria` can use `back_populates="productos"`.
2. A minimal stub of `ProductoPresentacion` is added (FKs + activation + ordering + lifecycle) so `Producto.presentaciones` resolves at module load. The full schema for `ProductoPresentacion` lands in a dedicated follow-up subphase.

This subphase finalizes the catalog + presentation relationships so that later subphases (order intake, listing, search) can navigate without ad-hoc joins. It also lands the first `ondelete="RESTRICT"` in the model layer (`Producto.id_categoria_producto` ↛ delete `CategoriaProducto` while products exist) and the first `Text` column (`Producto.descripcion`).

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supenova` and test DB `supenova_test`; both will eventually contain `productos` and `producto_presentacion` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `Producto` model whose column set and table-level constraints exactly match the user-supplied body.
- Provide a minimal `ProductoPresentacion` stub that makes `Producto.presentaciones` resolve at import time. The stub is intentionally lean: FKs, `activo`, `orden`, lifecycle timestamps.
- Rename `CategoriasProductos` → `CategoriaProducto` and add a `productos` relationship so `Producto.categoria` resolves.
- Re-export all three classes from `backend/models/__init__.py`.
- Mirror the established default patterns (`default` + `server_default`, timezone-aware timestamps with `onupdate`).

**Non-Goals:**

- The full `ProductoPresentacion` schema (constraints, ordering rules, uniqueness variants) — its own subphase.
- A back-reference from `Presentacion` to `ProductoPresentacion` — its own subphase.
- Seed data; Alembic migrations; any service or API surface.

## Decisions

**D1 — Files:**
- `backend/models/categoria_producto.py` does NOT exist; the existing `backend/models/categorias_productos.py` is reused and updated. **Class name** becomes `CategoriaProducto`; **tablename** stays `categorias_productos`.
- New file: `backend/models/producto.py` — `class Producto(Base)`, `__tablename__ = "productos"`.
- New file: `backend/models/producto_presentacion.py` — `class ProductoPresentacion(Base)`, `__tablename__ = "producto_presentacion"`.

Rationale for keeping the file location while changing the class name: matches the precedent set in Subphase 1.6 (`presentaciones.py` holds `class Presentacion`). Filenames are organizational; class names are part of the public API.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2, 1.3, 1.4, 1.5, 1.6 and the user's spec. Imports remain:
```python
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
```

`Text` is new for the model layer — first non-VARCHAR long-form column. Pattern: `descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)`.

**D3 — Renaming `CategoriasProductos` → `CategoriaProducto`.**
The user's `Producto.categoria` relationship forward-refs `CategoriaProducto` (singular). The existing class is `CategoriasProductos` (plural). Singular class names are now the established pattern (`Comercio`, `Presentacion`), so we rename the class. The implementation:

```python
# backend/models/categorias_productos.py
class CategoriaProducto(Base):
    __tablename__ = "categorias_productos"
    # ...existing columns unchanged...
    productos: Mapped[list["Producto"]] = relationship(back_populates="categoria")
```

The forward-ref string `"Producto"` avoids needing a hard import in `categorias_productos.py`, so the import graph can resolve in a single pass: `__init__.py` → both modules → relationships back-references resolve via `Base` metadata after both classes are declared.

Alternatives considered:
- Keep the class name `CategoriasProductos` and use forward-ref string `"CategoriaProducto"` in `Producto.categoria` — would never resolve because the string points to a class name that doesn't exist. Rejected.
- Rename the file too (to `categoria_producto.py`) for full file/class parity — invasive, with no benefit beyond cosmetics; rejected.

**D4 — `ondelete="RESTRICT"` on `Producto.id_categoria_producto`.**
The user supplied `RESTRICT`. Rationale: a `CategoriaProducto` row is a logical reference entry that defines the catalog branch under which products live; deleting it while products still reference it would orphan the catalog pointer. We `RESTRICT` so the application must clean up dependent products first.

This is the first `RESTRICT` FK in the model layer. Earlier per-comercio child tables used `CASCADE` because the children's existence was meaningless without the parent. Here the relationship is reversed from the child-tables pattern: `Producto` belongs to `CategoriaProducto`, not the other way around, and a category's "logical identity" is preserved even when products are reclassified.

Alternatives considered:
- `CASCADE`: rejected — silently deletes all products when a category is removed.
- `SET NULL`: rejected — turns the FK into a nullable column (already `nullable=False` in spec); breaks the data invariant.

**D5 — Composite `UniqueConstraint` named `categoria_producto_nombre_unico`.**
User supplied exactly: `UniqueConstraint("id_categoria_producto", "nombre", name="categoria_producto_nombre_unico")`. Note the singular `categoria_producto` in the constraint name, consistent with the user's pattern. We preserve the name verbatim.

**D6 — `CheckConstraint("orden >= 0", name="orden_no_negativo")`.**
Same logical name as `MetodosEntrega` (1.4) and `Presentacion` (1.6). PostgreSQL scopes constraint names per-table; no collision.

**D7 — `Producto` relationships.**
```python
categoria: Mapped["CategoriaProducto"] = relationship(
    back_populates="productos",
)
presentaciones: Mapped[list["ProductoPresentacion"]] = relationship(
    back_populates="producto",
)
```

User supplied both verbatim. The `back_populates` references require:
- `CategoriaProducto.productos = relationship(back_populates="categoria")` — added here.
- `ProductoPresentacion.producto = relationship(back_populates="presentaciones")` — added in the stub.
- `ProductoPresentacion.presentacion = relationship(...)` — declared as a forward-ref; the `Presentacion` back-ref lands in a dedicated subphase.

**D8 — `descripcion` as `Text` (nullable).**
First `Text` column in the model layer — used for arbitrarily long descriptions. `nullable=True` per spec. Pattern:
```python
descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Alternatives considered:
- `String(N)` with a large `N`: rejected — the description is conceptually unbounded; VARCHAR caps lead to surprising truncation errors.

**D9 — Two flags: `activo` and `disponible`.**
Per spec; both are `Boolean` with `default=True` and `server_default="true"`. They answer different questions:
- `activo` — admin-controlled catalog state. When `False`, the product is hidden from listings entirely.
- `disponible` — operational stock state. When `False`, the product is listed but cannot be ordered (out-of-stock).

Both default to `True`; both can be set independently. Defining them as two columns rather than one is the user's design choice and is preserved verbatim.

**D10 — `ProductoPresentacion` stub shape.**
Minimum to make `Producto.presentaciones` resolve at import time:
- `id_producto` (FK to `productos.id`, `ondelete="CASCADE"`, indexed)
- `id_presentacion` (FK to `presentaciones.id`, `ondelete="CASCADE"`, indexed)
- `activo` (Boolean, default True, server_default "true")
- `orden` (Integer, default 0, server_default "0")
- `fecha_alta` + `fecha_ultima_modificacion` (timestamps)
- `producto` relationship (`back_populates="presentaciones"`)
- `presentacion` relationship (forward-ref to `Presentacion`; back-ref lands elsewhere)

`CASCADE` on both FKs mirrors the standard join-table semantics: removing a `Producto` or a `Presentacion` cleans up join rows. No `__table_args__` is needed for the stub; uniqueness, ordering policies, and other invariants are deferred.

Alternatives considered:
- Define the stub without any back-relationships: rejected — `relationship(back_populates=...)` demands the partner attribute exists at import time.
- Make `ProductoPresentacion` a pure association table (no `activo` / `orden`): rejected — it would not be able to reflect per-product-presentation config, and the user's spec explicitly lists these columns.

**D11 — No `__repr__`, no validators, no extra `relationship()` not declared in the spec.**
Per "Implement only what is explicitly requested" and "Avoid overengineering".

## Risks / Trade-offs

- **[Risk] Renaming `CategoriasProductos` → `CategoriaProducto` is observable to any direct importer.** → Mitigation: documented. The re-export slot is updated; archived specs stay as historical.
- **[Risk] `ProductoPresentacion` is a stub without uniqueness, ordering policy, or any of the constraints the full model will need.** → Mitigation: explicit in the requirement title (`stub`) and in Open Questions. A dedicated subphase refines it.
- **[Risk] `Presentacion` does not yet declare a back-reference to `ProductoPresentacion`.** → Mitigation: documented in Open Questions; the forward-ref on `ProductoPresentacion.presentacion` does not break — it just leaves the partner side unconfigured until the other subphase lands.
- **[Risk] `RESTRICT` on `Producto.id_categoria_producto` blocks `CategoriaProducto` deletion in any code that tries it.** → Mitigation: intentional. The application layer must decide how to handle "category has products" — soft-disable, reassign, or hard-delete product-by-product.
- **[Trade-off] `activo` and `disponible` are introduced as separate columns without a process layer.** → Acceptable: the design intent is that the application interprets them.
- **[Trade-off] Mixing SQLAlchemy declarative styles** (`Column(…)` in 1.1, `Mapped[…]` elsewhere). → Acceptable: same compile target.

## Migration Plan

Not applicable in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test` and create `productos` and `producto_presentacion` on both databases.

The class rename `CategoriasProductos` → `CategoriaProducto` is a Python-level change only; no DB-level rename required (`__tablename__` stays `categorias_productos`).

## Open Questions

- **`ProductoPresentacion` refinement.** Add uniqueness (e.g., a `(id_producto, id_presentacion)` composite unique constraint that no two rows pair the same product with the same presentation), and possibly an `id_categoria_producto` materialization so the join row can be queried quickly per-category. Land in a dedicated subphase.
- **`Presentacion` back-reference.** Add `Presentacion.productos_presentacion = relationship("ProductoPresentacion", back_populates="presentacion")`. Land in a dedicated subphase.
- **`CategoriaProducto` relationship wiring.** Confirm: a category's `productos` collection is auto-loaded when accessing `categoria_producto.productos`. By default this is lazy-loaded; a future subphase may opt into `joinedload`/`selectinload` for read-heavy paths.
- **`disponible` lifecycle hook.** The DB enforces only the default; an application-level transition (e.g., 0-stock → out-of-stock) is not coded here. Should `disponible` flip automatically based on inventory? Defer.
