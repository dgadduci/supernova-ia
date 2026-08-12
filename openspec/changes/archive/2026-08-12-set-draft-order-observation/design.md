# Design: set draft-order observation

## Authoritative outcomes

| Pre-condition on the session/pedido | Normalized text length | Processed status | Persisted effect on `pedidos.observaciones` | Safe response meaning |
| --- | --- | --- | --- | --- |
| No `session.id_pedido` or row missing | any | `rejected` (`no_draft`) | None | No hay pedido activo para anotar. |
| `Pedido.id_session != session.id` | any | `rejected` (`session_mismatch`) | None | No se pudo guardar la observación. |
| `pedido.estado_pedido != BORRADOR` | any | `rejected` (`pedido_not_borrador`) | None | El pedido ya no se puede modificar. |
| All pre-conditions satisfied | `0` (empty / whitespace only) | `rejected` (`text_empty`) | preserved | No se pudo guardar la observación. |
| All pre-conditions satisfied | `> 500` | `rejected` (`text_too_long`) | preserved | No se pudo guardar la observación. |
| All pre-conditions satisfied | `1..500` | `executed` | replaced with the normalized text | Listo, guardé tu observación. |

The "preserved" rows mean the column keeps its prior value (which may
be `NULL` or a prior accepted text). The "replaced" row means the
column takes the new normalized text in the caller's transaction. The
"safe response meaning" column is the rendered Spanish
`CustomerResponse.message`; it never includes the raw or normalized
observation text, the pedido id, the session id, the cliente/comercio
ids, or any internal exception text.

## Runtime decision logic

```
process_initial_set_observacion_pedido(db, session, source_text):
    pedido = _load_session_pedido(db, session)
    if pedido is None:
        return _rejected("no_draft")

    if pedido.id_session != session.id:
        return _rejected("session_mismatch")

    if pedido.estado_pedido != BORRADOR:
        return _rejected("pedido_not_borrador")

    text = _normalize_observacion(source_text)
    length = len(text)
    if length == 0:
        return _rejected("text_empty")
    if length > 500:
        return _rejected("text_too_long")

    pedido.observaciones = text
    return ProcessedIntent(
        intent="set_observacion_pedido",
        source_text=source_text,
        status="executed",
        recognizer="draft_order_closure",
        handler="set_observacion_pedido",
        resolved_data={"accepted_length": length},
    )
```

`_normalize_observacion(text)`:

1. Apply `unicodedata.normalize("NFKC", text)` to fold compatibility
   forms (e.g. full-width spaces, ligatures) to their canonical
   decomposition.
2. `strip()` the result via `.strip()` (Python's built-in
   `str.strip()` is Unicode whitespace aware: it removes all leading
   and trailing code points classified as whitespace by
   `unicodedata.category`).
3. Collapse internal whitespace with a Unicode-aware regex
   (`re.sub(r"\s+", " ", text, flags=re.UNICODE)`). Python's `\s`
   in `re.UNICODE` mode matches every Unicode whitespace code point
   (ASCII space, tab, CR, LF, FF, VT, non-breaking space
   U+00A0, narrow no-break space U+202F, ideographic space U+3000,
   etc.) so mixed scripts collapse consistently.

The function never trims to 500, never strips courtesies, never
removes diacritics, and never lowercases. The length is measured in
Python code points after normalization; the change does **not** count
grapheme clusters. The cap is inclusive (`<= 500` is accepted, `> 500`
is rejected).

## Valid business outcomes

* `executed` with `accepted_length` in `1..500` — the column was
  replaced by the normalized text. The pedido, its lines, payment,
  delivery, scheduled time, and pending context are unchanged.
* `rejected` with `no_draft` — no `session.id_pedido` or row missing.
* `rejected` with `session_mismatch` — the pedido belongs to another
  session.
* `rejected` with `pedido_not_borrador` — the pedido is in
  `ingresado`, `preparacion`, `terminado`, `entregado`, or
  `cancelado`.
* `rejected` with `text_empty` — normalized text is `0` characters.
* `rejected` with `text_too_long` — normalized text is `> 500`
  characters.

## Technical failures

* Database connection, read, or write failure.
* Repository / model mapping error.
* Any unexpected `Exception` raised inside the orchestrator, response
  builder, dispatcher branch, or mapper branch.

Technical failures propagate to the existing transaction owner
(`process_incoming_message_transactional` for local traffic,
`ProviderInboundMessageCoordinator.process_lease` for provider
traffic) without conversion to a business outcome. The owner rolls
back the complete turn; the dispatcher / response / mapper surfaces
do not generate a `failed`-status response text outside the existing
generic fallback.

## Exact fallback conditions

None. The change does not introduce a fallback path:

* The classifier remains the only authority for naming
  `set_observacion_pedido`. The orchestrator does **not** retry, fuzzy
  match, or heuristic-match text.
* The orchestrator does **not** search for another pedido, another
  session, another cliente, or another comercio.
* The orchestrator does **not** truncate a too-long text; it rejects.
* The orchestrator does **not** create a pending context or queue a
  follow-up intent; a rejected observation is final for the turn.
* The orchestrator does **not** widen or modify any existing pending
  candidate set.
* The orchestrator does **not** consult the LLM, the product
  recognizer, the hybrid recognizer, or the shadow comparison path.

## Conditions that MUST NOT trigger fallback

* A pre-existing pending context of any kind (product selection, order
  line selection, product modification, order clear confirmation) —
  the message is resolved by that context instead of this
  orchestrator. The orchestrator is never invoked in that turn.
