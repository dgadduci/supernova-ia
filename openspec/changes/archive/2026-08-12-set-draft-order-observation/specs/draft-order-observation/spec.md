# draft-order-observation Specification

## ADDED Requirements

### Requirement: The `set_observacion_pedido` intent persists a single general observation on the session-associated borrador

When the authoritative initial classifier emits
`set_observacion_pedido` and the conversation has no pending context,
the system SHALL load only the pedido referenced by
`session.id_pedido`, validate that `Pedido.id_session == session.id`
and that `pedido.estado_pedido == BORRADOR`, normalize the
`classified.mensaje` text, and — when the normalized text length is in
the closed interval `[1, 500]` — stage a write that replaces the
current `pedidos.observaciones` value with that normalized text. The
write is durable only when the existing local or provider transaction
commits. The new observation field is a free-text general note that
belongs to the pedido as a whole; it SHALL NOT be persisted on
`pedidos_productos.observaciones` and SHALL NOT interact with the
product-level `set_observacion_producto` intent.

#### Scenario: Successful replacement of a NULL observation

- **WHEN** the associated borrador has `observaciones = NULL` and the
  customer supplies an in-range observation text
- **THEN** the pedido is updated with the normalized text
- **AND** lines, payment, delivery, scheduled time, pending context,
  pedido state, and session association are unchanged

#### Scenario: Successful replacement of an existing observation

- **WHEN** the associated borrador has a non-null `observaciones`
  value and the customer supplies an in-range observation text
- **THEN** the pedido is updated with the new normalized text
- **AND** the previous value is not preserved, restored, or
  archived

#### Scenario: Unicode whitespace is collapsed before the length check

- **WHEN** `classified.mensaje` contains leading/trailing whitespace
  or internal whitespace made of mixed Unicode space code points
  (ASCII space, tab, line terminators, non-breaking space, narrow
  no-break space, ideographic space, etc.)
- **THEN** the orchestrator strips and collapses that whitespace
  before measuring the length
- **AND** the in-range check operates on the post-normalization
  length

### Requirement: Empty or too-long observation text is a non-mutating rejection

A normalized text with length `0` (empty or whitespace-only) or
length `> 500` SHALL be a non-mutating `rejected` outcome. The
`pedidos.observaciones` value SHALL be preserved exactly (a `NULL`
value stays `NULL`; a prior accepted text stays unchanged). The
orchestrator SHALL NOT truncate a too-long text. The CustomerResponse
text SHALL NOT quote the rejected text or any part of it.

#### Scenario: Too-long text rejects without truncation

- **WHEN** the normalized text length is greater than `500`
- **THEN** the result is `rejected` with reason `text_too_long`
- **AND** the persisted `observaciones` value is unchanged
- **AND** the CustomerResponse text does not contain the rejected
  text, the original message, or any fragment of either

#### Scenario: Empty text rejects without mutation

- **WHEN** the normalized text length is `0`
- **THEN** the result is `rejected` with reason `text_empty`
- **AND** the persisted `observaciones` value is unchanged

### Requirement: Missing, foreign, or non-borrador pedido rejects without mutation

A `set_observacion_pedido` request SHALL NOT mutate the pedido,
its lines, payment, delivery, scheduled time, or pending context when
`session.id_pedido` is null, the loaded row is missing, the loaded
row's `id_session` differs from the active session, or the loaded
row's `estado_pedido` is not `BORRADOR`. Each case SHALL yield a
deterministic non-mutating `rejected` outcome. The orchestrator SHALL
NOT search for another pedido by cliente, comercio, channel, phone,
recency, or history.

#### Scenario: No associated pedido

- **WHEN** `session.id_pedido` is null or does not resolve to a row
- **THEN** the result is `rejected` with reason `no_draft`
- **AND** no observation text is written to any pedido

#### Scenario: Foreign associated pedido is not annotated

- **WHEN** `session.id_pedido` resolves to a pedido whose
  `id_session` differs from the active session
- **THEN** the result is `rejected` with reason `session_mismatch`
- **AND** the foreign pedido is not loaded, read, or mutated

#### Scenario: Non-borrador pedido is not annotated

- **WHEN** the associated pedido is in `ingresado`, `preparacion`,
  `terminado`, `entregado`, or `cancelado`
- **THEN** the result is `rejected` with reason
  `pedido_not_borrador`
- **AND** the pedido is not annotated, transitioned, or replaced

### Requirement: Pending context retains priority over a `set_observacion_pedido` request

