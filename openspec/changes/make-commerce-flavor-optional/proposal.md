# Proposal: make commerce communication flavor optional

## Objective

Replace the persisted `neutro` sentinel assignment with an absent optional
flavor relation. A commerce with no assigned flavor SHALL use exact
deterministic outbound responses and make no styling LLM call. A commerce with
an assigned active flavor and a usable instruction retains the current bounded
styling behavior.

## Current Execution Path

`Comercio.flavor_comunicacion_id` is currently a non-null foreign key. The
commerce creation service resolves the global row whose code is `neutro` and
assigns it to every new commerce. The outbound styler resolves that relation
and treats the literal `neutro` code as an explicit no-op. Flavor assignment
uses `ComunicacionFlavorService.assign_to_comercio` and the authenticated
assignment endpoint accepts only a positive flavor identifier.

## Scope

- Make `Comercio.flavor_comunicacion_id` nullable through one reversible
  migration.
- Convert existing commerce assignments to the canonical `neutro` row into
  `NULL` during that migration. Other flavor assignments remain unchanged.
- Stop assigning `neutro` when creating a commerce.
- Remove the styler's special-case dependency on the literal `neutro` code;
  absent, inactive, or instruction-less flavors remain the safe no-op.
- Add a controlled way to clear a commerce flavor through the existing
  assignment boundary, without introducing flavor CRUD.
- Preserve the global flavor catalog and existing non-neutral assignments.

## Non-Goals

No flavor catalog deletion, renaming, editing API, prompt change, LLM client
change, response-builder change, intent change, outbox change, transaction
owner change, or style eligibility change is included. `neutro` may remain a
catalog row for compatibility, but it is no longer required as a default or
runtime sentinel.

## Authoritative Outcomes and Fallback

| Condition | Required outcome |
| --- | --- |
| Commerce has no flavor (`NULL`) | Exact deterministic output; no style LLM call |
| Commerce has an active flavor with instruction | Existing bounded styling path may run for eligible response types |
| Assigned flavor is missing, inactive, or has no instruction | Exact deterministic output; no style LLM call |
| Clear assignment request | Persist `NULL` and return the existing safe commerce flavor projection without a selected flavor |
| Assign unknown/inactive flavor | Existing bounded domain error; preserve prior assignment |
| Migration | Only canonical `neutro` assignments become `NULL`; all other assignments remain intact |

The absence of a flavor is normal configuration, not a styling failure. It
must not trigger retries, a second model call, recognition, or any business
mutation.

## Shared Boundary and Transactions

The existing commerce-flavor assignment service remains the sole mutation
boundary. The existing shared outbound styler continues to be the sole
presentation boundary for both local and provider paths. The migration owns
schema/data changes; application services retain their existing caller-owned
transaction semantics and must not introduce commit/rollback behavior beyond
their current contract.

## Observability

The existing closed styling diagnostic continues to report `not_attempted`
without flavor code for absent configuration. It must not expose database
identifiers, prior assignment, migration detail, or instruction text. No new
event family is required.

## Expected Files

- `backend/models/comercio.py`
- new Alembic migration under `backend/alembic/versions/`
- `backend/services/comercio_service.py`
- `backend/services/comunicacion_flavor_service.py`
- `backend/repositories/comercio_repository.py` only if its existing setter
  cannot express `None` clearly
- `backend/schemas/comunicacion_flavor.py`
- `backend/routers/flavors_comunicacion.py`
- `backend/services/outbound_response_styler.py`
- focused flavor model/service/router/styler tests
- this change's OpenSpec files

## Focused Tests

- Migration changes only `neutro` assignments to `NULL`, preserves other
  flavor IDs, and makes the foreign key nullable while retaining referential
  integrity.
- New commerce persists with no flavor and does not require the `neutro` row.
- Clear and assign operations use the existing service/endpoint boundary;
  unknown/inactive assignment rejection remains unchanged.
- An absent flavor yields deterministic local and provider-equivalent output,
  no style call, and closed `not_attempted` diagnostic; a valid assigned flavor
  still styles approved response types.
- No service or styler transaction regression, and no instruction/identifier
  leak.

## Validation

The implementation plan must name the exact focused test files after source
inspection. It must run focused pytest, Ruff on touched files, compileall on
touched Python files, strict OpenSpec validation, migration upgrade/downgrade
checks against the project test database where available, and `git diff --check`.
The user runs any `venv`-dependent commands locally and provides complete
output for review.

## Rollback and Deferred Limitations

Rollback restores the non-null requirement only after safely mapping `NULL`
rows to a known active fallback flavor; that mapping must be explicitly
defined in the migration downgrade. No automatic flavor selection, per-intent
flavor selection, flavor CRUD, or administrator UI is introduced.