* A `set_observacion_producto` message — that intent keeps its own
  dispatch path. The new orchestrator is bound only to
  `SET_OBSERVACION_PEDIDO`.
* A `consultar_resumen_pedido` or `confirmar_pedido` request — the
  existing closure orchestrators keep their exclusive write paths.
* A `vaciar_pedido` confirmation pending — the confirmation resolver
  keeps its exclusive read path.

## Execution and isolation

1. The classifier preserves its existing names and ordering. The new
   orchestrator is registered as the `SET_OBSERVACION_PEDIDO` branch
   in the existing `dispatch_initial_message` `for` loop, between
   the existing `CONFIRMAR_PEDIDO` and `VACIAR_PEDIDO` branches. The
   order does not affect the response because no other initial intent
   runs in the same turn for the same message (a single classifier
   call may emit several intents, but the existing
   `active_boundary_reached` machinery only constrains
   `AGREGAR_PRODUCTO` and `INICIAR_PEDIDO`).
2. The orchestrator uses **only** `session.id_pedido`. It does not
   look up by cliente, comercio, channel, phone, or recency.
   `session.id_pedido` is a `Mapped[int | None]`, so the orchestrator
   handles `None` as the `no_draft` case and never falls through to a
   search.
3. The orchestrator validates `Pedido.id_session == session.id` to
   prevent any cross-session or cross-comercio leak. A pedido that
   belongs to a closed session is unreachable through the active
   session's `id_pedido`, so the active session is the sole
   authority.
4. The orchestrator normalizes the text once at the boundary, then
   stages the attribute write `pedido.observaciones = text`. The
   write is durable only when the existing outer transaction commits.
5. The shared `build_customer_responses` and `stage_outbound_rows`
   path renders the same text for the local endpoint and for the
   provider outbox, so a customer reply to the local HTTP route and a
   provider-replied message are byte-equal in `CustomerResponse.message`
   and identical in `intent` and `status`.

## Transaction ownership

The new code never calls `commit`, `rollback`, `begin`, `flush`,
`refresh`, `expire`, or `close`. The existing
`process_incoming_message_transactional` owns local commits and
rollbacks; the existing
`ProviderInboundMessageCoordinator.process_lease` owns the deferred
provider pipeline commit and rollback. The new orchestrator stages
the attribute write and lets the outer owner decide. The new response
builder is read-only over the already-staged attributes. The new
mapper branch is read-only over the already-staged
`ProcessedIntent.resolved_data`.

## Files and boundaries

* `backend/models/pedido.py` — `observaciones: Mapped[str | None]
  = mapped_column(Text, nullable=True)` (no `default`, no
  `server_default`, no `index`, no `CheckConstraint`).
* `backend/alembic/versions/<new_revision>_add_pedidos_observaciones.py`
  — `op.add_column("pedidos", sa.Column("observaciones", sa.Text(),
  nullable=True))` and `op.drop_column("pedidos", "observaciones")`.
* `backend/intents/orchestration/draft_order_closure.py` — add
  `process_initial_set_observacion_pedido`, `_normalize_observacion`,
  and a private `_validate_observacion_length` helper. Reuse
  `_load_session_pedido`, `_rejected`, the
  `unicodedata`/`re` imports already present, and the established
  no-transaction-control style.
* `backend/intents/orchestration/initial_intent_dispatcher.py` — one
  `elif` branch.
* `backend/intents/responses/draft_order_closure.py` — one builder
  function reusing the existing `_NO_DRAFT_MESSAGE`,
  `_NOT_BORRADOR_MESSAGE`, `_FAILED_MESSAGE` constants.
* `backend/services/outbound_response_mapper.py` — one `elif` branch
  in `build_customer_responses`.
* `backend/tests/test_draft_order_observation.py` — new focused test
  module (the user will add additional tests to
  `test_draft_order_closure.py` only if the established home is
  confirmed).

## Focused tests

PostgreSQL-backed integration tests using the `supernova_test` engine
established in `test_draft_order_closure.py` shall prove:

* `set_observacion_pedido` replaces a `NULL` observation.
* `set_observacion_pedido` replaces an existing observation.
* Unicode whitespace (NBSP, tab, mixed line terminators) collapses
  before the 1..500 length check.
* A 1-character text and a 500-character text are accepted.
* A 501-character text is rejected (`text_too_long`) and preserves
  the prior value.
* An empty / whitespace-only text is rejected (`text_empty`) and
  preserves the prior value.
* `session.id_pedido is None` → `rejected` `no_draft`, no DB write.
* `pedido.id_session != session.id` → `rejected` `session_mismatch`,
  no DB write.
* `pedido.estado_pedido in {ingresado, preparacion, terminado,
  entregado, cancelado}` → `rejected` `pedido_not_borrador`, no DB
  write.
* The dispatcher branch routes the new intent to the new
  orchestrator; no other orchestrator is called.
* The shared mapper renders the same `CustomerResponse.message`,
  `intent`, and `status` for the local path and the outbox staging
  path.
* The accepted length appears in `resolved_data["accepted_length"]`;
  the raw or normalized text does not appear in `resolved_data`,
  response text, or outbox row.
* The orchestrator, response builder, dispatcher branch, and mapper
  branch do not call `commit`, `rollback`, `begin`, `flush`,
  `refresh`, `expire`, or `close`.
* The migration is reversible: upgrade adds the column; downgrade
  drops it.

A pending-context priority test (e.g. an active product selection
context receives the message instead of the new orchestrator) is
covered by the existing `test_pending_context_dispatcher.py` because
the dispatcher is unchanged.
