# railway-postgresql-deployment Specification

## Purpose
TBD - created by archiving change deploy-railway-postgresql-6-1. Update Purpose after archive.
## Requirements
### Requirement: Reproducible Railway web and PostgreSQL deployment

The system SHALL provide repository-managed deployment instructions and the
minimum Railway configuration necessary to build the existing FastAPI service,
run the current Alembic migration chain through the Railway web-service
entrypoint before that process starts Tailscale or Uvicorn, start the web
service on Railway's assigned port, and connect it to Railway PostgreSQL via
`SUPERNOVA_DATABASE_URL`. No secret value or PostgreSQL connection URL SHALL
be committed to the repository. `railway.toml` SHALL NOT declare an independent
pre-deploy migration command.

#### Scenario: Web process reaches the current database revision before traffic

- **WHEN** Railway starts a web-service image with a valid referenced
  PostgreSQL URL
- **THEN** its entrypoint runs the existing Alembic chain through that image's
  `head` before starting Tailscale or the FastAPI web process
- **AND** only a successful migration permits the web process to serve traffic

#### Scenario: Release reaches the current database revision

- **WHEN** Railway deploys a release with a valid referenced PostgreSQL URL
- **THEN** the web-service entrypoint upgrades the database through the
  existing Alembic chain before the new web process serves traffic
- **AND** the web process starts the existing FastAPI application using
  Railway's assigned port

#### Scenario: Migration failure fails closed

- **WHEN** the referenced database URL is absent or the Alembic upgrade fails
- **THEN** the entrypoint exits non-zero before Tailscale or Uvicorn starts
- **AND** the service SHALL NOT serve traffic, select the local
  `supernova_test` fallback, or silently skip/retry the migration in-process

#### Scenario: Missing database configuration fails closed

- **WHEN** the Railway deployment lacks a valid production database URL
- **THEN** it SHALL fail before serving production traffic
- **AND** it SHALL NOT select the local `supernova_test` fallback

#### Scenario: Restart against an already-current schema remains safe

- **WHEN** Railway restarts a web-service image whose database is already at
  its Alembic `head`
- **THEN** the entrypoint runs the same Alembic upgrade successfully before
  starting the web process
- **AND** it SHALL NOT use a separate pre-deploy, request, worker, or handler
  migration path

### Requirement: Explicit infrastructure and business readiness gates

The deployment runbook SHALL distinguish infrastructure readiness from
business-message readiness. Infrastructure readiness requires a successful
build/release, persistent database migration, and public health verification.
Business-message readiness additionally requires a Railway-reachable configured
generative LLM, the embedding endpoint for any exercised embedding-dependent
path, and a controlled signed Twilio verification. The supplied Ollama service
at `100.113.65.40` MAY be used after bounded deployed verification of both
existing contracts: `qwen-27b-coding:latest` for the generative LLM and
`all-minilm:latest` for embeddings with the configured dimension. The models
SHALL NOT be substituted for one another.

#### Scenario: Local defaults are unavailable to Railway business processing

- **WHEN** either supplied Ollama contract is required but cannot be
  reached/validated from Railway
- **THEN** the deployment SHALL NOT be approved for live business-message
  processing
- **AND** the system SHALL NOT silently substitute `localhost`, a proxy, or a
  different model

### Requirement: Existing provider and transaction contracts remain unchanged

Deployment configuration SHALL NOT alter the existing `/health`, Twilio
inbound, Twilio status-callback, outbox-dispatch, or transaction-ownership
contracts. The existing outbound dispatcher remains a bounded, explicit CLI
operation; this capability SHALL NOT introduce a scheduler, worker, or polling
loop.

#### Scenario: Deployment does not create another dispatch path

- **WHEN** the application is deployed to Railway
- **THEN** pending outbound messages remain dispatched only through the
  existing explicit dispatcher entry point
- **AND** no web request, release step, cron, or background process sends an
  outbound message implicitly
