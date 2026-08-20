# Capability: Railway test provisioning for the Twilio Emulator

## ADDED Requirements

### Requirement: The test environment SHALL provide an isolated emulator service

Railway `core/test` SHALL provide a dedicated `twilio-emulator` service running
the existing `twilio_emulator` application with an explicit start command,
Railway `$PORT` binding and `GET /health` healthcheck. The service SHALL not
run the NovaOrders worker, migrations or business database code.

#### Scenario: Emulator service starts independently

- **WHEN** Railway starts the test-only emulator service with all required
  `EMULATOR_*` variables
- **THEN** the service listens on Railway's assigned port
- **AND THEN** `GET /health` returns HTTP 200
- **AND THEN** no NovaOrders migration, worker or real Twilio process starts

#### Scenario: Emulator service configuration is incomplete

- **WHEN** a required emulator URL, control token or synthetic credential is
  missing or malformed
- **THEN** the emulator refuses to accept traffic or fails startup according
  to its existing fail-closed contract
- **AND THEN** no core or T-C emulator activation is performed

### Requirement: Core and T-C SHALL share an explicit test-only emulator contract

The operator SHALL configure `supernova-ia` and `tc-comercio-1` with the exact
emulator mode, HTTPS base URL and synthetic credentials required by their
existing transport seams. The emulator, core and T-C SHALL use one identical
synthetic account SID/auth-token pair, while real Twilio credentials remain
separate and unchanged.

#### Scenario: Coordinated emulator configuration is valid

- **WHEN** the emulator is healthy and core/T-C have matching synthetic
  credentials, HTTPS emulator URL and explicit emulator mode
- **THEN** core and T-C accept the emulator configuration
- **AND THEN** the admin emulator action becomes eligible for display
- **AND THEN** the real Twilio transport is not selected

#### Scenario: Emulator configuration is mismatched

- **WHEN** core, T-C and emulator use different synthetic credentials, an
  invalid URL or an incomplete mode configuration
- **THEN** the relevant process fails closed or the admin action remains
  unavailable
- **AND THEN** no request falls back to real Twilio

### Requirement: The emulator action SHALL remain restricted to test

Emulator mode and the admin/pilot emulator action SHALL be enabled only in
Railway `test` after the dedicated emulator service is healthy. Production and
`calibracion` SHALL retain their existing provider behavior and SHALL not
receive emulator credentials or activation flags.

#### Scenario: Test-only activation

- **WHEN** the operator enables the complete contract in `test`
- **THEN** the authenticated active-order panel can show
  `Enviar por Twilio Emulator`
- **AND THEN** the existing local-only action remains available
- **AND THEN** no production or calibration configuration changes

#### Scenario: Non-test environments remain unchanged

- **WHEN** the emulator service is deployed or configured for `test`
- **THEN** production and `calibracion` remain in their previous mode
- **AND THEN** their admin panels do not expose the test emulator action

### Requirement: Provisioning SHALL preserve the existing asynchronous pipeline

The provisioned emulator SHALL drive the existing T-C webhook and outbound
Messages API seams only. It SHALL not introduce a second worker, synchronous
business processor, durable emulator database or alternate admin route.

#### Scenario: End-to-end test uses existing boundaries

- **WHEN** an operator submits one valid emulator message for an active test
  order
- **THEN** the emulator signs the inbound for the configured T-C webhook
- **AND THEN** the existing ingress, coordinator, worker, outbox and T-C
  outbound route process it
- **AND THEN** the emulator returns only a synthetic provider identifier
- **AND THEN** the browser can observe the existing bounded status projection

#### Scenario: Emulator transport is unreachable

- **WHEN** the emulator or its configured T-C webhook is unreachable
- **THEN** the admin action returns its bounded technical failure
- **AND THEN** no local direct processing or real Twilio fallback occurs

### Requirement: Provisioning SHALL be reversible without data repair

Disabling the explicit emulator modes and removing the test-only service or
variables SHALL restore the prior local-panel and real-provider behavior.
Provisioning SHALL not require a database migration or deletion of durable
NovaOrders provider rows.

#### Scenario: Test rollback

- **WHEN** the operator disables emulator mode on core and T-C
- **THEN** the admin emulator action becomes unavailable
- **AND THEN** the existing local-only action remains available
- **AND THEN** no synthetic provider request is created by the rollback

#### Scenario: Production safety during rollback

- **WHEN** the test emulator service is stopped or removed
- **THEN** production and `calibracion` remain unchanged
- **AND THEN** no production credential, webhook or provider configuration is
  altered
