# Order-management API security

## ADDED Requirements

### Requirement: Order-management API routes require one configured administrative credential

Every route provided by the `pedidos` and `pedido_productos` routers SHALL
require a request `X-Admin-Token` that matches the configured administrative
token using a constant-time comparison. The configured token SHALL have no
source-controlled default and SHALL NOT be logged, returned, or persisted.

#### Scenario: Missing or wrong client credential is rejected before business work

- **WHEN** a protected route receives an absent, blank, malformed, or
  non-matching credential
- **THEN** it returns `401 Unauthorized` with a fixed non-sensitive response
- **AND** it does not open a database session, invoke a service, or mutate data

#### Scenario: Matching credential preserves existing behavior

- **WHEN** a protected route receives a matching credential
- **THEN** it continues through its existing request validation, service,
  transaction, state-transition, and response behavior unchanged

### Requirement: Missing server configuration fails closed without exposing the secret state

When the administrative token is absent or blank in server configuration, every
protected route SHALL return `503 Service Unavailable` with a fixed
non-sensitive response. It SHALL NOT treat a request token as a replacement
configuration source or fall back to an open route.

#### Scenario: Misconfigured deployment does not expose order data

- **WHEN** the server has no usable configured administrative token
- **THEN** a request to any protected order-management route returns `503`
- **AND** no database/session/service work occurs
- **AND** the response and logs do not include the configured or supplied token

### Requirement: Provider webhook authentication remains separate

This authorization boundary SHALL apply only to order-management routes. The
Twilio inbound webhook and delivery callback SHALL retain their existing
signature-validation behavior and SHALL NOT require `X-Admin-Token`.

#### Scenario: Provider request does not depend on the administrative token

- **WHEN** a valid Twilio-signed webhook request omits `X-Admin-Token`
- **THEN** it follows its existing signature-authenticated path
- **AND** the administrative route dependency is not evaluated
