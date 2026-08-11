# Proposal: secure order-management API

## Objective

Protect the production HTTP surface that reads or mutates pedidos and their
lines with one application-enforced administrative credential, while keeping
the signed Twilio webhook flow unchanged.

## Current execution path

`backend.main` registers `backend.routers.pedidos` and
`backend.routers.pedido_productos` on the public FastAPI application. Their
routes currently depend only on `get_session`; they expose order reads,
creation, updates, state changes, and line-item mutations without an
application authentication dependency. The pilot used
`PUT /pedidos/{pedido_id}/estado` through the Railway public domain.

The Twilio webhook is a separate public ingress boundary. It authenticates
provider requests with Twilio's signature before lookup or mutation. It must
remain reachable without the administrative credential.

## Scope

- Add one required, configured administrative token and a reusable FastAPI
  dependency that validates it in constant time before a protected handler
  accesses its service or database session.
- Apply that dependency to every route in `pedidos.py` and
  `pedido_productos.py`, including reads. This closes both mutation and order
  data-disclosure paths with the same boundary.
- Default safely: when the configured token is absent, protected routes are
  unavailable for use; startup/settings validation must not reveal a token.
- Preserve existing route paths, request/response models, status-transition
  rules, transaction ownership, business errors, and the WhatsApp/outbox
  processing path.
- Add focused tests for missing, malformed, wrong, correct, and absent-config
  credentials; prove that rejected calls do not invoke services or sessions.

## Non-goals

- No users, roles, JWT, OAuth, sessions, SSO, external identity provider,
  database migration, authorization tables, rate limiting, gateway/proxy
  configuration, or credential rotation workflow.
- No change to Twilio signature validation, webhook routes, provider worker,
  outbox, order-state rules, recognizers, LLMs, or contracts.
- No retention/purge work and no endpoint protection expansion beyond the
  order and order-line routers in this change.

## Shared boundary, outcomes, and fallback

The configured admin token is authoritative for protected HTTP access. A
missing, blank, malformed, or non-matching request credential is an expected
`401 Unauthorized` outcome and must stop before database/session/service work.
There is no fallback to a query parameter, a different header, client identity,
commerce identity, source IP, or permissive local default. A missing server
configuration is a safe technical configuration failure, not an open route.

Twilio's signature remains authoritative only for its own webhook boundary;
the administrative token must not be required or accepted as a substitute for
that signature. Technical configuration/programming failures propagate
normally and must not be represented as successful authorization.

## Transaction ownership and observability

The authorization dependency performs no database work and owns no transaction.
Existing services and callers retain their current commit/rollback behavior.
The implementation must never log the configured value, request credential,
`Authorization` header, or raw request body. It may log only a safe denial
category if the established logging style requires one.

## Expected files

- `backend/config/settings.py` — validated secret setting, with no default
  credential.
- A narrow reusable HTTP authorization dependency module.
- `backend/routers/pedidos.py` and `backend/routers/pedido_productos.py` —
  apply the shared boundary only.
- Focused authorization and impacted router tests.
- `openspec/specs/order-management-api-security/spec.md` after approved
  implementation.

## Focused validation

The implementer must run locally and report complete output:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_order_management_api_security.py backend/tests/test_pedidos_router.py backend/tests/test_pedido_productos_router.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/config/settings.py backend/dependencies.py backend/routers/pedidos.py backend/routers/pedido_productos.py backend/tests/test_order_management_api_security.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/config/settings.py backend/dependencies.py backend/routers/pedidos.py backend/routers/pedido_productos.py
openspec validate secure-order-management-api --strict
```

## Rollback and deferred limitations

Rollback is removing the dependency and the setting from a subsequent approved
deployment; it does not alter persisted data. Rotating the configured token is
an operational Railway secret update followed by service restart/redeploy.
Multi-user identity, roles, proxy controls, rate limiting, and protection of
other legacy administrative routers remain deferred.
