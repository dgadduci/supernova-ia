## Context

Subphase 3.30 introduced `backend/scripts/cli_chat_client.py`, a stdlib-only Python CLI that drives a continuous conversation against the local FastAPI server through `urllib.request` and never imports any `backend.*` module. Subphase 3.30.1 extended the bootstrap (draft `Pedido` + `PUT /sessions/{id}/pedido`) and made the modern pipeline robust against stuck pending context. Subphase 3.30.2 is the next user-facing extension: after every successful order modification (currently `agregar_producto` and `quitar_producto`), the CLI must display the current draft `Pedido` as a terminal table so the operator can verify the committed state without leaving the CLI.

The existing `GET /pedidos/{pedido_id}/productos` endpoint returns `list[PedidoProductoResponse]`, which carries only `id_producto_presentacion` (a database id) for the product-presentation pair, not the human-readable product name or presentation description. A separate `GET /pedidos/{pedido_id}` returns the pedido scalars but no line items. Neither endpoint is enough to render a table that the operator can read. The project.md for 3.30.2 instructs: "Reuse an existing endpoint that returns the current draft Pedido and its product lines for the session created by the CLI" and "If no suitable read-only HTTP endpoint exists: Add only the smallest necessary production endpoint". A new minimal read-only endpoint is therefore the right answer, scoped to the strict layering established in Phase 2.

The CLI is already a strict HTTP-only client. The new feature must not weaken the import boundary, must not introduce a third-party table library, must not start the server, must not import any `backend.*` module, and must not hold the pedido state in local memory between calls. The table is reconstructed from a fresh HTTP read every time it is needed.

## Goals / Non-Goals

**Goals:**

- One new read-only production endpoint (`GET /pedidos/{pedido_id}/detalle`) following `Router → Service → Repository → SQLAlchemy`.
- New `PedidoDetalleResponse` schema exposing pedido scalars and a `lineas` array of `{cantidad, producto_nombre, presentacion_descripcion}` only (no database ids, no `precio_unitario`, no `observaciones`).
- CLI prints the customer-facing responses first, then `Pedido actual:` followed by a table or `Pedido actual: vacío`, only when at least one `CustomerResponse` in the list has `status == "executed"` and `intent in {"agregar_producto", "quitar_producto"}`.
- Pure helpers `response_modified_order(responses) -> bool` and `format_order_table(lineas) -> str`; module-level `ORDER_MUTATING_INTENTS` constant.
- Detail retrieval failure is non-fatal: warning printed, loop continues.
- Standard-library-only table formatting with dynamic column widths and `—` (em dash) fallback for missing/empty presentation descriptions.
- Strict import boundary preserved end-to-end.

**Non-Goals:**

- Implementing `modificar_producto` or any other new intent.
- Persisting pedido state in the CLI between calls.
- Introducing a third-party table library, a generic UI framework, a new dependency, or a new logging framework.
- Modifying the `agregar_producto` or `quitar_producto` contract, recognizer, processor, dispatcher, handler, resolver, or response builder.
- Modifying the incoming-messages endpoint, the session endpoints, the pedido endpoints, or the `pedido_producto` write endpoints.
- Adding a confirmation turn, a retry, a backoff, a WebSocket adapter, a Twilio adapter, or a queue worker.
- Adding a DB-level change, a model change, an Alembic migration, or a new column on `pedidos` / `pedidos_productos`.
- Reformatting the existing customer response lines (the `<- message=...` / `<- raw=...` contract stays unchanged).
- Surfacing internal fields (database ids, `precio_unitario`, `observaciones`) through the new endpoint.
- Exposing the detail endpoint over multiple HTTP verbs.

## Decisions

### D1. New endpoint at `GET /pedidos/{pedido_id}/detalle` on the existing `pedidos` router

**Decision.** Add the new handler to `backend/routers/pedidos.py` (no new router module, no new tag, no change to `backend/main.py`).

**Rationale.** The router already owns the pedido namespace; co-locating the read-only detail handler keeps the URL contract simple (`/pedidos/{pedido_id}/...`) and the router file small. The 3.30.1 review rejected the idea of a new `pedido-detalle` router module for the same reason: "the existing router is the right home for a read-only detail handler".

**Alternatives considered.** A new `backend/routers/pedido_detalle.py` router was rejected because the surface is one read-only handler, the URL is `/pedidos/{pedido_id}/detalle` (not a new prefix), and a separate router would not justify its own `__init__` / `main.py` registration. A sub-router mounted at `/pedidos/{pedido_id}` was rejected because it would require a second `APIRouter` and a `main.py` change without adding value.

### D2. New `PedidoDetalleResponse` and `PedidoDetalleLinea` in `backend/schemas/pedido.py`

