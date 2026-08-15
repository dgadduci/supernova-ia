# pilot-order-operations-panel Specification

## Purpose
TBD - created by archiving change add-pilot-order-operations-panel. Update Purpose after archive.
## Requirements
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
same-origin custom request header and a bounded nonblank plain-text body. For
the exact selected active draft, it SHALL revalidate `session.id_pedido`,
client/comercio association, and `borrador` state before calling the existing
`process_incoming_message_with_responses` seam for that exact Session. The
existing transactional processor remains the only transaction owner for this
draft path.

For the exact selected active non-draft order, the route SHALL permit only a
clean-context, classifier-derived status query. It SHALL invoke the existing
classifier only to interpret language, accept only exactly one
`consultar_estado_pedido` result, and execute the existing read-only status
orchestration and shared response mapper. It SHALL reject every other
classifier result, multi-intent result, classifier failure, pending context,
or identity/ownership inconsistency using the existing generic rejection. It
SHALL NOT invoke the normal message processor, global dispatcher, mutating
handler, provider, worker, outbox, or Twilio path for a non-draft order.

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
  `session.id_pedido`, or a client/comercio mismatch
- **THEN** the route rejects without invoking either the draft message pipeline
  or the confirmed-order status branch
- **AND THEN** it does not search for another active session or mutate any
  record

#### Scenario: Flexible status language is allowed only for the exact confirmed order

- **WHEN** an authenticated operator submits a local message for an exact
  active selected order in a non-draft state with no pending context
- **AND WHEN** the existing classifier returns exactly one
  `consultar_estado_pedido` intent from natural-language status phrasing
- **THEN** the route returns the existing read-only status response and safe
  snapshot for that same order/session identity
- **AND THEN** it does not create, replace, reopen, or modify a session, order,
  order line, pending context, provider row, or outbox row.

#### Scenario: Confirmed-order classifier output cannot authorize a mutation

- **WHEN** an authenticated operator submits a local message for an exact
  active selected order in a non-draft state
- **AND WHEN** classifier output is non-status, multi-intent, invalid, or fails
- **THEN** the route emits the existing generic local rejection without calling
  the normal message processor or any business mutation path
- **AND THEN** it does not search for a successor session or another order.

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

### Requirement: Local-test transcript has a fixed scroll viewport

The local-test transcript SHALL retain one fixed responsive viewport height.
Appending operator or customer turns SHALL scroll within that viewport and
SHALL NOT increase the height of the chat column or the surrounding debug grid.
Its text SHALL continue to wrap and be inserted as escaped plain text.

#### Scenario: Many turns do not expand the console

- **WHEN** an operator submits enough local-test turns to exceed the transcript
  viewport
- **THEN** the transcript scrolls to the newest turn inside its fixed viewport
- **AND THEN** the order-detail and execution-state columns retain their layout
  height independently of those turns.

### Requirement: Successful local turns refresh only safe execution state

For a successful local-test message, the route SHALL return the updated closed
execution-state summary for the same exact selected Session together with the
mapped customer responses. The browser SHALL update the existing execution
state cells in place using plain text APIs, without a full page reload. The
summary SHALL contain only the fields authorized for `PendingContextDebugView`
and SHALL NOT contain raw pending JSON, source text, resolved values,
candidate IDs, queue entries, diagnostics, exception detail, configuration,
credentials or provider data.

The pre-turn validation SHALL enforce the ``borrador``-only eligibility
contract for the exact selected Pedido. The post-turn snapshot projection
SHALL reload the exact same Pedido and Session by ``session.id`` AND
``session.id_pedido == pedido_id`` only; it SHALL NOT re-check
``borrador`` eligibility, SHALL NOT search for a successor session and
SHALL NOT fall back to another active session for the same
cliente/comercio. A successful turn that legitimately leaves the pedido in
``ingresado`` MUST still return the mapped responses and the refreshed
closed snapshot.

#### Scenario: Pending resolution updates the visible state

- **WHEN** a valid local-test turn changes the selected Session's pending
  context
