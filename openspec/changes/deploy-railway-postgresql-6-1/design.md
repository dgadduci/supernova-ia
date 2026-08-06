## Decision

Subphase 6.1 establishes one Railway deployment topology: one FastAPI web
service connected to one Railway PostgreSQL service. The web service starts
the existing `backend.main:app` through Uvicorn and uses Railway's assigned
port. A release command upgrades the configured database with the existing
Alembic chain before the new web release receives traffic.

`SUPERNOVA_DATABASE_URL` is the sole database configuration input for both
the application and Alembic. In the deployed environment it is mandatory;
the local fallback in `backend.dependencies` must never become a production
fallback. The implementation shall prefer Railway's reference-variable
mechanism over copying a connection string into repository files.

The existing `/health` endpoint remains a liveness endpoint. If a database
readiness check is necessary for Railway health verification, it shall be a
separate minimal endpoint or documented release check, must issue only a
bounded connectivity query, and must not expose configuration or data.

## External configuration contract

Railway stores all values as service variables. Repository files contain names
and instructions only; no secret values or PostgreSQL connection URLs are
committed. The user-supplied non-secret Ollama endpoint is documented only to
define the approved deployment target and is never written to application logs.

| Purpose | Existing variable | Production rule |
| --- | --- | --- |
| PostgreSQL | `SUPERNOVA_DATABASE_URL` | Railway PostgreSQL reference; mandatory |
| Twilio request validation | `TWILIO_AUTH_TOKEN`, `TWILIO_WEBHOOK_BASE_URL` | mandatory before enabling webhooks; base URL is public HTTPS |
| Twilio outbound CLI | `TWILIO_ACCOUNT_SID`, `TWILIO_OUTBOUND_SENDER_E164`, `TWILIO_CALLBACK_STATUS_URL` and existing retry settings | required only before an explicit dispatch pass |
| Business LLM | `LLM_URL`, `LLM_MODEL` and existing LLM settings | candidate: Ollama `http://100.113.65.40:11434/api/generate`, model `qwen-27b-coding:latest`; use only after Railway reachability and existing-contract response verification; never default to `localhost` |
| Embeddings | `EMBEDDING_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` | candidate: Ollama `http://100.113.65.40:11434/api/embed`, model `all-minilm:latest`, dimension `384`; use only after Railway reachability and response/dimension verification; never default to `localhost` |

The deployment runbook distinguishes infrastructure readiness from business
readiness. Infrastructure readiness needs build, migration, persistent DB and
public health. Business readiness additionally needs a reachable generative
LLM, the embedding configuration when an exercised path needs it, and a
controlled end-to-end Twilio verification. The supplied Ollama instance has
`qwen-27b-coding:latest` for `LLM_URL` and `all-minilm:latest` for embeddings.
Its `100.113.65.40` address is not presumed reachable from Railway, so bounded
deployed probes of both existing Ollama contracts are required. Until every
applicable gate is true, no production WhatsApp number is pointed at the
service.

## Invariants

- A web process never runs migrations on startup or on a request.
- No release may serve against the local `supernova_test` fallback.
- The supplied Ollama endpoint is configured only through Railway variables;
  a failed probe cannot fall back to `localhost`, a proxy, or a different
  embedding model.
- `all-minilm:latest` SHALL be used only as the embedding model and
  `qwen-27b-coding:latest` only as the generative LLM model; neither may be
  silently substituted.
- Existing Alembic history is the only schema authority; this subphase creates
  no business-schema revision.
- `/health`, webhook, callback and dispatcher behavior retain their existing
  contracts.
- Deployment manifests and logs contain no credentials, raw message bodies,
  signed form payloads, or database connection strings.
- The bounded manual outbox CLI remains manual; no Railway cron, worker, or
  polling loop is introduced.

## Focused tests

1. Deployment configuration starts Uvicorn with Railway's port and has a
   separate release migration command.
2. Production configuration fails safely rather than selecting the local/test
   database when the Railway database input is absent or invalid.
3. The supplied Ollama candidate is tested only through a bounded deployed
   embedding probe and a bounded generative probe; their configured models and
   contracts/dimension are verified without logging input text, vectors, or
   generated content.
4. Any new readiness behavior is bounded, database-only, and leaks no
   configuration/data.
5. Existing `/health` behavior remains compatible.
6. Static checks prove no deployment file contains a credential or connection
   string and no new migration/schema change was introduced.

## Validation

The implementer runs the focused local checks in the local terminal, then the
operator verifies Railway build/release logs, the public health URL, the
Alembic revision, and—in a controlled environment—the signed Twilio webhook
and callback URLs. The latter requires user-provided external credentials and
the supplied generative and embedding endpoints; it cannot be claimed from
local tests alone.
