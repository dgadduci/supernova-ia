## Context

Phase 3 (Intents) is now in the "router" layer: subphase 3.7 introduced the persistence surface for `PendingIntents`. The next piece is the vocabulary that the dispatch path will use to route a `Session`'s resolution flow. A `Session` running through the `agregar_producto` resolver is in a different "context" from one running through a future `cerrar_pedido` resolver. The future dispatch path will read the session's current `context_type` to pick the right recognizer / processor / handler chain. This subphase introduces the closed set of `ContextType` values — the smallest, narrowest declaration that lets a future subphase reference the values without inventing them ad hoc.

## Goals / Non-Goals

**Goals:**

- Create `backend/sessions/enums/context_type.py` exporting a single `ContextType` enum (a `StrEnum`) and a `__all__`.
- `ContextType` declares exactly one value: `PRODUCT_SELECTION = "product_selection"`.
- The file is importable: `from backend.sessions.enums.context_type import ContextType` works without side effects.
- One test asserts the enum value, string compatibility (`ContextType.PRODUCT_SELECTION == "product_selection"`), and rejection of an invalid value.

**Non-Goals:**

- No `backend/sessions/enums.py` (the spec mandates a *package* with `__init__.py`, not a single module). No shortcuts.
- No other enum values (e.g. `CART_REVIEW`, `CHECKOUT`, `CUSTOMER_SUPPORT`). One value per subphase.
- No model, no migration, no router, no FastAPI endpoint, no service code, no business logic, no validation framework.
- No `context_type` column on the `Session` model — that lands in a future subphase. The enum exists before the column does.

## Decisions

- **D1 — `ContextType` is a `StrEnum`, not a plain `Enum`.** `StrEnum` (Python 3.11+) gives string equality for free: `ContextType.PRODUCT_SELECTION == "product_selection"`. This is consistent with the earlier `EstadoPedido` and `EstadoSession` patterns in the project (those are `enum.Enum`, not `StrEnum`; future subphases may migrate them, but that's out of scope). For a context identifier that is persisted as a string, `StrEnum` is the right choice today.
- **D2 — Single value: `PRODUCT_SELECTION`.** The spec mandates exactly this one value. Future subphases will add new values to the same enum (e.g. `CART_REVIEW`). The active subphase does not preempt those — no placeholder values, no forward-declared "reserved" values.
- **D3 — Module location: `backend/sessions/enums/context_type.py`.** The spec mandates the path. The package structure (`backend/sessions/` with `enums/`, `models/`, `services/`, `routers/`, etc. to come) follows the project's existing convention (e.g. `backend/intents/{contracts,schemas,services}/`).
- **D4 — `__all__` is declared.** The only public symbol is `ContextType`. Mirrors the prior subphases' `__all__` discipline.
- **D5 — File is pure data.** No imports of `Session`, no imports of any other module. The enum is self-contained.

## Risks / Trade-offs

- **[Risk] Python <3.11 does not have `StrEnum`.** The project runs on Python 3.14 (per the venv). The test environment is also 3.14. → Acceptable: the project requires Python 3.11+ today.
- **[Trade-off] Only one enum value today.** A future subphase that adds a second value (e.g. `CART_REVIEW`) will append to the same enum; existing values do not change. Serialized form stays backward-compatible.

## Open Questions

- None. The enum value, the path, the `StrEnum` choice, and the "no other values / no business logic" rule are all fixed by Subphase 3.8 in `project.md`.