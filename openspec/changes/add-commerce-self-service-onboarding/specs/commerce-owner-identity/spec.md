## ADDED Requirements

### Requirement: Phase 2 Supabase magic link creates only an authenticated principal

During Phase 2, the system SHALL use a validated Supabase Auth email magic-link
session to authenticate a request principal. It SHALL validate the provider JWT
signature/key, issuer, audience, expiry and immutable subject before
application access. Phase 2 SHALL NOT create or update `CuentaUsuario`,
`ComercioUsuario`, an onboarding draft, a `Comercio`, a migration or any other
NovaOrders persistence. Authentication alone SHALL NOT authorize any commerce
resource.

#### Scenario: Verified magic-link subject receives a bounded Phase 2 session

- **WHEN** a valid provider session with a verified subject reaches the
  callback
- **THEN** the system SHALL establish only a short-lived local session carrying
  the validated subject
- **AND THEN** it SHALL show a bounded onboarding-not-enabled outcome
- **AND THEN** it SHALL not perform application persistence or authorize a
  commerce resource

#### Scenario: Link requests are enumeration-safe

- **WHEN** a visitor requests a magic link for any syntactically valid email
- **THEN** the system SHALL show the same neutral confirmation regardless of
  whether Supabase recognizes the email
- **AND THEN** it SHALL not expose provider identity errors or account
  existence

#### Scenario: Invalid provider token fails closed

- **WHEN** a provider JWT is missing, expired, has an unexpected issuer or
  audience, or fails signature validation
- **THEN** the system SHALL deny the request with a bounded authentication
  outcome before commerce business work
- **AND THEN** it SHALL not fall back to an email, browser claim or route ID

#### Scenario: Missing abuse protection fails closed

- **WHEN** the configured edge/application abuse guard is unavailable
- **THEN** the system SHALL not issue or resend a magic link
- **AND THEN** it SHALL return a bounded service-unavailable outcome without a
  permissive in-process fallback

### Requirement: Commerce ownership is membership-scoped

The system SHALL authorize commerce-owner actions from an active
`ComercioUsuario` membership for the authenticated `CuentaUsuario` and the
exact commerce. The initial role set SHALL contain only `OWNER`.

#### Scenario: Tampered commerce ID cannot cross tenant boundary

- **WHEN** an authenticated owner changes a commerce ID in a URL or form to a
  commerce without its active membership
- **THEN** the system SHALL return a bounded forbidden/not-found outcome
- **AND THEN** it SHALL not reveal, read or mutate the other commerce data
