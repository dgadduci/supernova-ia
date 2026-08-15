# Proposal: add global communication flavors and commerce selection

## Why

NovaOrders currently renders deterministic customer messages with no
per-commerce communication style. The later response-embellishment phase needs
a durable, audited and bounded style selection, but a commerce must not be
allowed to supply arbitrary prompt text.

This change establishes a global system-owned catalog of communication flavors
and makes every commerce select one. It deliberately does not call an LLM or
change any customer-visible response yet.

## What Changes

- Add a global `FlavorComunicacion` catalog with a stable unique code, visible
  name, administrator-facing description, backend-controlled LLM instruction,
  active flag, version and timestamps.
- Seed the initial global profiles: `neutro`, `serio`, `joven`, `elegante`,
  `mexicano` and `peruano`. Their `instruccion_llm` values are controlled
  backend data, not commerce input.
- Add a required `Comercio.flavor_comunicacion_id` foreign key. Existing and
  newly-created commerces default to the active `neutro` profile.
- Expose read-only active flavors to authenticated administrators and expose a
  focused authenticated operation that changes one commerce's selection only
  to an active global flavor.
- Include selected flavor metadata in existing commerce/configuration read
  responses without exposing `instruccion_llm`.

## Current execution path

`Comercio` currently owns locale-like configuration (`idioma`, `moneda` and
`zona_horaria`) and `ConfiguracionComercioService` reads it through
`ConfiguracionComercioRepository`. The authenticated configuration endpoint is
read-only. Customer responses are built by deterministic intent response
builders and `build_customer_responses`; no style model exists and no LLM
formats outbound responses.

## Scope

- Global flavor catalog, migration, initial system seed data, commerce FK and
  ORM relationships.
- Read-only administrator list of active flavors, selected-flavor read model,
  and a narrow commerce flavor-selection write operation.
- Validation that a selected flavor exists and is active; invalid/inactive IDs
  fail without changing the commerce.
- Backfill/default handling for existing commerces and new-commerce creation.

## Non-goals

- No LLM response embellishment, outbound prompt, response rewriting, retry,
  fallback policy, cost/latency telemetry or provider/Twilio change.
- No flavor CRUD endpoint and no commerce-provided `descripcion` or
  `instruccion_llm` text. Global flavors remain system-managed seed data in
  this phase.
- No change to intent classification, product recognition, pending context,
  pedido/line mutations, response facts or customer-visible wording.
- No admin-panel UI work unless an existing configuration surface requires a
  minimal compatible representation; API/model behavior is authoritative.

## Shared boundary

`FlavorComunicacion` owns the global controlled profile data. `Comercio` owns
only the foreign-key selection. The later embellecimiento phase may read the
selected active flavor but cannot mutate it or make it a source of business
authority.

## Authoritative outcomes and fallback

| Condition | Outcome |
| --- | --- |
| Existing commerce during migration | Backfilled to `neutro`; FK becomes required |
| New commerce with no explicit flavor | Assigned active `neutro` |
| Admin selects an active known flavor | Only that commerce selection changes |
| Unknown or inactive flavor ID | Validation error; no commerce mutation |
| Flavor instruction is requested through commerce config | Not exposed |
| Any ordinary customer message | Existing deterministic response path unchanged |

No LLM fallback is relevant in this phase because no LLM is called.

## Transaction ownership and privacy

The selection service/repository follows existing caller-owned transaction
ownership: it does not commit or roll back. The authenticated router owns the
normal application transaction boundary. `instruccion_llm` is internal
configuration and must never appear in public/admin response schemas,
diagnostics or exception messages. Customer/pedido content is not read by this
change.

## Expected files

- `backend/models/flavor_comunicacion.py`, `backend/models/comercio.py`, and
  `backend/models/__init__.py`
- one Alembic migration under `backend/alembic/versions/`
- focused repository/service/schema/router modules for communication flavors
  and commerce configuration
- `backend/schemas/comercio.py` and
  `backend/schemas/configuracion_comercio.py`
- focused model, migration, service and FastAPI surface tests
- `openspec/changes/add-global-communication-flavors/**`

## Focused validation

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_comunicacion_flavor_model.py backend/tests/test_comunicacion_flavor_service.py backend/tests/test_comercio_flavor_configuration.py backend/tests/test_configuracion_comercio.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/models/flavor_comunicacion.py backend/models/comercio.py backend/repositories backend/services backend/routers backend/schemas backend/tests/test_comunicacion_flavor_model.py backend/tests/test_comunicacion_flavor_service.py backend/tests/test_comercio_flavor_configuration.py backend/tests/test_configuracion_comercio.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models/flavor_comunicacion.py backend/models/comercio.py backend/repositories backend/services backend/routers backend/schemas
PYTHONPATH=. venv/bin/python -m alembic -c alembic.ini upgrade head
openspec validate add-global-communication-flavors --strict
git diff --check
```

## Rollback and deferred limitations

Before any later LLM activation, rollback consists of reverting this migration
and application release according to the deployment migration policy. The
default `neutro` makes the stored selection behaviorally inert until phase 2.
Editing global profile instructions, administrator UI and styled outbound
responses are deferred.
