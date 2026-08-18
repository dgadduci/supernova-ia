# Proposal: add commerce onboarding abuse guard

## Objective

Provide the external, distributed abuse-decision boundary required before
NovaOrders asks Supabase Auth to send a magic link. The guard is a separately
deployable Railway service backed by Redis. It supports the existing Phase 2
SUPABASE_ABUSE_GUARD_URL / SUPABASE_ABUSE_GUARD_TOKEN contract without adding
a permissive limiter, persistence model or transaction to NovaOrders.

The first release is suitable for staging and has a production-safe failure
model. Production activation still requires separate operational approval for
Railway services, Redis durability/backups, domains and secrets.

## Current execution path

backend/routers/public_onboarding.py validates the email, requires HTTPS and
calls backend.auth.abuse_guard.request_magic_link_authorization before calling
Supabase /auth/v1/otp. The caller accepts only a valid decision with
allowed=true; missing, denied, malformed or unavailable guard responses stop
the flow and render the bounded 503 view. The current identity PR depends on
this external boundary but does not implement the guard service.

## Scope

- Add a standalone abuse-guard service that can run as a second Railway
  service, independent of backend.main:app.
- Authenticate callers with a required Bearer token and compare it without
  leaking the configured secret.
- Normalize an email and accept the caller-provided remote IP as limiter input;
  never query Supabase or NovaOrders user data.
- Use Redis as the shared, atomic state store for bounded email, IP and
  email+IP windows. Counters must expire automatically.
- Return the existing decision contract: allowed boolean and non-empty
  decision_id for every valid decision.
- Fail closed when configuration, authentication, Redis, request parsing or
  response construction is unsafe.
- Add focused unit/contract/concurrency-oriented tests and deployment notes for
  a separate Railway service and private Redis connection.

## Non-goals

- No changes to the NovaOrders Phase 2 identity router, Supabase client, JWT,
  PKCE, session or callback implementation.
- No account, membership, draft, commerce, order, catalog, lifecycle, channel,
  Twilio or NovaOrders database changes.
- No in-process limiter, local-file state, browser CAPTCHA, bot-scoring system,
  email reputation lookup or Supabase user enumeration.
- No Railway/Supabase/DNS/Redis provisioning, secret creation, deployment,
  production activation, commit, sync or archive.
- No guarantee that the initial limits are correct for production traffic;
  tuning and capacity review remain operational gates.

## Shared boundary

~~~text
NovaOrders web service --HTTPS + Bearer token--> Abuse guard --private--> Redis
        |                                            |
        +-- allowed=true + decision_id ------------+
        +-- allowed=false / error -> no Supabase OTP
~~~

The guard is the authoritative anti-abuse decision for the link request. A
successful decision does not authenticate a user and does not grant commerce
authorization; Supabase remains authoritative for identity.

## Authoritative outcomes and fallback

### Valid business outcomes

- allowed=true with a non-empty opaque decision_id: the NovaOrders caller may
  continue to Supabase OTP.
- allowed=false with a non-empty opaque decision_id: the caller must not
  contact Supabase. The current router renders its bounded generic 503.

### Technical failures

- Missing or invalid Bearer token.
- Missing/invalid JSON, email or action.
- Missing or invalid limiter configuration.
- Redis timeout, connection failure, command failure or malformed result.
- Internal exception or inability to create a decision identifier.

### Exact fallback conditions

Every technical failure returns a non-2xx response from the guard, without
details that identify the email, IP, Redis topology or secret. The NovaOrders
adapter maps that result to its existing fail-closed 503 behavior.

### Conditions that must not trigger fallback

- A valid request below all configured limits must return allowed=true.
- A valid request above a configured limit must return allowed=false, not
  allowed=true and not a provider call.
- The guard must never consult Supabase to decide whether an email exists.

## Security and privacy

- The guard endpoint is HTTPS-only and requires Authorization: Bearer.
- ABUSE_GUARD_TOKEN and ABUSE_GUARD_HASH_SECRET are required secrets; neither
  has a committed/default value.
- Redis is private to the Railway project or managed provider; no public Redis
  port is part of the design.
- Redis keys use keyed hashes of normalized email and IP so raw identifiers do
  not become persistent key material. Values are counters with short TTLs.
