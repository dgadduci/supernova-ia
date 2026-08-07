## Why

Phase 5 has completed the provider-facing WhatsApp path, but it runs only
against local infrastructure. The project needs one reproducible deployment
baseline before further order-domain capabilities are added: a public HTTPS
application, persistent PostgreSQL, controlled migrations, and an explicit
operational configuration boundary.

## Objective

Deploy the existing FastAPI application to Railway with Railway PostgreSQL,
using the current Alembic history and existing provider-facing routes, without
changing order, recognition, or messaging business behavior.

## Current execution path

`backend.main:app` registers the HTTP application and `/health` returns a
process-local success response. `backend.dependencies` already obtains its
engine from `SUPERNOVA_DATABASE_URL` (falling back to a local test database),
and `backend/alembic/env.py` already uses that same variable for migrations.
There is no Railway manifest or documented release/start lifecycle. Default
LLM and embedding URLs point to `localhost`, which a Railway service cannot
use. Ollama at `100.113.65.40` has both required candidate models:
`all-minilm:latest` for semantic embeddings and `qwen-27b-coding:latest` for
the generative LLM. Their reachability from Railway and compatibility with the
existing endpoints must be proven before live traffic is enabled.

## Scope

- Add the minimum repository deployment configuration and operator
  documentation required for Railway to build, migrate, start, and health
  check the existing application.
- Define a release migration command that receives only
  `SUPERNOVA_DATABASE_URL` from Railway; migrations run once per release and
  are never executed by request handlers or application startup.
- Define the production configuration inventory and safe validation for the
  existing database, Twilio, outbound-dispatch, LLM, and embedding settings,
  including the supplied Ollama embedding candidate.
- Provision/configure the Railway PostgreSQL service and application only
  after the user supplies the necessary Railway/Twilio/LLM values, then prove
  the deployed `/health` route, database revision, and the existing signed
  Twilio webhook path with a non-destructive test.
- Record an explicit hand-off for the outbound dispatcher: it remains the
  bounded manual CLI from 5.6; this subphase does not add a worker or
  scheduler.

## Non-goals

- No new order intents, recognizers, handlers, services, payment/delivery
  behavior, LLM message embellishment, or product-recognition changes.
- No local Ollama/model deployment to Railway, new LLM provider, model
  migration, vector re-indexing, background queue/worker, scheduler, CI/CD
  pipeline, custom domain, authentication, observability platform, or
  autoscaling.
- No migration that changes the business schema: only the already-approved
  Alembic revisions are applied to the new PostgreSQL database.

## Shared boundary, outcomes, and fallback

| Condition | Outcome | Fallback |
| --- | --- | --- |
| Valid Railway database URL and successful Alembic upgrade | App starts against the persistent database | none |
| Missing/invalid database configuration or failed migration | Release/start fails before serving traffic | do not fall back to local/test DB |
| Valid public HTTPS base URL plus Twilio credentials | Existing signed inbound/callback routes can be configured and verified | none |
| Supplied Ollama embedding service is reachable and validates at the configured dimension | It may be configured as `EMBEDDING_URL` with `all-minilm:latest` | none |
| Supplied Ollama service is unreachable, private-only, invalid, or incompatible | Deployment remains infrastructure-ready; embedding-dependent runtime is not approved | do not silently use `localhost`, a proxy, or another model |
| Supplied Ollama generative endpoint is reachable and responds through the existing LLM contract | It may be configured as `LLM_URL` with `qwen-27b-coding:latest` | none |
| Supplied Ollama generative service is unreachable, private-only, invalid, or incompatible | Deployment is not approved for real business-message processing | do not silently use `localhost`, a proxy, or another model |
| Twilio outbound work exists | Operator invokes the existing bounded dispatcher explicitly | no scheduler or replay path |

## Transaction ownership and observability

Railway configuration and release migrations introduce no request transaction
owner. Existing request/coordinator/dispatcher ownership remains unchanged.
Deployment verification may expose release id, deployment URL, `/health`
status, Alembic revision, and safe Twilio message IDs. It must not log or
commit database URLs, Twilio credentials/signatures, LLM credentials, raw
message bodies, or customer data.

## Expected files

- Railway build/start/release configuration at the repository root
- deployment/runbook documentation under `backend/development/` or a focused
  deployment document
- only the smallest settings/startup/health changes discovered as necessary
- focused tests for any new configuration or health/readiness behavior
- this change's OpenSpec artifacts and spec delta

## Validation and rollback

Validation includes a clean Railway build/release, `alembic current` against
the Railway database, public `/health`, and a signed non-destructive Twilio
webhook verification once credentials are available. Locally, run only
focused configuration/health tests, Ruff, `compileall`, strict OpenSpec
validation, and `git diff --check` through the user's local terminal.

Rollback is Railway rollback to the prior release or service disablement;
database downgrade is not automatic. Before any downgrade, inspect whether
the persistent database contains production data and use an explicitly
approved Alembic plan. Local development remains unaffected.

## Deferred limitations

The supplied Ollama endpoint is the candidate for both semantic embeddings and
the existing generative LLM contract. Full real-message operation remains
blocked until Railway can reach it securely and bounded embedding and
generative probes pass. Automatic outbound dispatch, CI/CD, production
monitoring, custom domains, secret rotation, and the next order-domain
functionality phase are deferred.