When any pending context is active (product selection, order line
selection, product modification, or order clear confirmation), the
established pending-context dispatcher SHALL retain priority over
initial classification. A `set_observacion_pedido` request SHALL be
handled only by that active context, SHALL NOT invoke the new
orchestrator in the same turn, and SHALL NOT create, clear, promote,
or widen any pending candidate set.

#### Scenario: Pending product selection is preserved

- **WHEN** a product selection context is active and the customer
  sends a message that would otherwise be classified as
  `set_observacion_pedido`
- **THEN** the message is handled only by the active product
  selection resolver
- **AND** no write to `pedidos.observaciones` is staged
- **AND** no new pending context is created

### Requirement: Commerce and session isolation is preserved

The `set_observacion_pedido` orchestrator SHALL use
`session.id_pedido` as the sole authority for the target pedido. It
SHALL NOT read, search, or accept a pedido id, cliente id, comercio
id, channel id, or phone number from the message. It SHALL NOT
annotate, load, or expose a pedido belonging to a different session
or comercio. The `PedidoProducto.observaciones` field SHALL NOT be
read, written, or cleared by this orchestrator.

#### Scenario: Annotation stays within the session-owned borrador

- **WHEN** a customer annotates a borrador
- **THEN** the persisted annotation lives only on the pedido
  identified by `session.id_pedido`
- **AND** no other pedido, no `PedidoProducto` row, and no
  `set_observacion_producto` line is touched

### Requirement: Responses are non-sensitive and shared between the local and outbox paths

The `set_observacion_pedido` response builder and shared response
mapper SHALL render the same deterministic Spanish
`CustomerResponse.message` for the local HTTP endpoint and for each
staged provider-outbox row. The successful text SHALL be a fixed
confirmation that does not include the observation body. The rejected
text SHALL be a fixed Spanish message that does not include the
rejected text, the pedido id, the session id, the cliente/comercio
ids, or any internal exception text. The `ProcessedIntent
.resolved_data` SHALL contain only a stable reason code (on rejection)
or a non-revealing length field (on execution) — never the raw,
normalized, or partial text.

#### Scenario: Local and outbox responses agree

- **WHEN** the same processed `set_observacion_pedido` result is
  rendered by the local path and by durable outbox staging
- **THEN** both `CustomerResponse.message` strings are byte-equal
- **AND** both carry `intent = "set_observacion_pedido"` and the
  same `status`

#### Scenario: Observation text never leaks through the response surface

- **WHEN** a successful or rejected `set_observacion_pedido` turn
  completes
- **THEN** `CustomerResponse.message`,
  `ProcessedIntent.resolved_data`, the outbox row `cuerpo`, the
  structured observability snapshots, and the structured logs do not
  contain the raw, normalized, or any prefix/suffix of the
  observation text

### Requirement: Transaction ownership stays with the existing owners

The `set_observacion_pedido` orchestrator, response builder,
dispatcher branch, and shared mapper branch SHALL NOT call
`commit`, `rollback`, `begin`, `flush`, `refresh`, `expire`, or
`close` on the SQLAlchemy session. The successful attribute write
is staged only; durability is owned by the existing local
transactional processor and the existing provider deferred
coordinator. A technical failure propagates to those owners and
rolls back the complete turn.

#### Scenario: Technical failure rolls back the staged annotation

- **WHEN** a database or model error is raised after the orchestrator
  stages `pedido.observaciones = text` and before the outer
  transaction commits
- **THEN** the outer transaction rolls back
- **AND** no `pedidos.observaciones` value is durable
- **AND** the customer receives the existing technical-failure
  fallback, not a success response

### Requirement: Migration adds a nullable `pedidos.observaciones` column without backfill

The Alembic migration SHALL add a single nullable `Text` column
`observaciones` to the `pedidos` table. The migration SHALL NOT
backfill existing rows, SHALL NOT add a default or server default,
SHALL NOT add a `CheckConstraint`, SHALL NOT add an index, and
SHALL NOT alter any other column or table. `downgrade()` SHALL drop
the column. The migration SHALL be chained from the current
Alembic head.

#### Scenario: Reversible migration

- **WHEN** the operator runs `alembic upgrade head`
- **THEN** the `pedidos` table has a nullable `Text` column
  `observaciones` and no other schema change
- **WHEN** the operator runs `alembic downgrade -1`
- **THEN** the `pedidos` table no longer has the `observaciones`
  column
- **AND** Alembic state matches the database state
