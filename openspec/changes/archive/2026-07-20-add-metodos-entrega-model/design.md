## Context

The SQLAlchemy model layer of supernova-ia is being built up in small, single-purpose subphases. Subphase 1.1 introduced `estado_comercio` and the shared `Base`. Subphase 1.2 added `Comercio` (with `estado_id` FK to `estado_comercio`). Subphase 1.3 added `MediosPago` (payment-method catalog). **Subphase 1.4** continues the catalog pattern with **MetodosEntrega** — the reference table that holds the delivery methods a commerce can offer.

A small but important historical detail: the user's original Subphase 1.2 spec for `Comercio` ended with a relationship that pointed to a class called `ComercioMetodoEntrega` (a join table). At that time, neither `MetodosEntrega` (this subphase's catalog) nor `ComercioMetodoEntrega` (the join) existed, so the relationship was deferred. This subphase introduces the catalog only. The join table — and the re-introduction of the `Comercio.metodos_entrega` relationship — remain out of scope here.

The new concept introduced in this subphase is a **table-level `CheckConstraint`**, declared through `__table_args__`. This is a database-side invariant (not just a Python-side check), making it the first model in the layer that uses a non-`CheckConstraint`-less schema. The constraint is purely defensive: `orden >= 0`, ensuring the `orden` column (used to sort/display delivery methods) never stores negative values.

Constraints inherited from the project context (`openspec/specs/project.md`, `openspec/specs/AGENTS.md`):

- Code lives under purpose-specific subdirectories of `backend/` (here: `backend/models/`).
- Implement only what is explicitly requested.
- Dev DB `supernova` and test DB `supenova_test`; both will eventually contain `metodos_entrega` once a future subphase configures Alembic.
- No migration, no service, no API, no seed data in this change.

## Goals / Non-Goals

**Goals:**

- Provide a SQLAlchemy `MetodosEntrega` model whose column set exactly matches the user-supplied body.
- Declare a `CheckConstraint` named `orden_no_negativo` enforcing `orden >= 0`, attached via `__table_args__`.
- Re-export `MetodosEntrega` from `backend/models/__init__.py`.
- Mark `codigo` unique + indexed.
- Keep the surface area minimal: no `__repr__`, no validators, no relationships.

**Non-Goals:**

- Alembic migrations (a separate subphase).
- Seed rows (`RETIRO_EN_LOCAL`, `DELIVERY_PROPIO`, `ENVIOS_CORREO`, etc.).
- The `ComercioMetodoEntrega` join table.
- Re-introduction of the `Comercio.metodos_entrega` relationship.
- Any service, repository, API endpoint, or DTO layer.

## Decisions

**D1 — File: `backend/models/metodos_entrega.py` and re-export from `backend/models/__init__.py`.**
Per the convention established in Subphases 1.1 / 1.2 / 1.3: one purpose per file under `backend/models/`, `__init__.py` re-exports.

**D2 — ORM style: SQLAlchemy 2.0 typed declarations (`Mapped[…]` + `mapped_column(…)`).**
Matches Subphases 1.2 and 1.3 (and the user's spec). `EstadoComercio` in 1.1 used `Column(…)`; the mixed style is preserved without modification.

**D3 — `__tablename__ = "metodos_entrega"` exactly as supplied.**
Spanish snake-case matches `medios_pago`, `estado_comercio`, `comercio`. No English pluralization rule applied.

**D4 — Table-level `CheckConstraint` declared in `__table_args__`.**
```python
__table_args__ = (
    CheckConstraint("orden >= 0", name="orden_no_negativo"),
)
```
We use SQLAlchemy's `CheckConstraint` constructor with a raw SQL expression and an explicit constraint name. The expression is portable to PostgreSQL (the project's dev/test DB) without dialect-specific quoting.

Alternatives considered:
- Python-side `validates` decorator: rejected — won't catch inserts that bypass the ORM (raw SQL, migrations, psql). A DB-side check is the only guarantee.
- `Integer` column with `CheckConstraint` declared inline: rejected — PostgreSQL would accept it, but listing the constraint in `__table_args__` keeps the model body readable and matches the canonical SQLAlchemy 2.0 pattern.
- A domain-level validator (`if orden < 0: raise`): rejected — same bypass problem as the `validates` decorator.

**D5 — Preserve `activo` with both `default=True` and `server_default="true"`.**
Same pattern as Subphase 1.3 (`MediosPago`): Python-side default for ORM inserts, server-default for raw SQL inserts and migrations.

**D6 — Preserve all other column constraints exactly as supplied.**

- `codigo`: `String(50)`, `nullable=False`, `unique=True`, `index=True` — natural lookup key.
- `descripcion`: `String(100)`, `nullable=False` — human-readable label.
- `orden`: `Integer`, `nullable=False` — sorting key; constrained non-negative by D4.
- `fecha_alta` / `fecha_ultima_modificacion`: timezone-aware DateTime, `server_default=func.now()`; the latter additionally carries `onupdate=func.now()`. No Python-side `default=` (database owns them, mirroring Subphases 1.2 and 1.3).

**D7 — No `__repr__`, no validators, no relationships.**
Per "Implement only what is explicitly requested" and "Avoid overengineering". The model's consumer (a future join-table subphase) will declare its own relationship.

## Risks / Trade-offs

- **[Risk] `orden` is non-null and has no default — every insert must supply it explicitly.** → Mitigation: not a problem today (no inserts happen before migrations and seeding land). Future subphases that seed catalog rows must always set `orden`. This is the intended explicit-design contract.
- **[Risk] Consumers may try to add a relationship from `Comercio` to `MetodosEntrega` directly, bypassing `ComercioMetodoEntrega`.** → Mitigation: documented in `proposal.md` and `design.md` (this document). The deferred `Comercio.metodos_entrega` was always pointing at a join table, not the catalog. Adding a direct relationship before the join table exists would skip the "which methods this commerce accepts" semantics that the join table provides. We deliberately leave this absent.
- **[Risk] `CheckConstraint` requires raw SQL; if someone changes the column name later the SQL string silently drifts.** → Mitigation: the constraint name (`orden_no_negativo`) is descriptive and the column name (`orden`) is short; future changes should update both together. We do not auto-generate the SQL from a Python expression.
- **[Trade-off] Mixing SQLAlchemy declarative styles** (`Column(…)` in 1.1, `Mapped[…]` in 1.2, 1.3, and here). → Acceptable: both compile to the same `Table` metadata; no runtime or migration impact.

## Migration Plan

Not applicable. No migration is generated, applied, or rolled back in this change. A dedicated migration subphase will run later against `supernova` and `supenova_test`.

## Open Questions

- None for this subphase. The next subphases implied by the model:
  1. The Alembic revision that creates `metodos_entrega` (and `estado_comercio`, `comercio`, `medios_pago`) on both `supernova` and `supenova_test`.
  2. Seed rows for `metodos_entrega` (`RETIRO_EN_LOCAL`, `DELIVERY_PROPIO`, `ENVIOS_CORREO`, …) with sensible `orden` values.
  3. The `ComercioMetodoEntrega` join model that ties a commerce to the delivery methods it accepts, plus the re-introduction of `Comercio.metodos_entrega` as a relationship to that join table.
