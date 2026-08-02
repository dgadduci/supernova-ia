## Context

The model layer of supernova-ia is being built up in small, single-purpose subphases. Phase 1 has so far produced the catalog-side and per-comercio tables (`EstadoComercio`, `Comercio`, `MediosPago`, `MetodosEntrega`, `CategoriaProducto`, `Presentacion`, `Producto`, `ProductoPresentacion`, `Precio`). The catalog of delivery methods (`MetodosEntrega`) was introduced in Subphase 1.4 with an explicit note in `openspec/specs/metodos-entrega/spec.md`: *"Consumers (a future commerce-to-method association) will land in a separate subphase."* Likewise, the original `Comercio` spec (Subphase 1.2) deferred a `metodos_entrega` relationship pointing at a `ComercioMetodoEntrega` class that did not yet exist.

**Subphase 1.9** closes that gap. It introduces the join table — a real, navigable edge in the model graph — and re-introduces the two deferred relationships (`Comercio.metodos_entrega`, `MetodosEntrega.comercios`) so navigation is symmetric.

The change is the minimum required by the user's body: no extra indexes beyond the FKs, no denormalization, no service layer, no migration. The new invariants (composite uniqueness, non-negative `orden`) follow the same pattern already used by `ProductoPresentacion` (Subphase 1.8 refinement): a `UniqueConstraint` and a `CheckConstraint` declared in `__table_args__`.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supernova` and test DB `supenova_test`; both will eventually contain `comercio_metodos_entrega` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `ComercioMetodoEntrega` model whose column set exactly matches the user-supplied body.
- Declare a `UniqueConstraint` named `comercio_metodo_unico` enforcing `(id_comercio, id_metodo_entrega)` uniqueness, attached via `__table_args__`.
- Declare a `CheckConstraint` named `orden_no_negativo` enforcing `orden >= 0`, attached via `__table_args__`.
- Re-export `ComercioMetodoEntrega` from `backend/models/__init__.py`.
- Re-introduce `Comercio.metodos_entrega` and `MetodosEntrega.comercios` as forward-ref `relationship()` attributes using `back_populates`.
- Keep the surface area minimal: no `__repr__`, no validators, no extra indexes, no service layer.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seed rows for `metodos_entrega` and seed join rows (`(comercio, RETIRO_EN_LOCAL)`, …).
- The `ComercioMedioPago` join table (a parallel to this one for payments — separate future subphase).
- Any per-comercio override of catalog fields (e.g., per-comercio `descripcion` or per-comercio `activo` that diverges from the catalog row).
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/comercio_metodos_entrega.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in Subphases 1.1–1.8: one purpose per file under `backend/models/`, `__init__.py` re-exports.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2–1.8 and the user's spec. `EstadoComercio` in 1.1 used `Column(…)`; the mixed style is preserved without modification.

**D3 — `__tablename__ = "comercio_metodos_entrega"` exactly as supplied.**
Spanish snake_case matches `comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`, `presentaciones`, `productos`, `producto_presentaciones`. The join table is plural-as-collection (mirroring `producto_presentaciones`).

**D4 — `__table_args__` order: composite unique first, then check constraint.**
```python
__table_args__ = (
    UniqueConstraint("id_comercio", "id_metodo_entrega", name="comercio_metodo_unico"),
    CheckConstraint("orden >= 0", name="orden_no_negativo"),
)
```
Matches the order used by `Producto` and `ProductoPresentacion` (composite unique first, check after) — see Subphase 1.8 design.

**D5 — `id_comercio` FK uses `ondelete="CASCADE"`.**
When a `Comercio` is deleted, its per-comercio join rows go with it. This mirrors `CategoriaProducto.id_comercio` and `Presentacion.id_comercio` (both `CASCADE`). Semantically: a join row is an extension of its parent comercio, not an independent entity.

**D6 — `id_metodo_entrega` FK uses `ondelete="RESTRICT"`.**
A catalog row from `MetodosEntrega` cannot be deleted while any commerce still references it through the join. This mirrors `Producto.id_categoria_producto` (`RESTRICT`) and `Precio.id_producto_presentacion` (`RESTRICT`): the child FK should outlive its parent. Semantically: removing a catalog row is a destructive administrative action that should fail loudly if any commerce is still using it.

