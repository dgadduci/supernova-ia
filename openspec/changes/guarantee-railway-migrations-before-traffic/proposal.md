# Guarantee Railway migrations before traffic

## Objective

Make the deployed web process fail closed unless the Alembic chain of its own
image has reached `head` before Uvicorn can accept Railway traffic. This
replaces the unproven release-step guarantee that allowed production to serve
the draft-order observation code while PostgreSQL was still at revision
`7c4d5e6f7a8b`.

## Verified current execution path

Railway builds the repository Dockerfile, applies `railway.toml`, then starts
`./docker-entrypoint.sh`. The manifest currently also declares the independent
pre-deploy command `test -n "$SUPERNOVA_DATABASE_URL" && python -m alembic
upgrade head`. Railway's recorded production deployment loaded that command,
yet the deployment containing the observation migration served with
`pedidos.observaciones` absent until an operator ran `python -m alembic upgrade
head` manually in Railway.

The entrypoint validates `SUPERNOVA_DATABASE_URL`, starts userspace Tailscale,
waits for it, then backgrounds Uvicorn. It has no Alembic gate. Alembic itself
uses `SUPERNOVA_DATABASE_URL`, normalized by the shared database URL boundary,
and its transactions are owned by Alembic rather than request handlers.

## Scope

- Make the existing Railway entrypoint run the existing Alembic upgrade before
  Tailscale or Uvicorn starts.
- Make that entrypoint gate the sole repository-managed migration authority by
  removing the separate `preDeployCommand`.
- Fail startup non-zero, with safe lifecycle logging, if the database URL is
  missing or the upgrade fails.
- Document the revised deployment verification: deployment log evidence,
  `alembic current`, and public `/health` after the successful migration gate.
- Add focused entrypoint/configuration tests proving the ordering and
  fail-closed boundary.

## Non-goals

- No Alembic revision, model, schema, data backfill, downgrade, or change to
  the already-applied observation migration.
- No request-startup migration hook, handler/repository migration, second
  migration pipeline, worker/scheduler, Railway service, health endpoint, or
  provider/message-flow change.
- No change to Tailscale, worker supervision, Twilio, recognition, order
  behavior, local development defaults, or caller-owned business transactions.

## Shared boundary, fallback, and transaction ownership

The entrypoint is the shared deployment boundary. Its authoritative outcomes
are:

| Condition | Required outcome | Must not happen |
| --- | --- | --- |
| Valid URL and Alembic reaches image `head` | Continue startup; only then start Tailscale and Uvicorn | Serve traffic first |
| Missing URL | Exit non-zero before any child process | Select `supernova_test` or start Uvicorn |
| Alembic technical failure | Exit non-zero before any child process; Railway retains the prior healthy deployment | Continue, retry inside the process, or silently skip |
| Restart with schema already at `head` | Alembic's existing idempotent upgrade completes, then startup continues | Create a parallel release path |

There is no business fallback: Fuzzy and recognition fallback contracts are
irrelevant. Alembic owns its migration transaction; the entrypoint neither
opens nor commits a request/business transaction. Existing request,
coordinator, dispatcher and recognizer transaction ownership remains unchanged.

## Observability

The gate emits only lifecycle events sufficient to establish ordering and
failure category: `migration=starting`, `migration=completed`, or
`startup_error migration_failed`. It MUST NOT print the database URL,
credentials, Alembic SQL, customer/order data, environment dumps, or raw
exception payloads. Railway deployment status plus `python -m alembic current`
remain the authoritative post-deploy proof of the database revision.

## Expected files and focused validation

- `railway.toml`
- `docker-entrypoint.sh`
- `backend/tests/test_railway_tailscale_entrypoint.py` and/or the existing
  focused entrypoint test module
- `backend/development/railway.md`
- this OpenSpec delta

The user runs these exact local commands and supplies the complete output:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_railway_tailscale_entrypoint.py backend/tests/test_provider_processing_worker.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/tests/test_railway_tailscale_entrypoint.py backend/tests/test_provider_processing_worker.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/tests/test_railway_tailscale_entrypoint.py backend/tests/test_provider_processing_worker.py
sh -n docker-entrypoint.sh
openspec validate guarantee-railway-migrations-before-traffic --strict
git diff --check
```

After an explicitly authorized production deploy, verify the safe lifecycle
records, run `python -m alembic current` in the Railway service, and check
public `GET /health` returns `200` only after that revision evidence.

## Rollback and deferred limitations

Rollback is a Railway rollback/redeploy to the preceding application release
only after evaluating schema compatibility. No automatic Alembic downgrade is
permitted. Reverting the entrypoint/manifest restores the previous deployment
mechanism but does not reverse a successfully applied database revision.

This change does not establish a multi-replica migration lock, compatibility
policy for destructive schema changes, CI deployment gates, platform log
retention, or an external explanation for Railway's historic pre-deploy
anomaly. Those remain deferred unless separately approved.
