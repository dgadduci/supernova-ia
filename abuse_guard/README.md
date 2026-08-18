# abuse_guard

Standalone FastAPI service that authorizes magic-link issuance for
NovaOrders onboarding by consulting a private Redis-backed rate
limiter. It is deployed as a separate Railway service and has no
dependency on the NovaOrders backend, models or database.

The service implements the contract expected by the Phase 2
`backend.auth.abuse_guard.request_magic_link_authorization` adapter
and is intended to be the authoritative anti-abuse boundary for the
magic-link request.

## Required environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `REDIS_URL` | yes | Private TLS Redis connection string. Never returned by any API. |
| `ABUSE_GUARD_TOKEN` | yes | Bearer token presented by the NovaOrders caller. |
| `ABUSE_GUARD_HASH_SECRET` | yes | Separate HMAC secret used to derive limiter keys. |
| `PORT` | no | HTTP port (defaults to `8000`). Railway supplies this value. |

## Optional bounded configuration

All values are positive bounded integers. The service refuses to
start when any value is missing, blank, non-integer or outside the
allowed range.

| Variable | Default | Description |
| --- | --- | --- |
| `ABUSE_EMAIL_WINDOW_SECONDS` | `60` | Email window length in seconds (1..86400). |
| `ABUSE_EMAIL_MAX` | `1` | Maximum requests per email window (1..1000). |
| `ABUSE_IP_WINDOW_SECONDS` | `900` | IP window length in seconds (1..86400). |
| `ABUSE_IP_MAX` | `5` | Maximum requests per IP window (1..1000). |
| `ABUSE_PAIR_WINDOW_SECONDS` | `3600` | Email+IP window length in seconds (1..86400). |
| `ABUSE_PAIR_MAX` | `3` | Maximum requests per email+IP window (1..1000). |

## HTTP contract

### POST /check

Request:

```http
POST /check
Authorization: Bearer <ABUSE_GUARD_TOKEN>
Content-Type: application/json
Accept: application/json
```

```json
{
  "email": "owner@example.com",
  "action": "magic_link",
  "remote_ip": "203.0.113.10"
}
```

`remote_ip` is optional; `email` and `action` are required. The only
accepted `action` is `magic_link`. `email` is trimmed and lowercased.

Response (allow or deny):

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "allowed": true,
  "decision_id": "opaque-random-id"
}
```

`allowed=false` is an authoritative rate decision. The NovaOrders
adapter renders the bounded 503 view and does not call Supabase OTP.

Failure responses never include Redis URLs, credentials, identifiers
or internal counters.

| Condition | Status |
| --- | --- |
| Valid request below limits | 200, allowed=true |
| Valid request over any limit | 200, allowed=false |
| Missing/incorrect Bearer token | 401 |
| Body invalid, email invalid, action != magic_link | 400 |
| Missing/invalid configuration or Redis unavailable | 503 |

### GET /health

Returns a bounded liveness response. Returns 200 while the process is
running and serves `/check`.

### GET /ready

Returns 200 only when required configuration is loaded and Redis
responds to a safe connectivity check. Returns 503 otherwise. The
response never includes the Redis URL, credentials, counters or
identifiers.

## Local execution

The service is started through `python -m abuse_guard`, which loads
the fail-closed configuration from the environment, builds a real
Redis client and serves the FastAPI app on `0.0.0.0:${PORT}`. The
module-level `abuse_guard.app:app` instance is intentionally kept
unwired (Redis client absent) so a careless `uvicorn` invocation
cannot start the service in a permissive state.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r abuse_guard/requirements.txt
PYTHONPATH=abuse_guard \
  REDIS_URL=redis://localhost:6379/0 \
  ABUSE_GUARD_TOKEN=dev-token \
  ABUSE_GUARD_HASH_SECRET=dev-hash-secret \
  PORT=8000 \
  python -m abuse_guard
```

## Docker

The Dockerfile builds and runs only the `abuse_guard` service. It
does not depend on the NovaOrders root Dockerfile. The container
entrypoint is `python -m abuse_guard`, which wires the configuration
and the Redis client before opening the HTTP port.

```bash
docker build -f abuse_guard/Dockerfile -t abuse_guard .
docker run --rm -p 8000:8000 \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  -e ABUSE_GUARD_TOKEN=dev-token \
  -e ABUSE_GUARD_HASH_SECRET=dev-hash-secret \
  -e PORT=8000 \
  abuse_guard
```

## Railway deployment

Deploy as a second Railway service in the same project. The service
must run with its own public HTTPS domain dedicated to the guard
endpoint. Redis must be a private service or a managed provider inside
the same network; the public URL is never exposed.

Suggested environment variables (no real values are committed):

- `REDIS_URL` — private Redis connection string.
- `ABUSE_GUARD_TOKEN` — opaque caller token. Rotate independently of
  the application.
- `ABUSE_GUARD_HASH_SECRET` — separate HMAC secret. Rotate
  independently of the token.
- `ABUSE_EMAIL_WINDOW_SECONDS`, `ABUSE_EMAIL_MAX`,
  `ABUSE_IP_WINDOW_SECONDS`, `ABUSE_IP_MAX`,
  `ABUSE_PAIR_WINDOW_SECONDS`, `ABUSE_PAIR_MAX` — leave at defaults
  until operational review.
- `PORT` — supplied by Railway.

Configure NovaOrders to point at the deployed service through the
existing `SUPABASE_ABUSE_GUARD_URL` and `SUPABASE_ABUSE_GUARD_TOKEN`
variables. Token rotation on the guard side must be mirrored in
NovaOrders. Configuring the service is the only production
side-effect; the guard never writes to NovaOrders or Supabase.

Production activation requires a separate operational approval
step; this repository only contains the service implementation. Do
not commit real secrets, Railway IDs, DNS values or domains.

## Privacy and failure model

- The guard never logs raw email, IP, Authorization headers, Redis
  URLs, tokens, request bodies or decision identifiers.
- Decisions are returned only as `allowed` and `decision_id`. The
  `decision_id` is an opaque random identifier and is not derived
  from the email, IP or their hashes.
- The guard fails closed on every technical error: missing
  configuration, missing token, malformed body, invalid action,
  invalid email, Redis timeout, connection failure or malformed
  command response. There is no in-memory permissive fallback.

## Tests

```bash
PYTHONPATH=abuse_guard venv/bin/python -m pytest abuse_guard/tests -q
```

Tests use an in-process fake Redis transport and never contact a
real Redis, Railway, Supabase or email provider.
