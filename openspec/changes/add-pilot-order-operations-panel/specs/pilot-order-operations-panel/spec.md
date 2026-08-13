## ADDED Requirements

### Requirement: Authenticated pilot order panel provides a bounded list

The system SHALL provide a server-rendered panel under
`/admin/pilot/orders`, protected only for that route family by HTTP Basic
authentication whose password validates against the existing configured admin
token. It SHALL use no token URL parameter, client-side persistent storage or
new credential. The default list SHALL show the most recent seven days, newest
first, in pages of 25, with an upper page size of 100 and a maximum 31-day
date filter window. It SHALL include order id/state/timestamps, session id and
state, commerce id/name, and client id/name/WhatsApp.

#### Scenario: Valid operator sees a bounded recent list

- **WHEN** an operator requests the panel with a valid Basic password and no
  filters
- **THEN** the page renders at most 25 recent orders with the required summary
  fields
- **AND THEN** no write is staged.

#### Scenario: Invalid browser authentication discloses no panel data

- **WHEN** a request lacks a valid Basic credential or the configured token is
  absent
- **THEN** it receives the existing generic administrative authentication
  failure semantics
- **AND THEN** it contains no order, client, message or credential data.

### Requirement: Exact order detail renders authoritative linked data

For one existing `pedido_id`, the panel SHALL render only that Pedido's exact
session, client, commerce, lines, payment/delivery relationships and persisted
pedido data. Lines SHALL show the product name, presentation description,
quantity, unit price and line observation. Payment and delivery SHALL include
their id and description when present, and an unambiguous absence otherwise.

#### Scenario: Detail does not fall back to another pedido

- **WHEN** an operator requests an absent or invalid pedido id
- **THEN** the panel shows a safe not-found/validation result
- **AND THEN** it does not search by session, client, commerce or message to
  replace the requested record.

### Requirement: Provider history is accurate and privacy bounded

The detail view SHALL show provider history filtered to the exact client and
commerce of the selected order. It SHALL identify inbound entries as receipt
metadata only (provider, channel and timestamp) and outbound entries as
durable rendered messages with their recorded operational delivery fields.
The UI SHALL state that inbound entries are not persistently linked to a
session/pedido and that inbound raw bodies are not retained. It SHALL NOT
render an inbound body, provider identifier, admin token, lease token,
exception text or diagnostics.

#### Scenario: Outbound row appears under its exact receipt

- **WHEN** a matching receipt has an outbound row
- **THEN** the history renders its customer-visible outbound body and recorded
  delivery state beneath that receipt
- **AND THEN** it does not imply that the receipt belongs to the selected
  session.

### Requirement: Panel is strictly read-only and transaction-neutral

The panel router, templates, projection service and repository SHALL NOT
create, cancel, transition, reset, close, associate or retry any record. They
SHALL NOT call `commit`, `rollback`, `flush`, `refresh`, `begin` or `close`.
Existing provider, JSON API and order-processing paths SHALL remain unchanged.

#### Scenario: Viewing an order cannot reset it

- **WHEN** an operator opens the list or detail page
- **THEN** no Pedido, Session, provider receipt or outbound row is changed
- **AND THEN** no reset/cancel/close control is available.
