# Set draft-order observation

## Why

`set_observacion_pedido` is already in the legacy classifier names, in the
authoritative `IntentName` enum, and in the project-level `IntentName`
contract, but the inbound pipeline has no branch for it. A customer can ask
the conversation to attach a free-text general note to the active draft
pedido (for example, a delivery preference, a courtesy remark, or an
instruction for the merchant), and the message currently falls through to
the generic "no pude procesar tu mensaje" answer. `PedidoProducto`
already has a nullable `observaciones` column for product-level notes, but
that field belongs to a single line, not to the pedido as a whole, and
reusing it would conflate product and order notes and break commerce
isolation between the two.

## What Changes

Persist a single free-text observation belonging to the **borrador
pedido** associated with the active session.

* Add a new, narrow orchestration for `set_observacion_pedido` that
  operates exclusively on `session.id_pedido`, requires the loaded pedido
  to belong to that same session, and requires the pedido to be in
  `borrador`. The observation text comes from `classified.mensaje`; it is
  normalized (trim + Unicode whitespace collapse) and accepted only when
  its length is `1..500` characters. A valid value replaces the previous
  observation; an empty, whitespace-only, or too-long value is a
  non-mutating rejection that preserves the prior observation. None of
  the four other draft-closure outcomes (no draft, foreign-session
  pedido, non-`borrador` pedido, session not active) mutate the pedido.
* Add a new `Text` nullable column `pedidos.observaciones` via a
  reversible Alembic migration that does **not** perform a backfill. The
  migration is the only schema change; no other table, index, or
  constraint is touched and `PedidoProducto.observaciones` is **not**
  reused.
* Route the existing `set_observacion_pedido` classifier intent through
  the initial dispatcher to the new orchestrator, and route its
  `ProcessedIntent` through the existing shared
  `build_customer_responses` / `stage_outbound_rows` mapper so the local
  endpoint and the provider outbox render the same text. The
  `CustomerResponse` text never includes the observation body.

## Objective

Allow a customer to attach a single free-text general observation to the
`borrador` pedido already associated with their active session, using the
existing `set_observacion_pedido` classifier intent, without changing
any other draft-closure, product-observation, recognition, pending
context, confirmation, or outbox surface.

## Current execution path

Provider traffic follows receipt → deferred work → active session/draft
pedido staging → `process_incoming_message` → response mapping → outbound
outbox. Local traffic reaches the same message orchestration through
`process_incoming_message_transactional`. With no `context_type`,
`dispatch_initial_message` calls the authoritative classifier, which
emits `set_observacion_pedido` in the existing `IntentName` enum, but
the initial dispatcher has no branch for it, so it becomes a generic
rejected response. `Pedido` owns `id_session`, `id_medio_pago`,
`id_metodo_entrega`, `datetime_entrega_programada`, and the `borrador`
state; it does **not** own a general observation column. The reverse FK
is `Session.id_pedido`, so `session.id_pedido` is the only authority for
which pedido an observation may be attached to. The
`informational_commerce_queries` and `draft_order_closure` orchestrators
already establish the same session-borrador, commerce-isolated, no
transaction-control pattern that this change reuses.

## Scope and non-goals

* Dispatch the existing `set_observacion_pedido` intent to a narrow
  initial orchestrator and render its outcome through the existing
  shared response mapper and outbox.
* Add a nullable `Text` column `pedidos.observaciones` through a
  reversible Alembic migration. No backfill, no default, no
  `CheckConstraint`, no index, no `NOT NULL` upgrade in this change.
* Operate only on `session.id_pedido`; require `Pedido.id_session ==
  session.id`; require `pedido.estado_pedido == BORRADOR`; require
  `session.estado_session == ACTIVA` when the orchestrator first
  resolves the session-owned pedido.
* Reject — without mutating — empty, whitespace-only, or over-500
  characters text, missing/foreign/non-borrador pedido, and inactive
  session.
* Reuse the existing initial dispatcher, shared response mapper, and
  outbox; do not introduce a parallel pipeline, second classification,
  new transaction owner, new pending context, new endpoint, new
  classifier/prompt, recognizer, or outbox schema.
* Do **not** touch `PedidoProducto.observaciones`, the
  `set_observacion_producto` intent, the product recognizer, the
  product selection/modification context, the
  `consultar_resumen_pedido` summary, the
  `set_metodo_de_pago`/`set_metodo_de_entrega`/`confirmar_pedido`
  transitions, the `vaciar_pedido` confirmation flow, the
  `iniciar_pedido` new-order transition, the `cancelar_pedido` flow,
  or any LLM, prompt, LangGraph, or retrieval-augmented change.
