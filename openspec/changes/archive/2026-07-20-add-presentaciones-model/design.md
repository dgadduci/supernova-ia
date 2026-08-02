## Context

Phase 1 / Subphase 1.6 introduces **Presentacion** — the per-commerce product-presentation table. The five reference-data tables already in `Base.metadata` (`comercios`, `estado_comercio`, `medios_pago`, `metodos_entrega`, `categorias_productos`) and the first per-commerce child table (`categorias_productos`, Subphase 1.5) lead up to this model, which adds the richest set of table-level invariants yet: two composite `UniqueConstraint`s and one `CheckConstraint`, alongside the standard per-commerce child columns.

This subphase introduces three new patterns to the model layer:

1. **Composite `UniqueConstraint`s.** Two of them — one over `(id_comercio, codigo)`, one over `(id_comercio, descripcion)`. They enforce per-comercio uniqueness (codes and descriptions may legitimately repeat across different comercios) without requiring `unique=True` on the column itself.
2. **A second `CheckConstraint`.** Mirrors `MetodosEntrega`'s `orden_no_negativo`. PostgreSQL scopes constraint names per-table, so two tables can each carry a constraint with the same logical name without conflict.
3. **A composite-`id_comercio`-style FK with cascade.** Same pattern as Subphases 1.5 and 1.6-precedent — the parent's existence is a precondition for the child row's existence.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supenova` and test DB `supenova_test`; both will eventually contain `presentaciones` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `Presentacion` model whose column set exactly matches the user-supplied body.
- Declare `__table_args__` with the three table-level constraints, exactly as supplied (names verbatim, including the singular `presentacion` portion in the constraint names).
- Re-export `Presentacion` from `backend/models/__init__.py`.
- Mark `id_comercio` indexed for join performance.
- Mirror the established default patterns: `default=True` + `server_default="true"` for `activo`; `default=0` + `server_default="0"` for `orden`; `server_default=func.now()` for timestamps with `onupdate=func.now()` on the modification column.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seed rows.
- A `relationship()` from `Comercio` to `Presentacion` (deferred to a dedicated subphase).
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/presentaciones.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in earlier subphases. `__tablename__ = "presentaciones"`: snake_case plural Spanish, parallel to `medios_pago`, `metodos_entrega`, `categorias_productos`, and the `comercios` table.

Alternatives considered:
- `comercios_presentaciones` (parent-prefixed): more explicit about ownership but verbose. The FK and `id_comercio` already document ownership.
- `comercio_presentacion` (singular prefix): inconsistent now that the parent table is plural.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2, 1.3, 1.4, 1.5 and the user's spec. `EstadoComercio` (1.1) used `Column(…)`; the mixed style is preserved.

**D3 — FK target is `comercios.id`.**
Directly follows the user's literal spec. The literal `ForeignKey("comercios.id", ondelete="CASCADE")` resolves at runtime against `Base.metadata.tables["comercios"]`.

**D4 — `ondelete="CASCADE"` on `id_comercio`.**
The user's spec explicitly requests cascade-on-delete. Rationale: per-commerce presentations have no meaning without the parent commerce.

Alternatives considered:
- `ondelete="RESTRICT"`: rejected — would force callers to clean children manually.
- `ondelete="SET NULL"`: rejected — leaves orphans that violate the table's intent.
- No `ondelete`: rejected — weaker than CASCADE.

**D5 — Index on `id_comercio`.**
Common query pattern: "give me all presentations for one comercio". The user supplied `index=True`; preserved.

**D6 — Composite `UniqueConstraint`s with the user-supplied names.**
We declare two composite uniques — `(id_comercio, codigo)` and `(id_comercio, descripcion)` — named exactly as the user supplied: `comercio_presentacion_codigo_unico` and `comercio_presentacion_descripcion_unica`.

Note on naming: the constraint names use the singular form `presentacion` while the table is plural `presentaciones`. SQLAlchemy stores these as opaque identifiers; PostgreSQL scopes constraint names per-table, so no collision is possible. We preserve the user-supplied spellings verbatim. A future housekeeping pass could normalize the names, but it is out of scope.

Alternatives considered:
- `unique=True` on the `codigo` column alone: rejected — would forbid two different comercios from using the same `codigo` (e.g., both defining `KILO_1`). The composite constraint explicitly allows that.
- A class-level `__table_args__ = (UniqueConstraint("id_comercio", "codigo"), UniqueConstraint("id_comercio", "descripcion"), CheckConstraint("orden >= 0"))` (no names): rejected — the user supplied explicit names; auto-generated names collide with human-readable naming conventions and are harder to reference in migrations and error messages.

**D7 — `CheckConstraint("orden >= 0", name="orden_no_negativo")`.**
Mirrors `MetodosEntrega` (1.4). Constraint names are per-table in PostgreSQL, so the same logical name can exist on multiple tables.

**D8 — Preserve all column defaults as supplied.**
- `activo`: `Boolean`, `default=True`, `server_default="true"`.
- `orden`: `Integer`, `default=0`, `server_default="0"`.
- `fecha_alta` / `fecha_ultima_modificacion`: timezone-aware DateTime, `server_default=func.now()`, no Python-side `default=`; the latter additionally carries `onupdate=func.now()`.

**D9 — No `__repr__`, no validators, no `relationship()`.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". The future relationship from `Comercio` lands in a dedicated subphase.

## Risks / Trade-offs

- **[Risk] Per-comercio uniqueness is enforced at the database level; an application inserting an orphan row hits a constraint violation.** → Mitigation: acceptable. Constraint violations are a clear failure mode and easy to surface in error reporting. The alternative (validating in the application) is bypassable by raw inserts.
- **[Risk] PostgreSQL names the underlying unique indexes after the constraint by default; if a future migration needs to drop just the index, it must target it explicitly.** → Mitigation: documented as a consideration for the future migration subphase.
- **[Risk] Constraint names carry the singular `presentacion` while the class/table are plural.** → Mitigation: this aligns the class to the singular form during this change. The remaining mismatch is that the table remains plural (`presentaciones`). Out of scope for this subphase.
- **[Trade-off] Mixing SQLAlchemy declarative styles** (`Column(…)` in 1.1, `Mapped[…]` everywhere else). → Acceptable: same compile target.

## Migration Plan

Not applicable. No migration is generated, applied, or rolled back in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test` and create the table on both databases.

## Open Questions

- **Relationship wiring.** Add `Comercios.presentaciones = relationship("Presentacion", back_populates="comercio", cascade="all, delete-orphan", passive_deletes=True)` plus the back-reference on `Presentacion`. Land in a dedicated subphase.
- **Same per-commerce child pattern.** `CategoriasProductos` (1.5) does not carry uniqueness constraints; this model does. If future per-commerce child tables need composite uniqueness, the current `__table_args__` pattern scales. Defer until a third child table is requested.
- **Constraint name normalization.** After the in-progress rename to singular `Presentacion`, only the table name (`presentaciones`, plural) and the relationship endpoints remain in plural. Out of scope for this subphase. A future housekeeping pass could rename the table to `presentacion` if full singular consistency is desired.
- **`ComercioMetodoEntrega`.** Open question carried from earlier: whether delivery methods follow the per-commerce config pattern (as in 1.5 / 1.6) or are a join to the global catalog. Defer.
