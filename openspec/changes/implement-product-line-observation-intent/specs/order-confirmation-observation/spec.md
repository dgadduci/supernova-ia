## ADDED Requirements

### Requirement: Confirmation captures an optional order observation before finalizing

After an explicit `confirmar_pedido` request passes the existing active-own-
draft, non-empty-lines, payment and delivery preconditions, the system SHALL
persist a `pending_resolution` confirmation-observation intent and ask the
customer: `¿Querés agregar alguna observación al pedido? Escribila ahora o
respondé “no”.` It SHALL NOT infer that product selection has ended before
the explicit confirmation request.

#### Scenario: Confirmation opens the bounded observation step

- **WHEN** the active own draft satisfies the existing confirmation
  preconditions and the customer requests confirmation
- **THEN** the Pedido remains `borrador`
- **AND** no observation is changed
- **AND** the session enters `order_confirmation_observation` pending context

### Requirement: Capture reply is opaque and atomically finalizes the draft

While the confirmation-observation context is active, the next message SHALL
be handled before initial classification. Exact normalized `no` SHALL confirm
without changing `Pedido.observaciones`. Any other non-empty normalized value
of 1–500 code points SHALL replace `Pedido.observaciones` and confirm the
same validated own draft in the same caller-owned transaction. No LLM,
classifier, product recognizer, catalog or order-line lookup may inspect the
capture reply.

#### Scenario: Free text becomes the general order observation

- **WHEN** the customer replies with valid free text to the observation prompt
- **THEN** that normalized text is stored only on the active Pedido
- **AND** the Pedido transitions from `borrador` to `ingresado`
- **AND** no `PedidoProducto.observaciones` value changes

#### Scenario: Skip confirms without an observation write

- **WHEN** the customer replies `no` to the observation prompt
- **THEN** the Pedido is confirmed
- **AND** its prior `observaciones` value is preserved

#### Scenario: Invalid text remains safely pending

- **WHEN** the capture reply is empty after normalization or exceeds 500 code
  points
- **THEN** no order field changes and the confirmation-observation context
  remains active for a retry

### Requirement: Line observations are not an active capability

The runtime SHALL not classify or execute direct product-line observations,
select an order line for an observation, or display an editable/readable
product-line observation as an active feature. Existing persisted
`PedidoProducto.observaciones` data SHALL not be migrated, erased or copied.
Direct observation-classifier items outside the dedicated confirmation context
shall produce deterministic guidance and no mutation. A stale persisted
product-line-observation pending state SHALL be cleared as rejected without
invoking its former handler.

#### Scenario: Product wording does not select or mutate a line

- **WHEN** a customer sends an observation-like message while no
  confirmation-observation context is active
- **THEN** no product line is selected or modified
- **AND** the response directs the customer to confirm the order first

### Requirement: Finalization preserves transaction ownership and privacy

The confirmation orchestrator, observation resolver, finalizer and responses
SHALL not commit, rollback, flush, refresh, begin or close the database
session. They SHALL revalidate the active own draft and confirmation
preconditions immediately before staging changes. Unexpected technical
failures SHALL propagate to the existing outer transaction owner. New
diagnostics and customer responses SHALL not expose observation content,
database identifiers, raw classifier output or pending JSON.

#### Scenario: Final revalidation rejects without partial mutation

- **WHEN** the Pedido no longer satisfies a confirmation precondition when a
  capture reply is processed
- **THEN** neither `Pedido.observaciones` nor its state changes
- **AND** no transaction-control method is called by the new flow
