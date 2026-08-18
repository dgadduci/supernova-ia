# Design: commerce onboarding abuse guard

## Boundary and deployment shape

The abuse guard is a small standalone FastAPI service packaged separately from
NovaOrders. Railway runs it as a second service from the same repository (or a
separately built service image) and provides a public HTTPS domain only for
the guard endpoint. Redis is a separate private service or managed Redis
instance; the guard is the only component that talks to it.

~~~text
Browser -> NovaOrders web service -> HTTPS /check + Bearer token
                                      Abuse guard -> private Redis
                                      response: allowed + decision_id
                         allowed=true -> Supabase /auth/v1/otp
                         otherwise    -> bounded 503, no provider call
~~~

The current web-service adapter remains unchanged. This change implements the
external endpoint it already expects.

## HTTP contract

### Request

POST /check with:

~~~http
Authorization: Bearer <ABUSE_GUARD_TOKEN>
Content-Type: application/json
Accept: application/json
~~~

~~~json
{
  "email": "owner@example.com",
  "action": "magic_link",
  "remote_ip": "203.0.113.10"
}
~~~

remote_ip is optional because the caller may not have a trustworthy client
address. The guard must not infer identity from it and must not accept any
action other than magic_link.

### Valid response

For both allow and deny decisions, return HTTP 200 with exactly the bounded
decision fields:

~~~json
{
  "allowed": true,
  "decision_id": "opaque-random-id"
}
~~~

allowed=false is an authoritative rate decision. Non-2xx responses are
reserved for authentication, malformed input, configuration and technical
failures; the NovaOrders adapter treats each as unavailable and fails closed.

## Configuration

Required:

- REDIS_URL — private TLS Redis connection string; never returned by an API.
- ABUSE_GUARD_TOKEN — caller authentication secret.
- ABUSE_GUARD_HASH_SECRET — separate keyed-hash secret for limiter keys.

Bounded defaults, each overridable only by positive integers:

- ABUSE_EMAIL_WINDOW_SECONDS=60, ABUSE_EMAIL_MAX=1.
- ABUSE_IP_WINDOW_SECONDS=900, ABUSE_IP_MAX=5.
- ABUSE_PAIR_WINDOW_SECONDS=3600, ABUSE_PAIR_MAX=3.
- PORT is supplied by Railway.

The service rejects startup or readiness when required configuration is
missing, blank, malformed or outside safe bounds. It never falls back to an
in-memory limiter.

## Redis limiter algorithm

1. Trim and lowercase the email; reject empty or malformed input.
2. Build keyed hashes for email, IP when present, and email+IP using
   ABUSE_GUARD_HASH_SECRET.
3. Atomically increment each applicable bucket and set its TTL on first use.
4. Allow only when all applicable counters are within their limits.
5. Return a fresh opaque decision ID; never return the hashed keys or counts.

The increment/limit/TTL operation must be atomic across replicas (Redis Lua or
an equivalent atomic primitive). A Redis timeout or partial result is a
technical failure, not an allow.

## Security and privacy

The endpoint compares the Bearer token without timing-sensitive leakage and
does not echo credentials. Logs contain event names, categories and bounded
latency only. Redis keys are keyed hashes and expire; the service must not log
request bodies, raw email, raw IP, Authorization headers or Redis URLs.

The service does not call Supabase, query users, inspect authentication state,
or know whether an email exists. A rate decision is independent of identity
existence, preserving the Phase 2 anti-enumeration boundary.

## Failure behavior

| Condition | Guard result | NovaOrders result |
| --- | --- | --- |
| Valid request below limits | 200 allowed=true + decision_id | Calls Supabase OTP |
| Valid request over any limit | 200 allowed=false + decision_id | No OTP/cookie; bounded 503 |
| Missing/wrong token | 401/403 bounded response | No OTP/cookie; bounded 503 |
| Invalid request body | 400 bounded response | No OTP/cookie; bounded 503 |
| Missing config | Unready/503 | No OTP/cookie; bounded 503 |
| Redis unavailable/malformed | 503 bounded response | No OTP/cookie; bounded 503 |

No retry in the web request may turn an unavailable or uncertain guard into an
allow. The guard may retry Redis only if the implementation can prove the
operation was not partially applied; the default is one bounded attempt.

## Health and readiness

GET /health returns a bounded liveness response. GET /ready verifies that
required configuration is loaded and Redis can execute a safe connectivity
check. Neither endpoint returns the Redis URL, token, key material or counters.
Railway may use /ready for deployment health; a not-ready guard causes the
NovaOrders caller to fail closed.

## Observability

Use bounded counters/events:

- guard_allowed
- guard_denied_rate
- guard_auth_rejected
- guard_invalid_request
- guard_redis_unavailable
- guard_not_ready

Record latency and environment-safe reason categories. Do not add raw email/IP
labels to metrics because that would create high-cardinality personal data.

## Testing strategy

The service tests inject a fake Redis protocol or deterministic test double;
they never require a live Redis, Railway, Supabase or email provider. Tests
must assert exact response shape/status, token handling, hash-only keys, TTL
behavior, atomic decision semantics and fail-closed technical errors.

## Operational separation

The implementation may live in the same Git repository but must have its own
Dockerfile, dependency set, entrypoint and Railway service configuration
instructions. It must not import the NovaOrders application or share its
database. Creating the Railway service, Redis instance, public domain,
variables, secrets, deploy or DNS records remains outside this code change.
