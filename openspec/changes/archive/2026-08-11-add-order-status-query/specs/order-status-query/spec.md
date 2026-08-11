# WhatsApp order-status query

## ADDED Requirements

### Requirement: The existing status intent reads only the session-associated pedido

When the authoritative initial classifier emits `consultar_estado_pedido` and
the conversation has no pending context, the system SHALL load only the pedido
referenced by `session.id_pedido`. It SHALL require that the loaded pedido is
owned by that same session before reporting its status. It SHALL NOT create,
replace, reassociate, search for, or select another pedido.

#### Scenario: Missing association has no fallback lookup

- **WHEN** `session.id_pedido` is null or does not resolve to a pedido
- **THEN** the result is a non-mutating `rejected` outcome
- **AND** the system does not look up a pedido by client, commerce, channel,
  phone number, recency, or history

#### Scenario: Foreign associated pedido is not disclosed

- **WHEN** `session.id_pedido` resolves to a pedido whose `id_session` differs
  from the active session
- **THEN** the result is a non-mutating `rejected` outcome
- **AND** no status or order detail from that pedido is included in a response

### Requirement: Every defined pedido state has a descriptive safe outcome

For a valid session-associated pedido, `consultar_estado_pedido` SHALL return
an `executed` result whose authoritative state is the persisted
`EstadoPedido` value. `borrador` SHALL be described as unconfirmed/in progress;
`ingresado`, `preparacion`, and `terminado` SHALL be described as their existing
post-confirmation progress; and `entregado` and `cancelado` SHALL be described
as terminal outcomes. The query SHALL not transition the pedido or create a
new one.

#### Scenario: Draft status does not confirm

- **WHEN** the associated pedido is `borrador`
- **THEN** the result reports that it is still being assembled
- **AND** the pedido remains `borrador`
- **AND** payment, delivery, lines, session association, and pending state are
  unchanged

#### Scenario: Post-confirmation status is descriptive

- **WHEN** the associated pedido is `ingresado`, `preparacion`, or `terminado`
- **THEN** the result reports that persisted state
- **AND** it does not invoke any transition, confirmation, fulfillment, or new
  order flow

#### Scenario: Terminal status is descriptive

- **WHEN** the associated pedido is `entregado` or `cancelado`
- **THEN** the result reports that terminal state
- **AND** it does not reopen, replace, or alter the pedido

### Requirement: Status replies preserve conversation and commerce isolation

The status-query branch SHALL not write pending intents, alter
`session.context_type`, repeat an intent, inspect product candidate sets, or
widen any selection scope. When any pending context is active, the established
pending-context dispatcher SHALL retain priority over initial status
classification.

#### Scenario: Pending context is not bypassed by a status request

- **WHEN** a product-selection or order-clear-confirmation context is active
  and the customer sends a message that asks for order status
- **THEN** the message is handled only by that active context
- **AND** `consultar_estado_pedido` is not dispatched in the same turn
- **AND** existing candidate IDs and context state are not widened or cleared

### Requirement: Responses and transaction ownership remain shared and safe

The status-query orchestrator and response builder SHALL not call transaction
control methods. Technical failures SHALL propagate to the existing local or
provider transaction owner; missing or foreign associations are valid business
outcomes and SHALL not trigger fallback search or provider retry. The existing
shared response mapper SHALL render the same deterministic, Spanish,
non-sensitive response for local processing and each staged provider-outbox
row.

#### Scenario: Response does not expose sensitive order information

- **WHEN** a valid status query is rendered for any pedido state
- **THEN** the customer-facing text contains no database IDs, customer/contact
  information, products, prices, payment details, delivery details, address,
  or internal exception text

#### Scenario: Provider and local responses agree

- **WHEN** the same processed `consultar_estado_pedido` result is rendered by
  the local path and by durable outbox staging
- **THEN** both have the same message, intent, status, and ordering
