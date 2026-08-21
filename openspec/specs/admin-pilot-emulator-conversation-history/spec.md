# Capability: admin-pilot-emulator-conversation-history

## Purpose

Provide a bounded, scrollable conversation history on the Admin/Pilot Twilio
Emulator console so the operator can review and select the history of
operator messages and NovaOrders pipeline responses for the current order
detail page. The history is volatile page state scoped to the existing
provider contract: it shares the submit, status and rejection boundaries of
the dedicated Twilio Emulator action and never persists across reloads,
never reaches the database, never touches Twilio real and never replaces the
existing local-only transcript.

## Requirements

### Requirement: The Emulator panel displays a scrollable chronological conversation

The Admin/Pilot detail page SHALL display a dedicated, fixed-viewport
conversation list for the Twilio Emulator action. The list SHALL distinguish
messages sent by the operator from responses received from the existing
provider pipeline, preserve chronological order and remain manually
scrollable. The list SHALL be limited to the current page and SHALL not
persist history.

#### Scenario: A sent message appears immediately in the conversation

- **WHEN** the operator submits a valid message through the existing Twilio
  Emulator form
- **THEN** the conversation list adds one clearly labeled `Enviado` entry
- **AND THEN** the entry contains the bounded submitted text
- **AND THEN** the list remains in its own fixed-height vertical scroll context

#### Scenario: A received response is added without replacing prior turns

- **WHEN** the existing status polling obtains a bounded outbound response
- **THEN** the conversation list adds or updates one clearly labeled
  `Respuesta recibida` entry for the corresponding sent message
- **AND THEN** previous sent messages and responses remain visible in
  chronological order
- **AND THEN** the list scrolls to the newest entry

### Requirement: Conversation turns are scoped to the current page and synthetic inbound

The browser SHALL associate each Emulator conversation turn with the exact
`synthetic_inbound_id` returned by the existing submit contract. Repeated
status polls for the same identifier SHALL update the existing turn and SHALL
NOT duplicate its response or error entry. The implementation SHALL not add a
backend persistence model or a new source of truth.

#### Scenario: Repeated polling does not duplicate a response

- **WHEN** the status endpoint returns the same terminal response more than
  once for one synthetic inbound identifier
- **THEN** the UI keeps one sent entry and one received-response entry for that
  turn
- **AND THEN** the status may update in place without adding duplicate rows

#### Scenario: Multiple messages preserve submission order

- **WHEN** the operator submits two or more messages sequentially
- **THEN** each message has its own turn keyed by its own synthetic inbound
  identifier
- **AND THEN** the visible order matches submission order and each response
  remains associated with its originating turn

### Requirement: Pending and failed outcomes remain bounded and truthful

The conversation list SHALL use the existing allowed Emulator statuses and
generic rejection behavior. It SHALL show pending/accepted states without
inventing a response, show a bounded response body only when provided, and
show bounded generic failure/status information for retryable, terminal,
transport or rejected outcomes.

#### Scenario: Pending processing does not invent a response

- **WHEN** the Emulator accepts a message but the worker or dispatcher has not
  produced an outbound body
- **THEN** the UI shows the sent entry and a bounded pending/accepted state
- **AND THEN** it does not fabricate a received response

#### Scenario: A failure becomes one bounded error entry

- **WHEN** submission or polling ends in a generic rejection, retryable or
  terminal outcome
- **THEN** the UI shows one bounded error/status entry for that turn
- **AND THEN** it does not expose exception text, credentials, signatures,
  raw provider payloads or internal identifiers beyond the existing bounded
  synthetic/provider identifiers

### Requirement: Conversation rendering is safe, bounded and reversible

Operator messages and received response text SHALL be inserted using safe DOM
text APIs, not HTML sinks. The list SHALL have a bounded number of entries and
bounded display values. It SHALL not use localStorage, sessionStorage,
cookies, URL state or server persistence. The existing local-only transcript,
Emulator request contract, polling limits and provider pipeline SHALL remain
unchanged.

#### Scenario: HTML-like message text remains text

- **WHEN** an operator message or received response contains HTML-like text
- **THEN** the list renders it literally as text
- **AND THEN** it does not interpret or execute the text as markup or script

#### Scenario: Reload does not create persistent conversation state

- **WHEN** the operator reloads or leaves the order detail page
- **THEN** the volatile conversation list is not restored from browser or
  server storage
- **AND THEN** no new provider, T-C, worker or outbox action is triggered

#### Scenario: Existing local channel remains separate

- **WHEN** the operator uses the local-only form
- **THEN** its existing transcript and processing behavior remain unchanged
- **AND THEN** the Emulator conversation list does not become a second local
  processing path
