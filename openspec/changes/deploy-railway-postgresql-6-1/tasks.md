## 1. Deployment design and repository configuration

- [x] 1.1 Inspect Railway's current deployment conventions and the existing
  application start/migration paths; select the smallest supported manifest
  or service configuration.
- [x] 1.2 Add the minimal build, release-migration, start, and health-check
  configuration without embedding any secret or connection URL.
- [x] 1.3 Add a concise operator runbook with Railway PostgreSQL reference
  variables, migration/release ordering, Twilio URL setup, and rollback.

## 2. Production-safety boundary

- [x] 2.1 Ensure deployment configuration cannot serve with the local/test
  database fallback.
- [x] 2.2 Add only any necessary bounded readiness check or startup validation
  discovered during implementation; preserve all existing route contracts.
- [x] 2.3 Document the explicit business-readiness gate for a Railway-reachable
  generative LLM and embedding endpoints; assess the supplied Ollama
  `qwen-27b-coding:latest` and `all-minilm:latest` candidates through their
  respective existing contracts.
- [x] 2.4 Normalize Railway's bare PostgreSQL URL at the shared application /
  Alembic configuration boundary so the installed `psycopg` v3 driver is used;
  preserve explicit SQLAlchemy dialect URLs.

## 3. Railway provisioning and controlled verification

- [ ] 3.1 With user-provided Railway access and secret values, create/configure
  the Railway PostgreSQL and web services using reference variables.
- [ ] 3.2 Apply the existing Alembic revisions through the release command and
  verify the recorded revision against the Railway database.
- [ ] 3.3 Verify the public health endpoint, configure Twilio's inbound and
  status-callback URLs, and perform a non-destructive signed webhook check.
- [ ] 3.4 From the deployed Railway service, run a bounded safe probe of the
  supplied Ollama candidate (`100.113.65.40`): verify the existing generative
  contract with `qwen-27b-coding:latest` and the embedding contract/dimension
  with `all-minilm:latest`, without logging text, vectors, or generated
  content. If either is unreachable, do not introduce a proxy, tunnel, or
  model substitution; record the business-readiness gate as unresolved and
  keep the production WhatsApp number disabled.

## 4. Focused validation

- [ ] 4.1 Run focused configuration/health tests, Ruff, and `compileall` on
  touched files locally; retain the complete output.
- [ ] 4.2 Run strict OpenSpec validation and `git diff --check` locally.
- [ ] 4.3 Record safe Railway verification evidence and distinguish completed
  infrastructure readiness from any blocked business-readiness gate.