**Decision.** Define two new Pydantic models in the existing `backend/schemas/pedido.py` (no new schema file):

- `PedidoDetalleLinea` carries `cantidad: int`, `producto_nombre: str`, `presentacion_descripcion: str`. Uses `from_attributes=True` so Pydantic can build it from the ORM `PedidoProducto` row plus its eagerly-loaded `producto_presentacion.producto.nombre` and `producto_presentacion.presentacion.descripcion`. No `id` field, no `precio_unitario`, no `observaciones`, no `id_producto_presentacion`.
- `PedidoDetalleResponse` carries the same scalar fields as `PedidoResponse` plus a `lineas: list[PedidoDetalleLinea]`. Composed via explicit field declarations (not inheritance) so the openAPI surface is stable and the "no extra fields" contract is self-evident.

**Rationale.** The spec calls for "use existing Pedido and PedidoProducto schemas where possible; avoid duplicating existing contracts; not expose unnecessary internal fields". Reusing the existing scalar set by composition keeps the openAPI surface easy to diff, and a dedicated `lineas` element type keeps the "no database ids" contract testable.

**Alternatives considered.** Inheriting `PedidoDetalleResponse(PedidoResponse)` was rejected because it would either expose unwanted fields or require hiding them with a `model_config` exclude. Extending `PedidoProductoResponse` with `producto_nombre` and `presentacion_descripcion` and reusing the existing `GET /pedidos/{pedido_id}/productos` endpoint was rejected because that endpoint is read by the existing tests with id-based assertions; adding fields there would be a contract change for callers that do not need them. A new schema file `pedido_detalle.py` was rejected because two new classes do not justify a third schema file in this domain.

### D3. `PedidoProductoRepository.list_by_pedido` extends the existing `joinedload` chain to also load `Presentacion`

**Decision.** The repository's `list_by_pedido` already does `joinedload(PedidoProducto.producto_presentacion).joinedload(ProductoPresentacion.producto)`. The chain gains one more `joinedload(ProductoPresentacion.presentacion)`. No new repository method; no new query path.

**Rationale.** The whole graph is loaded in a single query (the existing code uses `select(...).options(...).where(...).order_by(...)`); adding the `presentacion` join keeps the same single-query shape. There is no need for a separate `list_by_pedido_with_detalle` method.

**Alternatives considered.** A new `list_with_presentaciones` method was rejected because the existing `list_by_pedido` is only consumed by `list_pedido_productos` (router) and `get_for_pedido` (service); both call sites can benefit from the new join without behavior change (the eager-load only adds attributes to the loaded objects; existing tests that read scalar attributes are unaffected). A two-query approach (`select` for line items, then `select` for `Presentacion`) was rejected because it doubles the round-trips and the join is free at this cardinality.

### D4. New `PedidoService.get_detalle(pedido_id)` is read-only

**Decision.** `PedidoService.get_detalle(pedido_id)` calls `self._repo.get(pedido_id)` to load the `Pedido`; raises `PedidoNotFound` when missing. Then calls `self._pedido_producto_repo.list_by_pedido(pedido_id)` to load the line items. Returns the `(pedido, [PedidoProducto])` pair to the router. Performs no `commit`, `rollback`, `flush`, `refresh`, `expire`, or `begin`.

**Rationale.** The `PedidoService` already injects a `PedidoProductoRepository` (the same shape used in 3.31 for the `quitar_producto` work). The pair `(pedido, lineas)` is the smallest return value the router needs to build a `PedidoDetalleResponse`. The read-only contract is enforced by the absence of any `self._session.commit/rollback/flush/refresh/expire` call.

**Alternatives considered.** Composing the detail response inside the service (returning a `PedidoDetalleResponse` directly) was rejected because the existing service convention is "return ORM model instances; the router builds the response schema". A separate `PedidoDetalleService` was rejected because the responsibility belongs to `PedidoService` — the same service that owns `get_by_id` and the field updates.

### D5. `PedidoDetalleLinea` is built in the router from the ORM rows

**Decision.** The router iterates the list of `PedidoProducto` returned by the service and builds `PedidoDetalleLinea` instances directly via `PedidoDetalleLinea.model_validate(line)` (`from_attributes=True`). The router substitutes the literal `—` when `line.producto_presentacion.presentacion` is `None` or its `descripcion` is empty / whitespace-only.

**Rationale.** Building the schema in the router keeps the service free of Pydantic concerns and the `—` fallback close to the rendering contract. The em-dash fallback is a presentation concern, not a data-access concern.

**Alternatives considered.** Doing the `—` substitution in the service was rejected because the service should not know about presentation fallbacks. Doing it in the schema via a `field_validator` was rejected because the `—` literal is a CLI-rendering concern; a future API consumer may want a different fallback. Adding `presentacion` loading into the service and letting the schema do the substitution was rejected because the `—` literal would still need to live somewhere outside the schema, and the router is the natural home.