**D7 — `activo` carries `default=False` AND `server_default="false"`.**
This differs from `ProductoPresentacion.activo` (which defaults to `True`). The user explicitly chose `False`: a new join row is **opt-in** (the comercio must explicitly enable each delivery method), not opt-out. We honor both sides: Python-side default for ORM inserts; server-side default for raw SQL inserts and migrations. The semantic mirror is the `comercios` rows in the catalog — they default to enabled, but a comercio adopting them is disabled by default until the operator turns each on.

**D8 — `orden` is non-null with NO default.**
The user's body did not specify a default. We honor that — `default=0`/`server_default="0"` (as used in `ProductoPresentacion`) is **not** added. Every insert must supply `orden` explicitly. Trade-off: more explicit insert contracts; matches `MetodosEntrega.orden` (also default-less).

**D9 — `MetodosEntrega.comercios` and `Comercio.metodos_entrega` are forward-ref `relationship()` attributes using `back_populates`.**
The three models form a cycle (`Comercio ↔ ComercioMetodoEntrega ↔ MetodosEntrega`). All relationships use forward-ref strings (`"ComercioMetodoEntrega"`, `"MetodosEntrega"`, `"Comercio`"); no hard imports are added between the three files. This mirrors how `Producto.presentaciones ↔ ProductoPresentacion.producto ↔ Presentacion.productos_presentacion` is wired (Subphases 1.7 / 1.8 refinement).

**D10 — Relationship target class is `MetodosEntrega` (plural), matching the existing catalog class name.**
The user's snippet wrote `Mapped["MetodoEntrega"]` (singular) in the `metodo_entrega` relationship; the actual existing class is `MetodosEntrega` (plural) per `backend/models/metodos_entrega.py`. We use the existing class name to keep the model layer consistent; this is treated as a typo in the user's body, not a rename proposal.

**D11 — No `__repr__`, no validators, no extra `relationship()`.**
Per "Implement only what is explicitly requested" and "Avoid overengineering".

## Risks / Trade-offs

- **[Risk] A future migration applying the new constraints against a database with existing data could fail with constraint violations.** → Mitigation: documented. The join table is empty today; future audits can recheck before any migration runs.
- **[Risk] `ComercioMetodoEntrega.comercio` and `.metodo_entrega` both use `back_populates`, which requires that the partner attribute exists at import time on the partner class.** → Mitigation: both `Comercio.metodos_entrega` and `MetodosEntrega.comercios` are added in this same change; all three load simultaneously via `Base.metadata`.
- **[Risk] `ondelete="RESTRICT"` on `id_metodo_entrega` blocks catalog-row deletes forever.** → Mitigation: this is intentional. The operator must remove the join rows first. Documented behavior; matches `Producto.id_categoria_producto` and `Precio.id_producto_presentacion`.
- **[Trade-off] `orden` without default means every insert must supply it explicitly.** → Acceptable: explicit-design contract, matches `MetodosEntrega.orden`.
- **[Trade-off] New `activo` default (`False`) is asymmetric to `ProductoPresentacion.activo` (`True`).** → Acceptable: opt-in vs opt-out is a domain choice. Documented in D7.
- **[Trade-off] Three-way cycle through forward-ref strings.** → Acceptable: same pattern as `Producto ↔ ProductoPresentacion ↔ Presentacion`. No runtime or migration impact.

## Migration Plan

Not applicable in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`. That migration will need to create `comercio_metodos_entrega` (with both constraints) on both databases.

## Open Questions

- None for this subphase. The next subphases implied by the model:
  1. The Alembic revision that creates `comercio_metodos_entrega` on both `supernova` and `supenova_test`.
  2. Seed rows for `metodos_entrega` (`RETIRO_EN_LOCAL`, `DELIVERY_PROPIO`, `ENVIOS_CORREO`, …) with sensible `orden` values.
  3. The `ComercioMedioPago` join model that ties a commerce to the payment methods it accepts (parallel to this one).
  4. Per-comercio overrides on top of the global `MetodosEntrega` catalog (e.g., per-comercio `descripcion`) — if ever needed.