- Responses contain only allowed and decision_id on valid decisions. Logs
  contain bounded event names and reason categories, never raw email, IP,
  Authorization headers, Redis URLs or tokens.
- Decision IDs are opaque random identifiers and are not an identity claim.

## Rate policy

The service exposes explicit configuration with conservative defaults:

| Dimension | Default window | Default maximum |
| --- | ---: | ---: |
| Normalized email | 60 seconds | 1 |
| IP address | 900 seconds | 5 |
| Email + IP pair | 3600 seconds | 3 |

All limits and windows are positive bounded integers. Exact production values
require traffic observation and operational approval; changing them is
configuration-only and reversible.

## Transaction ownership

The guard owns only atomic Redis counter operations. It opens no SQLAlchemy
session, owns no NovaOrders transaction and cannot create or mutate a user,
commerce, order, channel or outbound record. Redis counter expiry is the only
state mutation and is automatically reversible by TTL.

## Observability

Emit bounded events/counters such as guard_allowed, guard_denied_rate,
guard_auth_rejected, guard_redis_unavailable and guard_config_invalid.
Include environment-safe reason categories and latency; do not include raw
identifiers or request bodies. A health/readiness endpoint must make Redis
availability observable without echoing connection details.

## Expected files

- abuse_guard/app.py — standalone HTTP boundary and response contract.
- abuse_guard/config.py — fail-closed environment parsing and bounded limits.
- abuse_guard/limiter.py — normalized/hash keys and atomic Redis windows.
- abuse_guard/requirements.txt — minimal service dependencies only.
- abuse_guard/Dockerfile — independent Railway service image/entrypoint.
- abuse_guard/tests/ — focused contract, auth, limiter and failure tests.
- abuse_guard/README.md — local run, Railway service variables and private
  Redis reference guidance; no real secrets.
- OpenSpec proposal, design, spec delta and tasks files for this change.

No root application entrypoint, root Dockerfile, root requirements file,
Railway manifest, Supabase configuration or NovaOrders model is required.

## Focused tests

- Valid Bearer token plus below-limit request returns 200, allowed=true and an
  opaque decision_id.
- Repeated email/IP/pair requests return allowed=false at the configured
  boundary and never expose the identifiers.
- Missing, malformed or wrong token is rejected without touching Redis.
- Malformed input and unsupported action are rejected safely.
- Redis unavailable, timeout, command failure and malformed result fail closed.
- Counter keys are hashed, TTL-bound and updated atomically; concurrent calls
  cannot all pass a single-token window.
- Health/readiness behavior is bounded and does not expose secrets.
- The service has no imports from backend models, repositories, services,
  dependencies or NovaOrders routers.

## Validation commands

The implementer must run and report complete output for:

~~~text
PYTHONPATH=abuse_guard venv/bin/python -m pytest abuse_guard/tests -q
PYTHONPATH=abuse_guard venv/bin/ruff check abuse_guard
PYTHONPATH=abuse_guard venv/bin/python -m compileall -q abuse_guard
openspec validate add-commerce-onboarding-abuse-guard --strict
git diff --check
~~~

The commands must run without a live Redis or Railway service by using an
injected fake/test transport or deterministic Redis test double. No test may
contact a real external service.

## Rollback and reversibility

Disable/remove the separate guard service or unset the NovaOrders guard URL and
token to stop issuance safely; the existing Phase 2 router then returns its
bounded 503 outcome. Redis counters expire automatically. Rollback does not
delete NovaOrders data because this change creates none.

## Deferred limitations

- No CAPTCHA or advanced bot intelligence in this change.
- No multi-region Redis consistency or automated capacity scaling decision.
- No production traffic-derived limit tuning, SLO, backup policy or incident
  runbook until the operator approves the Railway/Redis deployment plan.
- The current Phase 2 implementation accepts the legacy JWT-shaped Supabase
  anon key; new sb_publishable key support remains a separate change.

## Decisions required before implementation/deployment

1. Approve the separate service boundary and default limit policy.
2. Choose Railway Redis versus an externally managed Redis provider, including
   backup/restore and monitoring expectations.
3. Approve a staging-only deployment before any production service, domain,
   secret, DNS or Railway mutation.
4. Approve production activation only after Minimax implementation and Codex
   review of tests, failure behavior and deployment evidence.
