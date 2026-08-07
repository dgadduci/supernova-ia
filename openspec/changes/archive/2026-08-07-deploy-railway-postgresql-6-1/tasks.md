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

- [x] 3.1 With user-provided Railway access and secret values, create/configure
  the Railway PostgreSQL and web services using reference variables. Completed
  with the deployed, healthy integrated Railway web service and PostgreSQL
  reference-variable topology evidenced by the archived 6.2 change
  (`2026-08-07-connect-railway-private-ollama-6-2`).
- [x] 3.2 Apply the existing Alembic revisions through the release command and
  verify the recorded revision against the Railway database. Railway shell
  evidence: `python -m alembic current` reported `a1b2c3d4e5f6 (head)`.
- [x] 3.3 Verify the public health endpoint, configure Twilio's inbound and
  status-callback URLs, and perform a non-destructive signed webhook check.
  The public Railway base and matching inbound/status-callback URLs were
  configured; the signed inbound check received a successful response after
  the matching `TWILIO_AUTH_TOKEN` was configured, with no Twilio Error 11200.
- [x] 3.4 Superseded explicitly by the approved 6.2 change
  (`connect-railway-private-ollama-6-2`), which replaced the original
  no-proxy restriction with a colocated, loopback-only Tailscale SOCKS5
  boundary. Its deployed integrated probes passed for
  `qwen-27b-coding:latest` and `all-minilm:latest` at dimension `384`, without
  recording prompt, response, or vector content. This is a documented scope
  replacement, not a silent completion of the original no-proxy task.

## 4. Focused validation

- [x] 4.1 Run focused configuration/health tests, Ruff, and `compileall` on
  touched files locally; retain the complete output. User-local results:
  `backend/tests/test_database_url.py` — 3 passed; Ruff — all checks passed;
  `compileall` — completed without error.
- [x] 4.2 Run strict OpenSpec validation and `git diff --check` locally.
  `openspec validate deploy-railway-postgresql-6-1 --strict` reported the
  change valid; `git diff --check` completed without output.
- [x] 4.3 Record safe Railway verification evidence and distinguish completed
  infrastructure readiness from any blocked business-readiness gate.
  Infrastructure readiness is evidenced by the deployed Railway service,
  PostgreSQL revision `a1b2c3d4e5f6 (head)`, and public health previously
  verified by 6.2. Business readiness is evidenced by 6.2's passed integrated
  private-Ollama probes and this change's successful signed Twilio inbound
  check; no credentials, signatures, message bodies, or vectors were recorded.
