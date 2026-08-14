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

### Requirement: Panel GET views are strictly read-only and transaction-neutral

Every panel GET route, template, projection service and repository SHALL NOT
create, cancel, transition, reset, close, associate or retry any record. They
SHALL NOT call `commit`, `rollback`, `flush`, `refresh`, `begin` or `close`.
The separately bounded local-test POST route is governed by the following
requirement; existing provider and JSON API paths SHALL remain unchanged.

#### Scenario: Viewing an order cannot reset it

- **WHEN** an operator opens the list or detail page
- **THEN** no Pedido, Session, provider receipt or outbound row is changed
- **AND THEN** no reset/cancel/close control is available.

## ADDED Requirements

### Requirement: Detail exposes safe pending-context execution state

The exact order detail SHALL render a typed execution-state summary for its
own Session. It SHALL show only `context_type`, pending encoding validity,
active intent/status, candidate count, requirement state counts, queue length,
parsed pending-schema version and a closed context/pending consistency value.
It SHALL never render raw `pending_intents`, source text, resolved values,
candidate identifiers/labels, raw queue entries, diagnostics, exception
detail, environment/configuration values, tokens or provider secrets.

#### Scenario: Pending product selection is inspectable without payload exposure

- **WHEN** the selected Session has a valid pending product or order-line
  selection
- **THEN** the page shows its safe context/status summary and candidate count
- **AND THEN** it exposes no candidate id, source text or resolved-data value

#### Scenario: Malformed pending JSON is bounded

- **WHEN** the selected Session stores malformed pending state
- **THEN** the page reports only `invalid` pending encoding and a closed
  consistency state
- **AND THEN** it renders neither the payload nor a validation error

### Requirement: Authenticated local test channel processes only the selected draft

The panel SHALL expose one clearly labelled local-test message route beneath
its existing HTTP Basic authenticated route family. The route SHALL require a
same-origin custom request header and a bounded nonblank plain-text body. It
SHALL revalidate the exact selected Pedido, its active Session,
`session.id_pedido`, client/comercio association and `borrador` state before
calling the existing `process_incoming_message_with_responses` seam for that
exact Session. The existing transactional processor remains the only
transaction owner.

#### Scenario: Valid test message follows normal business processing without Twilio

- **WHEN** an authenticated operator submits a valid local-test message for
  the selected active draft
- **THEN** the exact session is processed once through the existing response
  orchestration and mapped responses are returned to the browser-only
  transcript
- **AND THEN** no provider receipt, provider work item, outbound row, lease,
  worker invocation or Twilio delivery is created

#### Scenario: Mismatched target cannot be redirected to another session

- **WHEN** the selected Pedido has a closed/missing Session, a different
  `session.id_pedido`, a non-draft state or a client/comercio mismatch
- **THEN** the route rejects without invoking the message pipeline
- **AND THEN** it does not search for another active session or mutate any
  record

### Requirement: Debug console transcript is volatile and escaped

The detail page SHALL render a responsive three-column console with local-test
chat (30%), current order detail/history (30%), and execution state (40%).
The chat SHALL state that it is local-only and not sent through WhatsApp or
Twilio. Its submitted and returned text SHALL be inserted as escaped plain
text and retained only for the current browser page lifetime; it SHALL use no
durable transcript, local storage, cookie or URL parameter.

#### Scenario: Operator text cannot become markup

- **WHEN** an authenticated operator submits text containing HTML-like
  characters
- **THEN** the transcript displays it as literal text
- **AND THEN** it does not execute markup or persist the transcript
