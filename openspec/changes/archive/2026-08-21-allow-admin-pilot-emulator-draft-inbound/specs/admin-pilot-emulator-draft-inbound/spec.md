# Capability: admin-pilot-emulator-draft-inbound

## ADDED Requirements

### Requirement: Active draft orders accept the existing emulator action

The authenticated Admin/Pilot detail action `Enviar por Twilio Emulator` SHALL
accept an exact Pedido in `BORRADOR` state when it has the associated active
Session and all existing emulator, commerce, channel and T-C guards pass. The
action SHALL submit through the existing standalone emulator, T-C webhook,
provider coordinator, worker and outbox pipeline. It SHALL not directly create
or mutate a Session or Pedido.

#### Scenario: Valid active draft is submitted through the provider path

- **WHEN** an authenticated operator submits a valid message for the exact
  active Session whose associated Pedido is `BORRADOR`
- **THEN** the detail action sends one authenticated control request to the
  standalone Twilio Emulator using server-resolved provider addresses
- **AND THEN** the emulator forwards the provider-shaped inbound through the
  configured T-C webhook
- **AND THEN** the existing coordinator, worker and outbound pipeline process
  the message for that same Session/Pedido
- **AND THEN** no local-only processor, real Twilio endpoint or direct business
  mutation is invoked

#### Scenario: Draft state is not changed by the detail action

- **WHEN** the detail action accepts a message for an active draft
- **THEN** the route does not transition the Pedido to `INGRESADO` or another
  state
- **AND THEN** any lifecycle transition remains owned by the normal business
  processing path

### Requirement: Draft eligibility preserves exact identity and isolation

The active-draft extension SHALL preserve the existing exact Pedido/Session
association, active-Session, client, commerce, dedicated-channel,
availability, active-installation and explicit-emulator guards. Invalid targets
SHALL be rejected before any emulator request and SHALL not fall back to local
processing or real Twilio.

#### Scenario: Invalid draft target is rejected before downstream work

- **WHEN** the selected draft is detached, associated with an inactive or
  different Session, closed through an invalid lifecycle state, or mismatched
  to the requested client or commerce
- **THEN** the action returns the existing generic bounded rejection
- **AND THEN** it makes no emulator, T-C, coordinator, worker or outbox call
- **AND THEN** it performs no business-record mutation

#### Scenario: Operational guards still fail closed

- **WHEN** the exact active draft has unavailable commerce, no active dedicated
  channel, no active T-C installation or disabled/incomplete emulator
  configuration
- **THEN** the action is rejected before provider submission
- **AND THEN** it does not select a different commerce, channel, installation
  or provider mode

#### Scenario: Existing non-draft behavior remains unchanged

- **WHEN** an operator submits an eligible non-draft order through the existing
  detail emulator action
- **THEN** the same prior target checks, provider pipeline and bounded status
  behavior remain in effect
- **AND THEN** the change does not broaden eligibility to arbitrary orders

### Requirement: Consecutive draft messages reuse the existing active context

Distinct accepted emulator messages for the same exact active draft SHALL use
the existing synthetic provider receipt, worker, pending-context and outbox
semantics. The detail action SHALL not create a second active Session,
successor Pedido or parallel processing pipeline.

#### Scenario: Two messages use the same draft context

- **WHEN** the operator submits two valid messages sequentially for the same
  active draft
- **THEN** each accepted message enters the existing provider pipeline with
  its own synthetic inbound identifier
- **AND THEN** both messages remain scoped to the same active Session/Pedido
- **AND THEN** no replacement Session or Pedido is created by the Admin/Pilot
  route

#### Scenario: Duplicate synthetic inbound remains idempotent

- **WHEN** the same synthetic provider inbound identifier is delivered again
  for the exact active draft
- **THEN** existing duplicate receipt handling determines the outcome
- **AND THEN** the message is not replayed as a second business event
- **AND THEN** no alternate target or fallback transport is selected

### Requirement: Draft status remains bounded and exact

The existing Admin/Pilot emulator status projection SHALL accept the exact
active draft target and synthetic inbound identifier. It SHALL expose only the
existing bounded receipt/outbox status and test text, without creating state,
running the worker synchronously or disclosing another order or commerce.

#### Scenario: Delayed processing is visible for the selected draft

- **WHEN** the emulator accepts an inbound for the exact active draft but the
  worker or dispatcher has not completed
- **THEN** status polling reports the existing bounded accepted or pending
  outcome
- **AND THEN** after normal processing it reports the existing processed or
  sent outcome and bounded simulated outbound text

#### Scenario: Status cannot cross target boundaries

- **WHEN** a status request supplies another Pedido, Session, commerce or
  synthetic inbound identifier
- **THEN** the route returns the generic bounded rejection
- **AND THEN** it does not disclose or query another receipt or outbox row

### Requirement: The extension is reversible and transaction ownership is preserved

The change SHALL remain code-only and reversible. The detail target loader and
routes SHALL remain read-only and SHALL not commit, rollback, flush, refresh,
begin or close the caller-owned SQLAlchemy session. Disabling emulator mode
SHALL continue to prevent emulator submission while preserving the local-only
action and real-provider defaults.

#### Scenario: Route does not own the business transaction

- **WHEN** a valid active-draft message is submitted
- **THEN** the route only validates the target and invokes the existing
  authenticated emulator control surface
- **AND THEN** inbound acceptance and business processing remain owned by the
  existing coordinator and worker transactions

#### Scenario: Emulator disablement restores the prior boundary

- **WHEN** explicit emulator mode is disabled or its required configuration is
  incomplete
- **THEN** the active-draft emulator action is unavailable or rejected
- **AND THEN** the local-only detail action and real-provider configuration are
  unchanged
- **AND THEN** no synthetic provider message is created
