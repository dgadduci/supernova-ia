## ADDED Requirements

### Requirement: Product-add execution has a closed privacy-safe event

The existing operational-event catalogue SHALL expose
`product_add_execution` through a dedicated component. Its required outcome
is one of `created`, `incremented`, `rejected_invalid_input`,
`rejected_session_or_pedido`, `rejected_not_editable`,
`rejected_missing_presentation`, or `rejected_price_unavailable`. It SHALL
accept no identifiers, text, labels, quantities, prices, exception material,
correlation data or other optional fields.

#### Scenario: Price rejection is diagnosable without customer data

- **WHEN** a selected presentation has no usable price
- **THEN** exactly one `rejected_price_unavailable` event is emitted
- **AND** the event contains no customer, order, session, product or catalog
  identifier and no message content

### Requirement: Product-add observability cannot change business behavior

Event validation or emission failure SHALL be best effort and SHALL NOT
change the handler result or mutate database state.

#### Scenario: Event sink fails after an otherwise successful add

- **WHEN** the operational event sink fails while a priced presentation is
  being staged
- **THEN** the handler retains its `executed` outcome and the caller-owned
  transaction retains the same staged mutation
