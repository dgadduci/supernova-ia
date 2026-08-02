## Context

Follows the project's existing patterns: code lives under purpose-specific subdirectories (`backend/db/seeds/seeds/` for scripts, `backend/db/seeds/data/` for JSON payloads). DB selection reuses the `SUPERNOVA_DATABASE_URL` convention introduced in Subphase 1.11, defaulting to `supernova_test` so the test-first-then-prod discipline from `openspec/specs/project.md` is preserved.

## Decisions

- **D1 — One script, one DB at a time.** Selection via `SUPERNOVA_DATABASE_URL`, default `supernova_test`. Matches Alembic and avoids hidden cross-DB writes.
- **D2 — Idempotent on `estado` value.** Re-runs skip rows whose value already exists, so the script can be invoked safely against an already-seeded DB.
- **D3 — JSON data file.** Source of truth lives next to the script under `backend/db/seeds/data/estados.json`. The script does not embed the data; future edits to the JSON take effect on the next run.

## Risks / Trade-offs

- **[Risk] Running against the wrong DB.** → Mitigation: the script prints `target=...` to stdout; the operator can sanity-check before committing.
- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
