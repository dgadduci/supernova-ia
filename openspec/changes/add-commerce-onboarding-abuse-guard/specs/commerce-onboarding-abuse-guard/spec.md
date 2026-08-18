## ADDED Requirements

### Requirement: An external guard authorizes magic-link issuance

The system SHALL expose a separately deployable HTTPS abuse-guard endpoint
that accepts only an authenticated magic_link decision request and returns a
bounded allowed boolean plus non-empty opaque decision_id for every valid
decision. The guard SHALL not query Supabase or NovaOrders identity data.

#### Scenario: Valid request below limits is authorized

- **WHEN** the caller presents the configured Bearer token and a valid
  syntactically valid email/action request is below every configured limit
- **THEN** the guard SHALL return HTTP 200 with allowed=true and a non-empty
  opaque decision_id
- **AND THEN** the NovaOrders adapter MAY continue to Supabase OTP

#### Scenario: Rate-limited request is denied

- **WHEN** a valid authenticated request exceeds the email, IP or email+IP
  limit
- **THEN** the guard SHALL return HTTP 200 with allowed=false and a non-empty
  opaque decision_id
- **AND THEN** NovaOrders SHALL not call Supabase OTP or issue a PKCE cookie

### Requirement: Abuse state is distributed and bounded

The guard SHALL use a shared Redis-backed atomic limiter so decisions remain
consistent across service replicas. Limiter keys SHALL be keyed hashes of
normalized identifiers, and every counter SHALL have a finite TTL.

#### Scenario: Concurrent requests share the same decision state

- **WHEN** concurrent guard requests target the same normalized email, IP or
  pair across one or more service instances
- **THEN** the atomic Redis operation SHALL prevent every request from passing
  a single-token window
- **AND THEN** expired windows SHALL become eligible again after their TTL

### Requirement: Guard failures fail closed

The guard SHALL fail closed for missing/invalid credentials, malformed input,
invalid configuration, Redis timeout/connection/command failure and malformed
internal state. It SHALL never substitute an in-memory permissive limiter.

#### Scenario: Redis is unavailable

- **WHEN** the guard cannot prove a Redis decision
- **THEN** it SHALL return a bounded non-2xx response
- **AND THEN** NovaOrders SHALL not call Supabase OTP or issue a PKCE cookie

#### Scenario: Caller authentication is invalid

- **WHEN** the Bearer token is missing or does not match the configured secret
- **THEN** the guard SHALL return a bounded authentication failure
- **AND THEN** it SHALL not touch Redis or reveal the expected token

### Requirement: Guard privacy and operational boundaries are preserved

The guard SHALL not log raw emails, IPs, request bodies, Authorization headers,
Redis URLs, tokens or provider responses. It SHALL expose bounded health and
readiness outcomes without secrets. It SHALL not import or mutate NovaOrders
models, repositories, sessions, transactions or commerce data.

#### Scenario: Health checks do not disclose secrets

- **WHEN** an operator calls the guard health/readiness endpoint
- **THEN** the response SHALL contain only bounded status data
- **AND THEN** it SHALL not include Redis connection details, counters,
  credentials or identifiers
