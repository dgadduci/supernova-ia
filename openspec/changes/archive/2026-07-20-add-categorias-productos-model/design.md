## Context

Phase 1 / Subphase 1.5 introduces **CategoriasProductos** — the per-commerce product-category configuration table. Each `Comercio` records its own product-category descriptions, ordering and activation state inline (no FK to a global catalog table). The model carries the same general shape that other per-commerce child tables in the future will share (`id_comercio` + content columns + timestamps).

The user's spec wrote the FK target as `"comercios.id"` (plural). The `Comercio` table, as built in Subphase 1.2, used `__tablename__ = "comercio"` (singular). The user has confirmed that the rename to `comercios` is the correct direction; that rename also lands here so this subphase's FK targets a real table.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supenova` and test DB `supenova_test`; both will eventually contain `categorias_productos` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `CategoriasProductos` model whose column set exactly matches the user-supplied body.
- Declare the ForeignKey `id_comercio → comercios.id` with `ondelete="CASCADE"` and an index on the FK column.
- Re-export `CategoriasProductos` from `backend/models/__init__.py`.
- Mirror the established patterns: `default=True` + `server_default="true"` for `activo`; `default=0` + `server_default="0"` for `orden`; `server_default=func.now()` for timestamps with `onupdate=func.now()` on the modification column.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seed rows.
- A relationship from `Comercio` to `CategoriasProductos` (and a back-reference). Wiring that lands in a dedicated subphase.
- The `comercio` → `comercios` rename is included in this change because the FK target demands it; it is **not** listed under "goals" because it is a prerequisite correction, not a new feature.
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/categorias_productos.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in earlier subphases. `__tablename__ = "categorias_productos"`: snake_case plural Spanish, parallel to `medios_pago` (Subphase 1.3), `metodos_entrega` (Subphase 1.4), and the `comercios` table.

Alternatives considered:
- `comercios_categorias_productos` (parent-prefixed): more explicit about ownership but verbose. The `id_comercio` FK already documents ownership, so the prefix is redundant.
- `comercio_categorias_productos`: parent-prefixed with singular `comercio`. Inconsistent now that the parent table itself is plural (`comercios`).

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2, 1.3, 1.4 (and the user's spec). `EstadoComercio` (1.1) used `Column(…)`; the mixed style is preserved.

**D3 — FK target is `comercios.id`.**
Directly follows the user's literal spec and the confirmation that the parent table is now plural. The literal `ForeignKey("comercios.id", ondelete="CASCADE")` resolves at runtime against `Base.metadata.tables["comercios"]`.

**D4 — Rename `comercio` → `comercios` in Subphase 1.2.**
Already executed before this subphase started. The class name remains `Comercio` (the public identifier re-exported from `backend.models`); only the DB-level `__tablename__` switches from `"comercio"` to `"comercios"`. Anyone (humans or Alembic) reading the DB must use the plural form.

Alternatives considered for the rename:
- Do not rename; pick `comercio.id` (singular) FK in this subphase. **Rejected** by the user during the proposal phase — they confirmed the rename is the right direction.
- Repurpose `comercio_medios_pago` (the earlier mis-scoped attempt) as the canonical name. **Rejected**: the model is for product categories, not payment methods; the name mismatch would be permanently wrong.

**D5 — `ondelete="CASCADE"` on `id_comercio`.**
The user's spec explicitly requests cascade-on-delete. Rationale: per-commerce product categories have no meaning without the parent commerce. The DB enforces the invariant; applications cannot leave orphaned rows.

Alternatives considered:
- `ondelete="RESTRICT"`: would force callers to clean children manually; rejected as error-prone and verbose.
- `ondelete="SET NULL"`: leaves orphans that violate the table's intent; rejected.
- No `ondelete` (PostgreSQL default `NO ACTION`): rejected as weaker than `CASCADE`.

**D6 — Index on `id_comercio`.**
Common query pattern: "give me all categories for one commerce". The user supplied `index=True` on this column; we preserve it.

**D7 — Preserve `activo` with both `default=True` and `server_default="true"`.**
Mirrors Subphases 1.3 and 1.4. Python-side default for ORM inserts; server-default for raw SQL inserts and migrations.

**D8 — `orden` has both `default=0` and `server_default="0"`.**
Mirrors the pattern introduced earlier this session. DB-level default `"0"` is a string literal; PostgreSQL casts it to Integer automatically.

**D9 — Timestamp columns: `server_default=func.now()` and `onupdate=func.now()` on the modification column. No Python-side `default=`.**
Mirrors Subphases 1.2, 1.3, 1.4. The database owns these values; the ORM does not auto-populate them when the caller omits them.

**D10 — No `__repr__`, no validators, no `__table_args__`.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". No `CheckConstraint` is needed here (the user's spec does not require non-negative ordering — `MetodosEntrega` did, this one does not).

**D11 — No `relationship()` on `CategoriasProductos`.**
We deliberately omit `Mapped[Comercio] = relationship(Comercio)`. Wiring the relationship on both sides (and the corresponding back-reference) lands in a dedicated subphase. Until then, consumers dereference the FK by ID.

## Risks / Trade-offs

- **[Risk] Any code or migration referencing the old `comercio` table name breaks.** → Mitigation: the only consumers are subphases in this same conversation; no third-party impact. The class name `Comercio` is unchanged, so any Python import keeps working.
- **[Risk] Archived change snapshots are inconsistent with the live tablename.** → Mitigation: documented in `proposal.md`. Archives are historical planning artifacts; rewriting them would corrupt the audit trail. The live code and the main spec (which does not assert tablename anyway) are the authoritative source.
- **[Risk] Future per-commerce child tables will be tempted to use `__tablename__` (singular `comercio`) again.** → Mitigation: the FK target field in `proposal.md`/`design.md` is now `comercios.id`. Any future FK that mimics this template will point at the correct table.
- **[Risk] Without a `relationship()` on either side, consumers must join by `id_comercio` manually.** → Mitigation: acceptable for the model-only scope; a future subphase adds the relationship.
- **[Trade-off] Mixing SQLAlchemy declarative styles** (`Column(…)` in 1.1, `Mapped[…]` everywhere else). → Acceptable: same compile target.

## Migration Plan

Not applicable in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test` and create `categorias_productos` (and the prior tables) on both databases. It must also account for the `comercio` → `comercios` rename — specifically the existing `comercio` table must be `ALTER TABLE … RENAME TO comercios` (or recreated with the new name and data migrated, if Alembic has not yet been initialized).

## Open Questions

- **Per-commerce child-table pattern.** This subphase is the second iteration of the same per-commerce config pattern (the earlier `ComercioMediosPago` attempt was reverted). Future per-commerce child tables (delivery-method config, hours-of-operation, etc.) can either reuse this shape or specialize. Defer until a third child table is actually requested; the abstraction is not justified for only one or two occurrences.
- **Relationship wiring.** Add `Comercio.categorias_productos = relationship("CategoriasProductos", back_populates="comercio", cascade="all, delete-orphan", passive_deletes=True)` plus the back-reference on this model in a dedicated subphase.
- **Same question for delivery methods.** Whether `ComercioMetodoEntrega` mirrors `CategoriasProductos` (per-commerce config with inline `descripcion`/`orden`) or is a pure join to `metodos_entrega` (the global catalog from Subphase 1.4). Defer.
- **Database-level sanity check.** A `CHECK (orden >= 0)` constraint, like `MetodosEntrega` carries, is **not** here because the user's spec did not request one for `CategoriasProductos`. If negative `orden` is undesirable, raise it as a follow-up.
