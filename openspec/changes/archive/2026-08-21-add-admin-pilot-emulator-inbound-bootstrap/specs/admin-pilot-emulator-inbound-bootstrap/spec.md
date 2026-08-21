# Capability: admin-pilot-emulator-inbound-bootstrap

## Purpose

Allow an authenticated Admin/Pilot operator to start a clean provider-shaped
inbound test using an existing client and commerce, while preserving the
existing T-C, NovaOrders provider worker and Twilio Emulator boundaries.

## ADDED Requirements

### Requirement: Admin/Pilot can start a clean emulator inbound

The Admin/Pilot orders list SHALL expose a clearly labelled bootstrap action
with bounded controls for `cliente_id`, `comercio_id` and a nonblank plain-text
message. The action SHALL authenticate with the existing Admin/Pilot contract,
require the existing same-origin protection and call the existing emulator
inbound control surface only after server-side validation.

#### Scenario: Valid bootstrap uses server-resolved provider addresses

- **WHEN** an authenticated operator submits valid client and commerce IDs,
  a bounded message, an active client, an available commerce, an active
  dedicated Twilio channel and a valid emulator configuration
- **THEN** the route resolves the client's E.164 and the channel's destination
  E.164 on the server
- **AND THEN** it submits exactly one authenticated inbound command to the
  configured Twilio Emulator
- **AND THEN** it returns a bounded accepted result with the synthetic inbound
  identifier
- **AND THEN** the browser never receives a control token, Twilio credential,
  webhook URL, raw address or raw provider payload

#### Scenario: Bootstrap acceptance is not mistaken for worker completion

- **WHEN** the emulator accepts a valid bootstrap inbound
- **THEN** the panel reports that the inbound was accepted and processing is
  pending
- **AND THEN** it provides a bounded refresh path for the order list
- **AND THEN** the existing provider worker remains responsible for creating
  the active Session and draft Pedido

### Requirement: Bootstrap preserves the existing inbound pipeline

The bootstrap action SHALL use the emulator's authenticated inbound control
surface as its only downstream entry point. It SHALL NOT insert or mutate a
Session, Pedido, Cliente, channel, installation, receipt, processing row,
outbox row or commerce state directly, and SHALL NOT call the T-C webhook,
provider coordinator, worker, dispatcher or real Twilio directly.

#### Scenario: A first inbound creates the normal test order context

- **WHEN** the selected active client and commerce pair has no active Session
  and the emulator-delivered inbound reaches the existing provider worker
- **THEN** the existing processing path creates one active Session for that
  client/commerce pair
- **AND THEN** it creates one associated empty `borrador` Pedido
- **AND THEN** the message is processed and the existing outbound path is used
  for the response

#### Scenario: Existing active context is not duplicated

- **WHEN** the selected client/commerce pair already has an active Session
- **THEN** the bootstrap action returns the generic bounded rejection
- **AND THEN** it does not close, replace or mutate that Session or Pedido
- **AND THEN** it does not call the emulator

### Requirement: Bootstrap validates the exact operational target

The route SHALL reject a missing/inactive client, unavailable commerce,
missing/inactive dedicated Twilio channel, missing/inactive T-C installation,
invalid IDs, blank/oversized message or disabled/incomplete emulator
configuration before contacting the emulator. Any rejected request SHALL use
the existing bounded rejection shape and SHALL not fall back to local
processing or real Twilio.

#### Scenario: Invalid target fails closed before transport

- **WHEN** any required target or emulator invariant is false
- **THEN** the route returns the generic rejected/unavailable response
- **AND THEN** no emulator, T-C, worker, dispatcher or real provider request is
  made
- **AND THEN** no database record is created or changed by the bootstrap route

#### Scenario: Cross-commerce addresses cannot be supplied by the browser

- **WHEN** the operator submits a client ID and commerce ID with an arbitrary
  address or target value in the request
- **THEN** the route ignores any address/target fields outside the approved
  input schema
- **AND THEN** it resolves both provider addresses from the selected database
  identities or rejects the request

### Requirement: Bootstrap is safe, bounded and reversible

The bootstrap form and route SHALL limit message length, escape rendered text,
prevent duplicate browser submission and emit only closed outcome/reason
categories without PII, secrets, URLs, raw payloads or exception details. The
route SHALL preserve request-level transaction ownership and SHALL perform no
commit, rollback, flush, refresh, begin or close operation.

#### Scenario: Operator input cannot leak or execute

- **WHEN** the operator submits HTML-like or secret-like text in the message
  field
- **THEN** the text is bounded and treated as plain text
- **AND THEN** it is not returned in an error body, rendered as markup or
  written to operational logs

#### Scenario: Disabling emulator mode removes the bootstrap path

- **WHEN** emulator mode is disabled or its required configuration is
  incomplete
- **THEN** the bootstrap action is unavailable or returns the bounded
  unavailable response
- **AND THEN** no synthetic inbound, order context or real Twilio request is
  created
- **AND THEN** the existing local-only action and real provider defaults remain
  unchanged
