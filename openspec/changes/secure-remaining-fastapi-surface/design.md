# Design: secure remaining FastAPI surface

## Decision

Use the deployed `require_admin_token` dependency at router scope for every
administrative router. Router-level attachment prevents future endpoints in a
protected router from accidentally being public and reuses the exact
constant-time comparison, fixed safe outcomes, and no-session-first boundary
already validated for order management.

## Route classification

| Classification | Routers / routes | Boundary |
| --- | --- | --- |
| Public operational | `health` (`/health`) | None |
| Public provider ingress | `twilio_webhook`, `twilio_delivery_callback` | Existing Twilio signature only |
| Administrative | comercios, clientes, sessions, incoming_messages, categorias_productos, presentaciones, productos, precios, configuracion_comercio, producto_queries, medios_pago, metodos_entrega, estados_comercios, admin_product_embeddings | Existing admin token |
| Already administrative | pedidos, pedido_productos | Existing admin token; no behavior change |

The `incoming_messages` HTTP helper is administrative in this phase because it
can invoke the intent pipeline using direct commerce/client identifiers. The
WhatsApp provider path remains its signed webhook and is not affected.

## Error and transaction behavior

Protected routes keep the existing dependency's exact outcomes: `503` when the
server token is missing/blank, `401` for an invalid caller credential. Both
must resolve before `get_session` or service dependencies. The dependency must
not add transactions, session ownership, logs, or response payload fields.

The local embedding-admin feature flag remains evaluated after authorization;
disabled endpoints keep their existing `404` behavior for an authorized
request. This preserves the flag's local-only invisibility while ensuring an
enabled route is not public.

## Test approach

Use a route inventory assertion based on `backend.main` registrations and
FastAPI dependency metadata to prevent accidental omissions. For representative
protected routers covering read, mutation, pipeline entry, and feature-flag
surfaces, assert `401`/`503` cause no session/service work and a valid token
preserves existing behavior. Separately assert `/health` has no admin
dependency and Twilio routers retain no admin dependency.

Existing tests may override the shared dependency with an authorized no-op;
they must not remove or weaken application behavior. No production secret is
allowed in tests.

## Alternatives rejected

- **Global middleware:** would cover public health and signed Twilio routes,
  creating an avoidable outage risk.
- **Protect only mutating methods:** still discloses client/order/catalog data
  and misses direct message processing.
- **Feature flags alone:** do not authenticate enabled routes.
- **A new token:** duplicates the already-deployed boundary without benefit.