- **THEN** the returned closed execution-state snapshot and the displayed
  execution-state cells reflect that same selected Session after the turn
- **AND THEN** the volatile transcript remains visible without a page reload.

#### Scenario: Confirm-order turn still refreshes the visible state

- **WHEN** a valid local-test turn legitimately flips the exact selected
  Pedido from ``borrador`` to ``ingresado`` while leaving the exact session
  identity intact
- **THEN** the route returns 200 with the mapped responses and a closed
  execution-state snapshot
- **AND THEN** the displayed execution-state cells are updated from that
  snapshot using plain text APIs
- **AND THEN** the route does not search for any other session, does not
  substitute a successor, and does not invoke any transactional control
  itself.

#### Scenario: Identity truly gone still preserves the documented rejection

- **WHEN** the post-turn snapshot loader cannot reload the exact Pedido or
  Session identity (for example the session was deleted or re-pointed to a
  different pedido during the turn)
- **THEN** the route returns the documented generic rejection
- **AND THEN** the browser keeps the previously displayed execution-state
  cells and only shows the existing generic local-test failure message.

#### Scenario: Rejected local submission preserves the displayed snapshot

- **WHEN** the local-test route rejects the request or the browser receives a
  malformed/non-success response
- **THEN** the browser retains the previously displayed execution-state cells
- **AND THEN** it shows only the existing generic local-test failure message.

### Requirement: Canonical cleared pending state is displayed as empty

The panel SHALL treat the successfully parsed canonical cleared pending state
(`active` absent and `queue` empty) as semantic `empty`, even when its stored
JSON has a valid schema version. With `context_type` absent it SHALL display
closed values `none / empty / none`, all counts zero and no displayed schema
version. It SHALL NOT mutate the stored pending JSON or report this canonical
state as inconsistent.

#### Scenario: Cleared product selection has no false inconsistency

- **WHEN** a successful product selection clears its pending context and the
  selected Session stores the canonical versioned empty pending object
- **THEN** the execution-state panel displays context `none`, pending `empty`
  and consistency `none`
- **AND THEN** it exposes no pending payload and does not alter the Session.

### Requirement: Diagnostic detail remains compact and scrollable

The local transcript SHALL use a fixed 12rem scroll viewport. The order-lines
section SHALL render all selected Pedido lines within its own bounded
scrollable container. Execution-state labels and their closed values SHALL
render as compact `nombre: valor` pairs while preserving the existing
`data-debug-*` value selectors. The verbose local-channel warning SHALL be
removed; a concise notice below the transcript SHALL state that the channel
does not send through WhatsApp/Twilio.

#### Scenario: Long diagnostic data remains accessible without expanding columns

- **WHEN** a transcript has many turns or a selected Pedido has more lines
  than fit in its visible section
- **THEN** each respective section scrolls internally and all turns/lines
  remain accessible
- **AND THEN** the panel does not expand those sections with content.

### Requirement: Successful local turns refresh exact order lines

For a successful local-test turn, the existing response SHALL include a typed,
JSON-safe `order_lines` snapshot for the same exact selected Pedido. It SHALL
contain only line id, product name, optional presentation description,
quantity, unit-price display value and optional line observation. The browser
SHALL replace the existing scrollable line-list contents in place using text
APIs, without a page reload or transcript loss. It SHALL NOT expose ORM,
Session/Pedido, pending, provider, diagnostic or credential data.

#### Scenario: Added product appears without manual reload

- **WHEN** a valid local-test turn adds a product line to an initially empty
  selected draft
- **THEN** the response returns that exact line in `order_lines`
- **AND THEN** the detail page replaces its empty-line message with the
  scrollable list row without a page reload.

### Requirement: Order lines lead the detail column

The scrollable order-lines list SHALL appear immediately below the “Detalle del
pedido” heading and before commerce, client, session and Pedido metadata. It
SHALL retain all rows in its bounded scroll container.

#### Scenario: Several lines remain visible at the top of detail

- **WHEN** the selected Pedido has several product lines
- **THEN** the operator finds their scrollable list at the start of the detail
  column and can access every row by scrolling that list.

