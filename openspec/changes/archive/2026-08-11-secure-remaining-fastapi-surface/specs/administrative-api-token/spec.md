# Administrative API token

## ADDED Requirements

### Requirement: Remaining administrative routers use the shared token boundary

Every router classified administrative SHALL require the existing
`require_admin_token` dependency at router scope. The dependency SHALL retain
its configured-token, constant-time comparison, fixed `401`/`503`, no-fallback,
no-session-first, and non-leakage contracts.

#### Scenario: Unauthorized direct message processing cannot invoke the pipeline

- **WHEN** a request without a valid token reaches the administrative
  incoming-message HTTP route
- **THEN** it returns the shared authorization outcome before session lookup,
  classifier, intent processing, response mapping, or mutation

#### Scenario: Authorized administrative catalog route preserves behavior

- **WHEN** a request with a valid token reaches an administrative catalog or
  configuration route
- **THEN** its existing validation, service behavior, transaction ownership,
  and response contract remain unchanged

### Requirement: Local embedding administration has both required gates

The embedding-admin routes SHALL require a valid administrative token and keep
their existing local-admin enablement gate. A disabled endpoint SHALL retain
its existing `404` behavior after successful authentication.

#### Scenario: Enabled embedding admin route rejects an unauthorized caller

- **WHEN** the local-admin flag is enabled and the request has no valid token
- **THEN** the request receives the shared authorization outcome before any
  embedding/database work
