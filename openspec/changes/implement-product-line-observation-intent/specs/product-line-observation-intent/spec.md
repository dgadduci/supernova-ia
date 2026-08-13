# Capability: product-line-observation-intent

## Purpose

Execute the existing `set_observacion_producto` intent against exactly one
line of the active conversation session's own draft Pedido, without expanding
the order-line candidate boundary or changing transaction ownership.

## Requirements

### Requirement: Only an active session's own draft line is mutable

The intent SHALL use `session.id_pedido` as its only order scope. Before
writing, it SHALL require an active conversation session, an existing Pedido
whose `id_session` equals `session.id`, `estado_pedido == borrador`, and a
`PedidoProducto` whose `id` belongs to that Pedido. It SHALL never select a
line through the commerce catalog, a different session, or a most-recent-line
fallback.

#### Scenario: Foreign line is not mutated

- **WHEN** a ready intent names a `pedido_producto_id` that belongs to another
  Pedido
- **THEN** the result is `rejected`, its observation remains unchanged, and
  no other line is substituted

#### Scenario: Non-borrador order is not mutable

- **WHEN** the session points at an `ingresado` Pedido
- **THEN** the result is `rejected` and no observation is written

### Requirement: Local action and value determination

The implementation SHALL use the trimmed user-supplied classified message as
the value for a set action. It SHALL derive a clear action only from the local
explicit clear grammar defined by the approved change; a clear writes `NULL`.
It SHALL reject empty text and SHALL NOT use LLM output to extract, rewrite,
delete, or otherwise determine the stored observation or final line id.

#### Scenario: Set preserves user text

- **WHEN** a unique line is recognized from `La pizza es sin aceitunas`
- **THEN** the line receives that trimmed source text as its observation and
  the result is `executed`

#### Scenario: Explicit clear writes NULL

- **WHEN** a unique line is recognized from an explicit supported
  “remove observation” phrase
- **THEN** the line's `observaciones` value is set to `NULL` and the result is
  `executed`

### Requirement: Candidate selection is order-line-only and monotonic

The recognizer SHALL build its candidate catalog only from current
`PedidoProducto` rows of `session.id_pedido` and use `PedidoProducto.id` as
the final candidate identifier. One candidate becomes ready; multiple
candidates create an `order_line_selection` pending context. Clarification
SHALL intersect only with the stored candidate ids and preserve the original
action/value. It SHALL not reclassify, query the commerce catalog, or widen a
pending set.

#### Scenario: Clarification narrows without changing text

- **WHEN** an ambiguous observation intent stores candidates `[10, 11]` and
  its action/text
- **AND** the clarification identifies only line `11`
- **THEN** ready execution targets `11` and uses the original action/text

#### Scenario: Out-of-set clarification is rejected

- **WHEN** a clarification recognizes line `12` while the stored set is
  `[10, 11]`
- **THEN** the result is `rejected` and no observation changes

### Requirement: New write seam preserves caller transaction ownership

The dedicated repository/service operation for this intent SHALL validate
ownership, draft state and line membership before assigning only
`PedidoProducto.observaciones`. It SHALL support a nullable assignment and
SHALL NOT call `commit`, `rollback`, `flush`, `refresh`, `expire`, `begin`,
or `close`. Unexpected failures SHALL propagate to the existing outer
transaction owner.

#### Scenario: Technical error rolls back the turn

- **WHEN** the write operation raises while processing an incoming message
- **THEN** the exception reaches the existing transactional processor, which
  owns rollback; the observation intent code itself performs no transaction
  control

### Requirement: Responses are deterministic and observation-private

The response mapper SHALL route this intent to a deterministic builder for
pending, executed, rejected and failed outcomes. It SHALL show display labels
only when needed for clarification/confirmation and SHALL NOT include stored
observation text, raw classifier/LLM output, database ids, or session ids.

#### Scenario: Successful response does not echo sensitive text

- **WHEN** a set action succeeds with a free-text observation
- **THEN** the response confirms that the product clarification was updated
  without reproducing that text
