# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect the Railway manifest, Docker image, entrypoint, Alembic
  configuration, relevant archived deployment specification, Railway service
  manifest/history, and the verified production incident.
- [x] 1.2 Define the one-authority entrypoint gate, fail-closed outcomes,
  transaction boundary, observability, rollback, non-goals, and focused
  validation.
- [x] 1.3 Obtain explicit approval of this proposal before implementation.

## 2. Implementation (after approval)

- [x] 2.1 Remove the independent Railway `preDeployCommand` migration path.
- [x] 2.2 Add the safe Alembic lifecycle gate to `docker-entrypoint.sh` after
  production database validation and before Tailscale/Uvicorn.
- [x] 2.3 Update the focused manifest/entrypoint tests to prove the ordering,
  fail-closed behavior, and unchanged worker supervision boundary.
- [x] 2.4 Update the Railway runbook with the new authoritative migration
  evidence and rollback constraint.
- [x] 2.5 Review scope, privacy, transaction ownership, and deployment
  boundary against this approved change.

## 3. Validation and controlled production check

- [x] 3.1 User runs the focused pytest, Ruff, compileall, shell syntax,
  strict OpenSpec validation, and diff check commands from the proposal and
  provides complete output.
- [x] 3.2 After separate authorization, deploy the approved change to Railway
  production and verify safe migration lifecycle records, `alembic current`,
  and `/health` in that order.
- [x] 3.3 Review production evidence and rollback readiness; obtain separate
  authorization before sync/archive.
