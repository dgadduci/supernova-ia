# railway-postgresql-deployment Specification Delta

## MODIFIED Requirements

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

#### Scenario: Migration failure fails closed

- **WHEN** the referenced database URL is absent or the Alembic upgrade fails
- **THEN** the entrypoint exits non-zero before Tailscale or Uvicorn starts
- **AND** the service SHALL NOT serve traffic, select the local
  `supernova_test` fallback, or silently skip/retry the migration in-process

#### Scenario: Restart against an already-current schema remains safe

- **WHEN** Railway restarts a web-service image whose database is already at
  its Alembic `head`
- **THEN** the entrypoint runs the same Alembic upgrade successfully before
  starting the web process
- **AND** it SHALL NOT use a separate pre-deploy, request, worker, or handler
  migration path
