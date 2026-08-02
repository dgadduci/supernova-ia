## Context

The model layer of supernova-ia is being built up in small, single-purpose subphases. Subphase 1.9 just landed `ComercioMetodoEntrega` (the per-comercio selection from the `MetodosEntrega` catalog) and closed the corresponding two deferred relationships on `Comercio` and `MetodosEntrega`. **Subphase 1.10** is the payment-side parallel: it introduces `ComercioMedioPago`, the per-comercio payment-method row, and re-introduces the previously-missing `Comercio.medios_pago` and `MediosPago.comercios` relationships.

The change is the minimum required by the user's body: no extra indexes beyond the FKs, no denormalization, no service layer, no migration. The new invariant (composite uniqueness over `(id_comercio, id_medio_pago)`) follows the same pattern already used by `ComercioMetodoEntrega` (Subphase 1.9). Two **per-comercio** metadata columns (`titular`, `alias`) carry operator-facing display info that does not belong on the global `MediosPago` catalog; both are nullable, since not every medio de pago needs both (e.g., cash on delivery has no titular; a generic alias suffices for others).

**Important delta from 1.9:** this join has **no `orden` column** and therefore **no `CheckConstraint`**. Payment methods are not displayed in a sorted list in the same way delivery methods are; if display ordering is needed later it can be added in a refinement subphase. Keeping the schema minimal matches the user-supplied body and the "Implement only what is explicitly requested" rule from `openspec/specs/AGENTS.md`.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supernova` and test DB `supenova_test`; both will eventually contain `comercio_medios_pago` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `ComercioMedioPago` model whose column set exactly matches the user-supplied body.
- Declare a `UniqueConstraint` named `comercio_medio_pago_unico` enforcing `(id_comercio, id_medio_pago)` uniqueness, attached via `__table_args__`.
- Re-export `ComercioMedioPago` from `backend/models/__init__.py`.
- Re-introduce `Comercio.medios_pago` and `MediosPago.comercios` as forward-ref `relationship()` attributes using `back_populates`.
- Keep the surface area minimal: no `__repr__`, no validators, no extra indexes, no service layer.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seed rows for `medios_pago` (`EFECTIVO`, `TRANSFERENCIA_BANCARIA`, `MERCADO_PAGO`, …) and seed join rows.
- An `orden` column or any display-ordering invariant.
- Payment-method-type discriminator (debit / credit / wallet / cash / …).
- CVU / CBU / alias-specific metadata columns beyond the user-supplied `titular` and `alias` (no banking-detail storage here — that lives elsewhere when needed).
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/comercio_medios_pago.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in Subphases 1.1–1.10: one purpose per file under `backend/models/`, `__init__.py` re-exports.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2–1.9 and the user's spec. `EstadoComercio` in 1.1 used `Column(…)`; the mixed style is preserved without modification.

**D3 — Class name `ComercioMedioPago` (singular) and `__tablename__ = "comercio_medios_pago"` (plural) exactly as supplied.**
The class is singular (mirrors `ComercioMetodoEntrega`, `ProductoPresentacion`); the table is plural-as-collection (mirrors `comercio_metodos_entrega`, `producto_presentaciones`). Snake_case Spanish matches every other table in the model layer. The user supplied `__tablename__` as `"comercio_medios_pago"` (plural) — we honor it verbatim.

**D4 — `__table_args__` contains only the composite unique constraint.**
```python
__table_args__ = (
    UniqueConstraint("id_comercio", "id_medio_pago", name="comercio_medio_pago_unico"),
)
```
No `CheckConstraint` — there is no `orden` (or other numeric) column to constrain. Mirrors the user's body exactly; matches the "implement only what is requested" rule.

**D5 — `id_comercio` FK uses `ondelete="CASCADE"`.**
When a `Comercio` is deleted, its per-comercio join rows go with it. This mirrors `CategoriaProducto.id_comercio`, `Presentacion.id_comercio`, and `ComercioMetodoEntrega.id_comercio` (all `CASCADE`). Semantically: a join row is an extension of its parent comercio, not an independent entity.

**D6 — `id_medio_pago` FK uses `ondelete="RESTRICT"`.**
A catalog row from `MediosPago` cannot be deleted while any commerce still references it through the join. This mirrors `ComercioMetodoEntrega.id_metodo_entrega`, `Producto.id_categoria_producto`, and `Precio.id_producto_presentacion` (all `RESTRICT`): the child FK should outlive its parent. Semantically: removing a catalog row is a destructive administrative action that should fail loudly if any commerce is still using it.

**D7 — `activo` carries `default=False` AND `server_default="false"`.**
This matches `ComercioMetodoEntrega.activo` (Subphase 1.9): a new join row is **opt-in** (the comercio must explicitly enable each payment method). Python-side default for ORM inserts; server-side default for raw SQL inserts and migrations.

**D8 — `titular` and `alias` are nullable String columns, no defaults.**
The user supplied them as `Mapped[str | None]` with `nullable=True`. These are operator-facing display fields (account-holder name, short alias) that not every medio de pago requires (cash on delivery has no titular). No `default=` / `server_default=` — leaving them `NULL` is a valid state.

- `titular`: `String(150)`, nullable. Max length matches the longest business profile field (`Comercio.nombre_fantasia` = 150) for visual consistency.
- `alias`: `String(100)`, nullable. Shorter than `titular` because aliases are intended to be short operator-facing labels.

**D9 — No `orden`, no `CheckConstraint`.**
Explicit: the user's body does not include `orden`, and we follow "implement only what is explicitly requested". If display ordering becomes needed, it lands in a future refinement subphase.

**D10 — `MediosPago.comercios` and `Comercio.medios_pago` are forward-ref `relationship()` attributes using `back_populates`.**
The three models form a cycle (`Comercio ↔ ComercioMedioPago ↔ MediosPago`). All relationships use forward-ref strings (`"ComercioMedioPago"`, `"MediosPago"`, `"Comercio"`); no hard imports are added between the three files. This mirrors how `Producto.presentaciones ↔ ProductoPresentacion.producto ↔ Presentacion.productos_presentacion` is wired (Subphases 1.7 / 1.8) and `Comercio.metodos_entrega ↔ ComercioMetodoEntrega.comercio ↔ MetodosEntrega.comercios` is wired (Subphase 1.9).

**D11 — Relationship target class is `MediosPago` (plural), matching the existing catalog class name.**
The user's snippet wrote `Mapped["MedioPago"]` (singular) in the `medio_pago` relationship; the actual existing class is `MediosPago` (plural) per `backend/models/medios_pago.py`. We use the existing class name to keep the model layer consistent; this is treated as a typo in the user's body, not a rename proposal.

**D12 — No `__repr__`, no validators, no extra `relationship()`.**
Per "Implement only what is explicitly requested" and "Avoid overengineering".

## Risks / Trade-offs

- **[Risk] A future migration applying the new constraint against a database with existing data could fail with constraint violations.** → Mitigation: documented. The join table is empty today; future audits can recheck before any migration runs.
- **[Risk] `ComercioMedioPago.comercio` and `.medio_pago` both use `back_populates`, which requires that the partner attribute exists at import time on the partner class.** → Mitigation: both `Comercio.medios_pago` and `MediosPago.comercios` are added in this same change; all three load simultaneously via `Base.metadata`.
- **[Risk] `ondelete="RESTRICT"` on `id_medio_pago` blocks catalog-row deletes forever.** → Mitigation: this is intentional. The operator must remove the join rows first. Documented behavior; matches the same pattern in 1.9 (`ComercioMetodoEntrega.id_metodo_entrega`).
- **[Trade-off] Two nullable metadata columns (`titular`, `alias`) on every join row whether used or not.** → Acceptable: payment methods commonly need at least one of these; `NULL` is a valid state, and storage cost is negligible.
- **[Trade-off] No `orden` column means the join has no built-in display ordering.** → Acceptable: explicit-design choice (D9). If display ordering becomes needed, add in a refinement subphase.
- **[Trade-off] Three-way cycle through forward-ref strings.** → Acceptable: same pattern as `Producto ↔ ProductoPresentacion ↔ Presentacion` and `Comercio ↔ ComercioMetodoEntrega ↔ MetodosEntrega`. No runtime or migration impact.

## Migration Plan

Not applicable in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`. That migration will need to create `comercio_medios_pago` (with the composite unique constraint) on both databases.

## Open Questions

- None for this subphase. The next subphases implied by the model:
  1. The Alembic revision that creates `comercio_medios_pago` on both `supernova` and `supenova_test`.
  2. Seed rows for `medios_pago` (`EFECTIVO`, `TRANSFERENCIA_BANCARIA`, `MERCADO_PAGO`, …).
  3. An optional display-order refinement (add `orden` column + `CheckConstraint`) if/when the frontend needs sorted payment-method lists — pattern would mirror `ComercioMetodoEntrega` (1.9).
  4. Payment-method-type discriminator (debit / credit / wallet / cash) if business logic needs to distinguish them.
