# Proposal: secure remaining FastAPI surface

## Objective

Extend the deployed administrative-token boundary to every remaining FastAPI
route that is not an explicitly public operational or provider-signature
boundary. The change closes unauthenticated reads and mutations outside order
management while preserving health and Twilio ingress.

## Current execution path

`secure-order-management-api` protects the `pedidos` and
`pedido_productos` routers through `require_admin_token`. The remaining API
routers still expose client, session, commerce, catalog, configuration,
incoming-message, and embedding-admin operations without that shared boundary.
Their public domain is reachable in production.

`/health` is an operational availability probe. The Twilio inbound webhook and
delivery callback are public by necessity, but each relies on its existing
Twilio-signature validation contract. They are not administrative API routes.

## Scope

- Define an explicit route classification for every router registered in
  `backend.main`.
- Require the existing `X-Admin-Token` dependency, with its established
  `401`/`503` behavior, on every non-exempt router, including reads.
- Keep only `/health`, the Twilio inbound webhook, and the Twilio delivery
  callback unauthenticated at the application-token layer.
- Preserve the local embedding-admin feature flag as an additional gate; when
  enabled it must also require the admin token.
- Prove protected denials do not open a database session or invoke business
  work, and prove public/provider routes do not gain the admin dependency.

## Non-goals

- No new credential type, users, roles, JWT/OAuth/SSO, gateway/proxy rules,
  rate limiting, database migration, API contract redesign, or token rotation
  automation.
- No change to existing Twilio signature validation, health response, orders,
  outbox, workers, recognizers, LLMs, or business rules.
- No retention/purge work, observability implementation, new intent, or
  catalog/frontend public API in this change.

## Shared boundary, fallback, and transactions

The existing configured admin token remains authoritative for protected routes.
Missing/blank server configuration returns its existing safe `503`; a missing,
blank, malformed, or incorrect request token returns the existing safe `401`.
Neither condition may fall back to client/comercio identity, source address,
query parameter, a different header, or an open route. The dependency is
evaluated before session/service work and owns no database transaction.

Health has no credential fallback because it remains public. Twilio routes use
only their existing signature boundary; an admin token neither replaces nor is
required by that signature. Technical failures propagate to their existing
owners and are not translated into authorization success.

## Observability and privacy

No token, authorization header, raw body, client number, address, or provider
payload may be logged or returned by the new boundary. Reuse the existing
fixed-safe responses. Do not add a telemetry pipeline or persistent audit log.

## Expected files

- Router modules registered by `backend.main`, except the three explicit public
  routers, only where the shared dependency must be attached.
- Focused API-surface classification and authorization tests, plus minimal
  updates to existing router tests needed to provide the authorized dependency.
- This change's three subspec deltas and task list.

## Focused validation

The implementer must run locally and report complete output:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_remaining_fastapi_surface_security.py backend/tests/test_order_management_api_security.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/routers backend/tests/test_remaining_fastapi_surface_security.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/routers backend/tests/test_remaining_fastapi_surface_security.py
openspec validate secure-remaining-fastapi-surface --strict
```

## Rollback and deferred limitations

Rollback removes router-level uses of the existing dependency in a subsequent
approved deployment; no data is changed. Explicit public catalog APIs, fine-
grained roles, identity-provider integration, and gateway controls remain
separate future decisions.