* Do **not** infer or execute confirmation, cancellation, or new-order
  semantics. `set_observacion_pedido` is its own one-shot intent that
  only stages an `executed` or `rejected` result.

## Shared boundary, fallback, and transactions

* The initial classifier is authoritative only for naming
  `set_observacion_pedido`. The new orchestrator does not reclassify,
  does not consult the LLM, and does not read or modify the
  `set_observacion_producto` surface.
* A non-null pending context retains its established priority over
  initial classification, so a message that would otherwise look like
  a `set_observacion_pedido` request is resolved by the active pending
  context (product selection, order line selection, product
  modification, order clear confirmation) and never falls through to
  the new orchestrator. The new orchestrator never creates, clears,
  promotes, or widens any pending candidate set.
* The orchestrator uses **only** `session.id_pedido` and validates
  `Pedido.id_session == session.id`. It does not search by cliente,
  comercio, channel, phone, or recency. Commerce isolation is
  preserved because the pedido is reachable exclusively through the
  active session.
* `classified.mensaje` is the sole source of the observation text. It
  is normalized with `unicodedata.normalize("NFKC", ...).strip()` plus
  a Unicode-aware whitespace collapse (`re.sub(r"\s+", " ", ...)` after
  a Unicode-aware `split` so non-breaking spaces and other
  whitespace code points collapse like ASCII space). No
  language-specific truncation, no courtesy stripping, no
  ellipsization, no second classification, no re-prompt.
* The valid text is **1..500** characters after normalization. The
  minimum is `1`; the maximum is `500`. Outside that range the
  orchestrator returns a non-mutating `rejected` outcome that
  preserves the prior `pedidos.observaciones` value. The orchestrator
  must **not** truncate a too-long text — the user must receive a
  rejection, never a silent cut.
* A valid text replaces the previous value, including the case where
  the previous value was `NULL` (the column becomes non-null) and the
  case where the previous value was non-null (the column overwrites).
  The new value is staged as a single attribute write and committed
  by the existing outer transaction owner.
* Technical exceptions (database read/write failure, repository
  exception, etc.) propagate unchanged to the existing local
  (`process_incoming_message_transactional`) or provider
  (`ProviderInboundMessageCoordinator.process_lease`) transaction
  owner. The new orchestrator, response builder, dispatcher branch,
  mapper integration, and migration never call `commit`, `rollback`,
  `begin`, `flush`, `refresh`, `expire`, or `close` on the SQLAlchemy
  session. They never take transaction ownership.
* The CustomerResponse message never contains the raw observation
  text, the pedido id, the session id, the cliente/comercio/channel
  ids, or any internal exception text. Successful outcome text is a
  fixed Spanish confirmation that says the observation was saved.
  Rejection text is a fixed Spanish message that never quotes the
  rejected text.

## Observability

Reuse the existing structured `ProcessedIntent`,
`pending_state_snapshot`, provider-processing, and outbound-attempt
observability. The new orchestrator and response builder must not log
the raw message, the normalized observation text, the rejected text,
the pedido id, the session id, the cliente/comercio ids, or any other
customer/order detail. The successful `ProcessedIntent.resolved_data`
must contain only a boolean success flag and the length of the accepted
text (so logs can confirm the field is non-empty without disclosing
its content); the rejected `resolved_data` must contain only a stable
reason code such as `text_empty`, `text_too_long`, `no_draft`,
`pedido_not_borrador`, or `session_mismatch`.

## Expected files

* `backend/models/pedido.py` — add `observaciones: Mapped[str | None]`
  mapped column, `Text`, nullable, default `None`, no server default,
  no index, no check constraint.
* `backend/alembic/versions/<new_revision>_add_pedidos_observaciones.py`
  — reversible migration that `op.add_column("pedidos", sa.Column("observaciones", sa.Text(), nullable=True))`
  in `upgrade()` and `op.drop_column("pedidos", "observaciones")` in
  `downgrade()`. `down_revision` is the current Alembic head
  `7c4d5e6f7a8b`.
* `backend/intents/orchestration/draft_order_closure.py` — add a
  narrow `process_initial_set_observacion_pedido(db, session,
  source_text)` orchestrator and a small private
  `_normalize_observacion(text)` helper. Reuse the existing
  `_load_session_pedido`, `_rejected`, and the established
  no-transaction-control style.
