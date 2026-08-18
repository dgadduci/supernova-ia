## ADDED Requirements

### Requirement: Supabase magic link authenticates but does not authorize a commerce

The system SHALL use a validated Supabase Auth email magic-link session to
authenticate an account. It SHALL validate the provider JWT signature/key,
issuer, audience, expiry and immutable subject before application access.
Authentication alone SHALL NOT authorize any commerce resource.

#### Scenario: Verified magic-link account receives its private onboarding scope

- **WHEN** a valid provider session with a verified subject reaches the
  callback
- **THEN** the system SHALL create or update only the matching
  `CuentaUsuario` projection for that subject
- **AND THEN** it SHALL redirect to that account's private onboarding scope

#### Scenario: Invalid provider token fails closed

- **WHEN** a provider JWT is missing, expired, has an unexpected issuer or
  audience, or fails signature validation
- **THEN** the system SHALL deny the request with a bounded authentication
  outcome before commerce business work
- **AND THEN** it SHALL not fall back to an email, browser claim or route ID

### Requirement: Commerce ownership is membership-scoped

The system SHALL authorize commerce-owner actions from an active
`ComercioUsuario` membership for the authenticated `CuentaUsuario` and the
exact commerce. The initial role set SHALL contain only `OWNER`.

#### Scenario: Tampered commerce ID cannot cross tenant boundary

- **WHEN** an authenticated owner changes a commerce ID in a URL or form to a
  commerce without its active membership
- **THEN** the system SHALL return a bounded forbidden/not-found outcome
- **AND THEN** it SHALL not reveal, read or mutate the other commerce data