### D6. CLI module-level `ORDER_MUTATING_INTENTS = {"agregar_producto", "quitar_producto"}` and pure helper functions

**Decision.** The CLI gains three new top-level constructs, all exported through `__all__`:

- `ORDER_MUTATING_INTENTS = {"agregar_producto", "quitar_producto"}` — a frozen set literal; small enough to live at module scope.
- `def response_modified_order(responses) -> bool` — pure function: returns `True` iff at least one element of `responses` is a `dict` carrying `status == "executed"` and `intent in ORDER_MUTATING_INTENTS`. Ignores non-dict elements, missing keys, and any other status.
- `def format_order_table(lineas) -> str` — pure function: returns a single multi-line string. When `lineas` is empty, returns `"Pedido actual: vacío\n"`. Otherwise computes dynamic column widths from the headers and the values, falls back to `—` for empty/missing presentation description, renders a plain-text table with `+---+---+` borders, and ends with a single `\n`. Quantities are rendered as `str(int(cantidad))`; product names and presentation descriptions are rendered verbatim from the API response.

The `__main__` loop gains a new branch: after `_print_responses(payload)` returns and `response_modified_order(responses)` is `True`, the loop calls a new helper `_fetch_pedido_detalle(base_url, pedido_id)` and prints the table (or the warning). When `response_modified_order` is `False`, the loop continues as before.

**Rationale.** Splitting the trigger check (`response_modified_order`) from the rendering (`format_order_table`) from the IO (`_fetch_pedido_detalle`) keeps each piece unit-testable. Module-level `ORDER_MUTATING_INTENTS` makes the set of mutating intents a single grep target for future subphases. Both pure helpers have no imports beyond `str`/`builtins`, so the import-boundary test continues to pass.

**Alternatives considered.** A single `print_pedido_table(base_url, pedido_id, responses)` mega-function was rejected because the pure pieces would no longer be unit-testable in isolation. Adding `ORDER_MUTATING_INTENTS` as a parameter was rejected because the spec describes it as "easy to extend later through one constant" — a constant at module scope is the right shape. Using a third-party table library was rejected because the spec forbids it. Using `tabulate` or `prettytable` was rejected because the project does not have them installed and the spec explicitly says not to add a dependency for this.

### D7. Table format follows the example in the subphase spec

**Decision.** When the pedido is non-empty, the CLI prints, in order:

1. The literal line `Pedido actual:`.
2. A four-line header strip:
   - `+----------------------+-------------+----------+` (border widths computed dynamically)
   - `| Producto             | Presentación| Cantidad |`
   - `+----------------------+-------------+----------+`
3. One row per line item, in the order returned by the API: `| <producto_nombre padded> | <presentacion_descripcion padded> | <cantidad right-padded> |`.
4. A closing border strip matching the header.

Column widths are `max(len(header), max(len(value) for value in column)) + 2` (one space of padding on each side of the value). The rightmost column (`Cantidad`) is right-padded; the first two columns are left-padded. Quantities are rendered as integers (no `Decimal`, no thousands separator, no currency).

**Rationale.** This format matches the example in the project.md subphase definition (which uses `+---+---+` borders and `|` separators) and the project's "stdlib only" rule. Dynamic widths handle the "Column widths adapt to long product and presentation names" scenario without per-case code.

**Alternatives considered.** Using `str.format` with `{:<N}` and `{:>N}` was rejected because the column widths must be computed from the data first, then passed in. Using `f-string` padding (`f"| {name:<{w}} |"`) was accepted for the row rendering — it is the most readable way to express dynamic padding in Python. Using a `textwrap` based renderer was rejected because the structure is fixed (header / row / border) and dynamic widths do not need word-wrap logic.

### D8. Detail retrieval failure prints a single-line warning and the loop continues

**Decision.** `_fetch_pedido_detalle(base_url, pedido_id)` returns one of three values: `(200, dict_payload)`, `("warning", "...")`, or raises. The CLI's table branch:

- On `(200, dict_payload)`: builds a list of `lineas` from `payload["lineas"]` (defaulting to `[]` when missing) and prints either `Pedido actual: vacío` or the formatted table.
- On `("warning", message)`: prints `Warning: the order was modified, but its updated detail could not be retrieved.` followed by the message (HTTP status or API detail when available). Continues the loop. Does NOT close the session, does NOT exit non-zero, does NOT print "modification failed".
- On raised exception: same behavior as the `warning` branch, with the exception message used as the detail.

**Rationale.** The project.md spec is explicit: "Do not terminate the interactive message loop solely because the table lookup failed. Do not report that the modification failed when only the read-back request failed." A single-line warning preserves the operator's ability to keep iterating.

