## MODIFIED Requirements

### Requirement: Product selection dispatch

When `session.context_type == "product_selection"`, the dispatcher SHALL call
the existing product-selection orchestration service with the supplied message
and active intent. It SHALL persist only a `pending_resolution` or `ready`
result through `set_active`. A `ready` result SHALL delegate to
`execute_ready_pending_context`. A resolver-produced `rejected` result SHALL
clear the active pending state and `session.context_type`, then return that
rejected result once; it SHALL NOT persist a rejected active intent.

#### Scenario: Pending product selection reply persists context

- **WHEN** a `product_selection` reply still resolves to `pending_resolution`
- **THEN** the dispatcher persists the updated active intent and preserves
  context type

#### Scenario: Ready product selection triggers execution

- **WHEN** a `product_selection` reply resolves to `ready`
- **THEN** the dispatcher persists the ready intent and delegates to
  `execute_ready_pending_context`, returning the executed result

#### Scenario: Rejected product selection releases the context

- **WHEN** a product-selection resolver returns `rejected`
- **THEN** the dispatcher returns that result once with no active pending
  intent and `session.context_type == null`
- **AND** the following ordinary customer message reaches initial dispatch

### Requirement: Definitive resolver rejection clears supported pending context

For every supported pending context, a resolver-produced `rejected` result is
a definitive business outcome. The dispatcher SHALL clear active pending state
and `session.context_type` within the caller-owned transaction, return exactly
one rejected result, and not invoke ready execution. It SHALL preserve state
for `pending_resolution` and shall not clean up a technical failure.

#### Scenario: Invalid order-line clarification cannot trap later messages

- **WHEN** an `order_line_selection` resolver rejects a clarification outside
  its stored candidate set
- **THEN** the context is cleared without widening candidates or mutating an
  order line
- **AND** a later status or product message is not dispatched as that stale
  clarification

### Requirement: Explicit status question interrupts supported pending context read-only

Before invoking a supported pending resolver, the dispatcher SHALL apply the
existing closed deterministic status-question predicate. If it matches, the
dispatcher SHALL call the existing own-pedido status-query orchestrator and
return its one result without invoking the classifier or pending resolver. It
SHALL leave pending JSON, candidate sets, queue and `session.context_type`
unchanged for both `executed` and business `rejected` status outcomes.

#### Scenario: Status during product selection preserves the clarification

- **WHEN** `product_selection` is pending and the customer sends `Cuál es el
  estado de mi pedido`
- **THEN** the dispatcher returns the status-query outcome for only the
  session-associated pedido
- **AND** the same product-selection candidates and context remain pending

#### Scenario: Ordinary product answer does not become a status interruption

- **WHEN** `product_selection` is pending and the customer sends `Grande`
- **THEN** only the existing restricted product resolver is invoked