* `backend/intents/orchestration/initial_intent_dispatcher.py` — add
  one branch in the `for classified in result.intents:` loop that
  calls `process_initial_set_observacion_pedido(db, session,
  classified.mensaje)` for `IntentName.SET_OBSERVACION_PEDIDO`. The
  branch reuses the same `dispatch_initial_message` caller-controlled
  transaction; it does not loop, does not create pending context, and
  does not flush/refresh.
* `backend/intents/responses/draft_order_closure.py` — add a
  `build_set_observacion_pedido_response(db, session, intent)`
  builder. Reuse the existing `_NO_DRAFT_MESSAGE`,
  `_NOT_BORRADOR_MESSAGE`, and `_FAILED_MESSAGE` constants where
  applicable. Successful text is a fixed Spanish confirmation; rejected
  text is a fixed Spanish rejection that never quotes the rejected
  text.
* `backend/services/outbound_response_mapper.py` — add one
  `elif intent.intent == "set_observacion_pedido":` branch in
  `build_customer_responses` that calls the new builder. The
  `stage_outbound_rows` path inherits the new branch for free.
* `backend/tests/test_draft_order_observation.py` — new focused test
  module.
* `openspec/changes/set-draft-order-observation/specs/draft-order-observation/spec.md`
  — new capability spec with the `ADDED Requirements` block.
* `openspec/changes/set-draft-order-observation/proposal.md`,
  `design.md`, `tasks.md` — this change set.

## Focused tests

PostgreSQL-backed integration tests shall cover:

* successful replacement of `NULL` observation,
* successful replacement of an existing observation,
* successful Unicode whitespace collapse (tabs, non-breaking space,
  multiple spaces, mixed line terminators) before the 1..500
  acceptance check,
* rejection (`text_too_long`) preserves the prior value,
* rejection (`text_empty`) preserves the prior value,
* no associated pedido → `rejected` with `no_draft`, no DB write,
* foreign-session pedido → `rejected` with `session_mismatch`, no DB
  write,
* pedido in any non-`borrador` state → `rejected` with
  `pedido_not_borrador`, no DB write,
* dispatcher branch wires the new orchestrator, mapper wires the new
  response builder, local and outbox responses are byte-equal,
* `classified.mensaje` round-trip: a 500-character accepted text does
  not appear in `resolved_data`, logs, response text, or outbox row,
* migration is reversible: upgrade adds the column, downgrade drops it,
  and Alembic state matches.

## Validation commands

The implementer must run locally and report complete output:

```
venv/bin/python -m pytest backend/tests/test_draft_order_observation.py backend/tests/test_draft_order_closure.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_outbound_response_mapper.py -q
```

```
venv/bin/python -m ruff check backend/models/pedido.py backend/intents/orchestration/draft_order_closure.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py backend/alembic/versions/ backend/tests/test_draft_order_observation.py
```

```
venv/bin/python -m compileall -q backend/models/pedido.py backend/intents/orchestration/draft_order_closure.py backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/responses/draft_order_closure.py backend/services/outbound_response_mapper.py backend/tests/test_draft_order_observation.py
```

```
openspec validate set-draft-order-observation --strict
```

## Rollback / reversibility

* The migration is reversible: `downgrade()` drops
  `pedidos.observaciones`. Because no backfill and no index exist,
  downgrade is non-destructive of any application-level data (no
  other change writes this column, and the only mutation comes from
  the new orchestrator).
* The new dispatcher branch, response builder, and mapper branch are
  removable in one revert per file. The initial classifier keeps
  emitting `set_observacion_pedido`; the dispatcher simply falls back
  to the existing generic rejected path.
* No live customer data is altered by the migration.

## Deferred limitations

* Locale-specific truncation, courtesy stripping, profanity filtering,
  and PII heuristics remain out of scope; the orchestrator accepts any
  1..500 character text after Unicode normalization.
* Per-line (product) observations continue to live in
  `PedidoProducto.observaciones` and are unaffected.
* Per-pedido history, audit, version, undo, and redaction of
  observations remain deferred.
* Migration to a typed `JSONB` or `CITEXT` column, an index, or a
  maximum-length check constraint remains deferred.
* LLM-driven summarisation, classification, or translation of the
  observation text remains deferred and forbidden in this change.