**Alternatives considered.** Treating a read failure as fatal was rejected by the spec. Re-trying the detail request was rejected because the spec says one retrieval per message. Falling back to the previous in-memory order state was rejected because the CLI is required to be stateless between calls.

### D9. `PedidoDetalleResponse` uses `extra="forbid"` on the line schema to enforce the "no database ids" contract at the OpenAPI level

**Decision.** `PedidoDetalleLinea` declares `model_config = ConfigDict(extra="forbid", from_attributes=True)`. `PedidoDetalleResponse` declares `model_config = ConfigDict(extra="forbid")` (no `from_attributes`; the router builds it from explicit kwargs).

**Rationale.** `extra="forbid"` is the project-wide pattern for request / response schemas that must not carry unexpected fields (see Subphase 2.2 `EstadoComercioCreate`). It catches accidental additions during review (a future contributor cannot slip a database id into the response without breaking every consumer).

**Alternatives considered.** Using only the `from_attributes=True` pattern was rejected because the OpenAPI surface would not be locked. Adding a manual "no `id_` keys" validator was rejected because `extra="forbid"` already achieves that — Pydantic raises if any non-declared attribute is set during construction.

## Risks / Trade-offs

- **Single new endpoint increases the API surface.** The endpoint is read-only, scoped to a single resource, and follows the established layering; future contributors are unlikely to misuse it. The "no database ids in the response" contract is enforced by `extra="forbid"` and the spec. → Mitigation: the spec explicitly documents the contract, the schema enforces it at the Pydantic layer, and the test suite asserts the response shape contains no `id_*` keys.

- **Adding `joinedload(ProductoPresentacion.presentacion)` to the existing `list_by_pedido` could change the shape of the existing `GET /pedidos/{pedido_id}/productos` response.** Pydantic with `from_attributes=True` reads only the declared fields, so the new eager-load adds attributes that the existing schema ignores; the response is byte-for-byte identical for the existing schema. → Mitigation: the existing `PedidoProductoResponse` does not declare `presentacion_descripcion`, so the new join is invisible to its serialization. The new endpoint is what surfaces the new fields.

- **CLI's `format_order_table` is tested with synthetic inputs, not real API responses.** If the API shape ever drifts (e.g. `lineas` key renamed), the CLI would silently print an empty table. → Mitigation: the new endpoint spec pins the response shape; the CLI asserts the response is a dict and that `lineas` is a list; the warning branch catches unexpected shapes.

- **Detail retrieval adds one extra HTTP round-trip per executed mutation.** The CLI already makes one POST per typed line; adding one GET adds ~10ms of latency on a localhost server. → Mitigation: the spec explicitly chose HTTP over local state recomputation; a single GET is cheaper than the alternative (maintaining local state with reconciliation logic).

- **`ORDER_MUTATING_INTENTS = {"agregar_producto", "quitar_producto"}` does not yet include `modificar_producto`.** The spec for 3.30.2 forbids implementing it. → Mitigation: the constant is module-level and the comment in the code references this subphase; a future subphase that adds `modificar_producto` will extend the set in one place.

- **The `—` fallback for missing presentation description is hard-coded in the CLI rendering.** A future API consumer that prefers `""` or `null` would diverge. → Mitigation: the spec defines the fallback explicitly; the endpoint returns the literal em-dash so the CLI does not need to do the substitution; future API consumers that need a different fallback can either request an additional query parameter or build their own client.

- **Test coverage is split between focused CLI tests (mocked HTTP) and the manual acceptance scenarios in the project.md.** A regression in the integration between CLI and endpoint could go undetected. → Mitigation: the focused CLI tests assert the response shape, the count of HTTP calls, and the printed output; the manual acceptance scenario in the project.md is run by the operator before archiving the change (the same pattern used in 3.30 and 3.30.1).

## Migration Plan

This change is purely additive on the server side (one new GET handler) and purely additive on the client side (one new print branch). There is no DB migration, no model change, no Alembic revision, and no rollback concern beyond reverting the four modified files.

- **Deploy order:** no order dependency. The new endpoint is only consumed by the CLI; any running CLI version ignores it.
- **Rollback strategy:** revert the four modified files (`backend/routers/pedidos.py`, `backend/services/pedido_service.py`, `backend/repositories/pedido_producto_repository.py`, `backend/schemas/pedido.py`, `backend/scripts/cli_chat_client.py`) and the new tests. No DB rollback is needed; the new endpoint did not write anything.
- **Cutover:** none. The CLI prints the new table from the first run after the change lands.

## Open Questions

None. All decisions are pinned by the project.md subphase spec, the existing 3.30 / 3.30.1 constraints, and the Phase 2 / Phase 3 layering rules.
