## Why

The deployed Railway PostgreSQL database has the schema but no operational
fixture data: the read-only commerce and commerce-status endpoints return
empty lists. The controlled WhatsApp pilot cannot resolve an active commerce
in that state. The new target data must be generated from versioned static
fixture definitions, not copied from or mixed with the developer database.

## Objective

Provide one controlled, deterministic fixture catalog for an empty
production-shaped database. It creates three human-recognizable active
commerce fixtures and the minimum catalog data needed to exercise ordering,
recognition, dedicated WhatsApp routing, and future shared-routing work.

## Current execution path

The current bring-up entry point, `backend.db.seeds.setup_all`, runs legacy
JSON seed scripts in dependency order. It does not model WhatsApp channels,
prints its database target, and is not an appropriate Railway operator
surface. The active pilot's
`backend.cli.provision_whatsapp_pilot_routing` separately verifies or creates
one active dedicated Twilio channel using the configured sender after an
active commerce already exists.

## Scope

- Add one internal fixture CLI, read-only by default and explicit on apply.
- Create exactly three active, synthetic commerce fixtures with stable slugs
  and labels: `Piloto WhatsApp Dedicado`, `Piloto WhatsApp Compartido Uno`,
  and `Piloto WhatsApp Compartido Dos`.
- Create for each commerce four categories, seven presentations, thirty
  deterministic products, their valid product-presentation associations, and
  one price per association.
- Provide only the minimum common reference data the fixtures require,
  including the `ACTIVO` commerce state.
- Reuse the existing dedicated-routing provisioning CLI after the fixture
  seeder reports ready; it remains the only authority that may bind the
  current real Twilio sender to the dedicated fixture commerce.

## Non-goals

- No PostgreSQL dump/restore, manual SQL, direct Railway table editing, or
  import of the local development database.
- No read, export, cleanup, reset, or mutation of any local development
  database. The local database is neither an input nor an execution target.
- No migrations, FastAPI administration endpoint, CI/CD automation,
  scheduler, worker, recognizer-policy change, or modification of the active
  WhatsApp pilot change.
- No real customer data, real client data, orders, sessions, messages,
  credentials, E.164 values, Twilio signatures, or database URLs in fixture
  data or command output.
- No active shared WhatsApp channel, shared membership, routing code, or
  placeholder destination. Those require a second real provider number and
  are explicitly deferred.

## Shared boundary, outcomes, and fallback

| Condition | Authoritative outcome | Fallback |
| --- | --- | --- |
| Empty compatible fixture tables and explicit apply | All fixtures are staged and committed once | `provisioned` |
| Exact complete fixture set already exists | No mutation | `ready` |
| Empty schema has not yet received fixtures | No mutation | `not_ready` |
| Any pre-existing fixture-domain data is incomplete, malformed, or non-fixture | No mutation | `conflict`; stop and diagnose separately |
| Missing schema/reference prerequisite or technical failure | Roll back the whole apply transaction | Typed technical failure; no partial fixture set |

The fixture command must not infer, change, or delete arbitrary existing
business data. It is a controlled empty-target bring-up surface, not a general
data repair tool. Before its first apply it requires every table it owns
(commerce states, commerces, categories, presentations, products,
product-presentations, and prices) to be empty. It may only operate against
the configured runtime target; static source definitions are packaged in the
application and it never reads a source database.

## Transaction ownership and observability

The CLI owns one transaction. Its helpers may stage ORM state but must not
commit, roll back, begin, or flush. The CLI may flush once for its final
read-back verification, then commits once on success or rolls back on every
failure. Output contains mode, status, aggregate counts, stable fixture slugs
and numeric IDs only. It must never print a database URL, a phone number,
message content, credential, secret, or raw exception text.

## Expected files

- `backend/cli/seed_controlled_railway_fixtures.py`
- One focused fixture service and/or static fixture-data module under
  `backend/services/` or `backend/db/seeds/`, reusing existing repositories
  where their contracts fit.
- Focused tests under `backend/tests/`.
- This OpenSpec change: proposal, design, capability delta, and tasks.

## Focused tests and validation

Tests must cover default read-only verification, first apply, exact rerun,
all-or-nothing rollback, stable-identity conflict, catalog counts and
associations, price coverage, no active shared-channel data, and sanitized
output. The user runs focused pytest, Ruff, compileall, strict OpenSpec
validation, and `git diff --check` in their local terminal; no validation is
accepted without complete reported output.

## Rollback and deferred limitations

The command never deletes fixtures. On a disposable empty Railway database,
rollback is an approved environment/database replacement or restore decision,
not a destructive CLI option. Shared channel provisioning begins only after a
second real provider number is available and is proposed in its own scoped
change.
