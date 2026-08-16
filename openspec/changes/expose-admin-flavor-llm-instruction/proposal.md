# Proposal: expose LLM flavor instructions to authenticated administrators

## Why

The full outbound-message experiment reads the selected global flavor's
persisted `instruccion_llm` at runtime. Administrators need to inspect the
same durable instruction through the existing protected flavor-catalog API in
order to calibrate a flavor without requiring a code change. The current
`GET /flavors-comunicacion` schema intentionally omits that field, which makes
the applied LLM directive opaque.

## What Changes

- Extend only the existing authenticated `GET /flavors-comunicacion` response
  to include each active flavor's `instruccion_llm`.
- Retain the existing `X-Admin-Token` dependency and active-only list
  behavior.
- Keep `instruccion_llm` absent from all commerce and commerce-configuration
  read models, nested flavor summaries, assignment payloads, logs,
  diagnostics, and errors.
- Add focused API/schema/security regression coverage. No write endpoint is
  introduced: flavor editing remains a direct controlled database operation
  for this phase.

## Objective

Let an authenticated administrator read the precise persisted instruction
used by the outbound stylist, while preserving the commerce-facing safe
summary boundary and avoiding any business, LLM, or persistence behavior
change.

## Current Execution Path

`backend/routers/flavors_comunicacion.py` defines `GET /flavors-comunicacion`
under router-level `require_admin_token`; it maps active catalog rows through
`FlavorComunicacionResponse`. That schema currently serializes only safe
metadata. Commerce and configuration responses instead use
`FlavorComunicacionSummary`, which must remain instruction-free. The outbound
styler reads `FlavorComunicacion.instruccion_llm` directly from the selected
model after deterministic business execution.

## Scope and Non-Goals

In scope: the listing response contract, its documentation and focused tests.

Out of scope: flavor CRUD, PUT/PATCH of `instruccion_llm`, migration/model
changes, admin-panel UI, outbound prompt behavior, LLM calls, customer
responses, commerce assignment, commerce/configuration response expansion,
and diagnostics/logging changes.

## Shared Boundary

The catalog listing is the sole new instruction-reading surface. The list
response may expose the durable instruction only after existing admin-token
authentication. `FlavorComunicacionSummary` remains the shared safe projection
for every commerce/configuration response and never gains this field.

## Authoritative Outcomes and Fallback

| Condition | Outcome |
| --- | --- |
| Valid admin token, active flavor | List item includes the exact persisted instruction |
| Missing/invalid token | Existing generic 401/503 behavior; no catalog/service access |
| Inactive flavor | Not listed, unchanged from current active-only contract |
| Commerce/configuration/assignment response | Instruction remains absent |
| Database/service technical failure | Existing framework error behavior; do not add a text fallback or leak fields |

No LLM fallback applies: this is a read-only API representation change.

## Transaction Ownership and Privacy

The list path stays read-only and must not call commit, rollback, flush,
refresh, begin, begin_nested, or close. The instruction is confidential
administrative configuration: it may appear only in the protected catalog list
body and must not be copied to nested commerce responses, logs, diagnostics,
or exception details.

## Expected Files

- `backend/schemas/comunicacion_flavor.py`
- `backend/routers/flavors_comunicacion.py` only if typing/docs require it
- `backend/tests/test_comunicacion_flavor_service.py`
- `backend/tests/test_comercio_flavor_configuration.py`
- `backend/tests/test_configuracion_comercio.py` only for a narrow no-leak
  regression if existing coverage needs adjustment
- `openspec/changes/expose-admin-flavor-llm-instruction/**`

## Focused Tests

- Protected catalog list includes exactly the persisted non-empty instruction
  for active flavors after auth is overridden in its focused route harness.
- Missing and incorrect admin tokens keep the existing generic rejection and
  do not invoke the list service.
- Inactive flavors remain absent from the list.
- Commerce response, configuration response, nested `FlavorComunicacionSummary`
  and assignment request/response remain instruction-free.
- Listing performs no transaction control and does not alter a flavor row.

## Validation

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_comunicacion_flavor_service.py backend/tests/test_comercio_flavor_configuration.py backend/tests/test_configuracion_comercio.py backend/tests/test_remaining_fastapi_surface_security.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/schemas/comunicacion_flavor.py backend/routers/flavors_comunicacion.py backend/tests/test_comunicacion_flavor_service.py backend/tests/test_comercio_flavor_configuration.py backend/tests/test_configuracion_comercio.py backend/tests/test_remaining_fastapi_surface_security.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/schemas/comunicacion_flavor.py backend/routers/flavors_comunicacion.py
openspec validate expose-admin-flavor-llm-instruction --strict
git diff --check
```

## Rollback and Deferred Limitations

Reverting the response-schema change restores the prior safe-only catalog
list; no data migration or persisted state is involved. Editing instructions
through an API, role granularity beyond the existing admin token, and a panel
editor are deliberately deferred.
