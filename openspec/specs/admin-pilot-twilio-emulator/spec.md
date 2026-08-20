# Capability: admin-pilot-twilio-emulator

## Purpose

Provide a cost-free, provider-shaped test path from the admin/pilot console
through the existing commerce-isolated T-C and NovaOrders processing flow.
The emulator replaces Twilio transport only when explicitly enabled in a test
environment; real provider behavior remains the default elsewhere.

## Requirements

### Requirement: The emulator covers the inbound and outbound Twilio boundaries

The system SHALL provide a standalone `twilio_emulator` with an authenticated
inbound control surface and a Twilio-shaped outbound Messages API. The inbound
surface SHALL generate a unique synthetic provider message identifier, sign
the complete form with generated test credentials and forward it only to the
configured T-C webhook. The outbound surface SHALL validate the generated
credentials, capture the bounded command and return a unique synthetic
`MessageSid` without contacting the real Twilio service.

#### Scenario: Simulated inbound uses the real T-C webhook contract

- **WHEN** an authenticated emulator control command supplies a valid test
  source, destination and body
- **THEN** the emulator sends a complete signed Twilio-shaped form to the
  configured T-C webhook
- **AND THEN** the existing T-C signature validation, canonical event
  normalization and NovaOrders ingress path execute
- **AND THEN** no real Twilio endpoint is contacted

#### Scenario: Simulated outbound returns a fake provider acceptance

- **WHEN** the T-C outbound route runs in emulator mode with a valid command
- **THEN** it sends the provider-shaped request to the emulator Messages API
- **AND THEN** the emulator returns a unique synthetic `SM...` identifier
- **AND THEN** the existing T-C route and NovaOrders dispatcher finalize the
  existing outbox row using the normal typed sent outcome
- **AND THEN** no real Twilio SDK or network call is invoked

### Requirement: Emulator mode is explicit and fails closed

The T-C and central Twilio transport seams SHALL support an explicit
`real`/`emulator` mode with `real` as the default. Emulator mode SHALL require
the test-only emulator URL, control/authentication configuration and
Twilio-shaped generated credentials. Missing, malformed or contradictory
configuration SHALL prevent the relevant process from accepting traffic.

#### Scenario: Real mode remains unchanged

- **WHEN** provider mode is omitted or set to `real`
- **THEN** existing Twilio transport behavior and configuration remain in
  effect
- **AND THEN** no emulator code path is selected

#### Scenario: Emulator configuration cannot fall through to real Twilio

- **WHEN** emulator mode is enabled but the emulator URL or generated
  credentials are unavailable
- **THEN** startup or the bounded provider action fails closed
- **AND THEN** zero real Twilio calls are attempted

### Requirement: Admin/pilot exposes an explicit emulator action

The admin/pilot detail page SHALL preserve the existing local-only action and
add a separate authenticated action labelled as a Twilio-emulator test. The
new action SHALL validate the exact selected active Session, Pedido, Cliente,
Comercio, dedicated channel and active T-C installation. It SHALL reject an
unavailable commerce, an inactive/missing installation, cross-commerce
identity mismatch or disabled emulator configuration without invoking a
local processor, real T-C, central Twilio or real provider.

#### Scenario: Admin test traverses the existing provider pipeline

- **WHEN** an authenticated operator submits a valid emulator test message
  for the exact selected active order
- **THEN** NovaOrders asks the emulator to deliver the inbound through the
  configured T-C webhook
- **AND THEN** the existing T-C ingress, NovaOrders coordinator, provider
  worker, outbox dispatcher and T-C outbound command path process the message
- **AND THEN** the browser receives a bounded test identifier for status
  polling

#### Scenario: Existing local chat remains local-only

- **WHEN** an operator uses the existing `local-test` action
- **THEN** it keeps its current direct local behavior
- **AND THEN** it does not contact the emulator, T-C, Twilio, provider
  coordinator, worker or outbox

### Requirement: Emulator test status is asynchronous and exact

The admin/pilot SHALL provide a read-only status projection scoped to the
exact selected Pedido/Session and synthetic inbound identifier. The projection
SHALL read the existing provider receipt/outbox state and expose only bounded
inbound/outbound status, synthetic provider identifiers and the outbound test
text required by the authenticated console. It SHALL not create a second
source of truth or invoke the worker synchronously.

#### Scenario: Worker-delayed outbound becomes visible

- **WHEN** the emulator accepts the inbound but the worker has not yet
  processed the deferred work
- **THEN** status polling reports a bounded pending/accepted state
- **AND THEN** after the existing worker and dispatcher complete, polling
  reports the existing processed/sent state and the simulated outbound text

#### Scenario: Status cannot cross order or commerce boundaries

- **WHEN** a polling request supplies another Pedido, Session, commerce or
  synthetic inbound identifier
- **THEN** the route returns the generic bounded rejection
- **AND THEN** it does not disclose another provider receipt or outbox row

### Requirement: Simulated provider identities and observability are safe

Generated emulator credentials, signatures, raw forms, customer addresses,
message bodies and arbitrary operator input SHALL never appear in operational
logs or exception text. Emulator/admin events SHALL use the existing safe
structured event catalogue with closed outcomes and no raw payload fields.

#### Scenario: Test credentials are not exposed

- **WHEN** the emulator starts, signs an inbound request or authenticates an
  outbound request
- **THEN** credentials and signatures remain in process/configuration memory
- **AND THEN** they are absent from logs, browser responses and error bodies

### Requirement: The emulator is reversible and cannot alter production

Disabling emulator mode SHALL restore the existing real T-C and central
transport paths. The emulator SHALL be disabled by default and SHALL not
change commerce activation, provider credentials, worker cadence, leases,
retries, TwiML contracts or real deployment behavior.

#### Scenario: Disabling the emulator restores real transport defaults

- **WHEN** emulator mode is disabled in the test configuration
- **THEN** the admin emulator action is unavailable
- **AND THEN** the existing local-only admin action and real provider
  transport configuration remain unchanged
- **AND THEN** no emulator request or synthetic provider message is created