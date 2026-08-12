# Design: secure order-management API

## Decision

Use one application-level admin token supplied in a dedicated request header
and stored only as a Railway secret. A FastAPI dependency performs a
constant-time comparison and is attached at router scope to the existing
pedido and pedido-producto routers. Router-level attachment is deliberately
chosen so new routes in either router inherit the protection by default.

## Boundary

The setting is optional at process load but has no default value. The
authorization dependency treats a missing/blank configured token as a safe
configuration denial (`503 Service Unavailable`) for protected routes, rather
than opening them or preventing unrelated webhook health from starting. A
missing, blank, malformed, or mismatched client credential returns `401` with
a fixed non-sensitive response. The request header is `X-Admin-Token`; no
alternate header or query-string credential is supported.

The dependency must run before `get_session` and the service dependency. The
route declarations therefore order the authorization dependency ahead of the
database/service dependency, and tests assert no session/service work on a
denial. The dependency uses `secrets.compare_digest` on normalized string
inputs, never echoes either value, and does not log request headers.

## Protected routes

All existing routes in these two routers are protected:

- `/pedidos` and `/pedidos/{pedido_id}` including detail and all mutation
  subroutes;
- `/pedidos/{pedido_id}/productos`;
- `/pedidos-productos/{item_id}`.

The change deliberately does not attach the dependency globally. Twilio
webhook and callback routes keep their independent signature-authentication
contracts, and no behavior in their public provider ingress changes.

## Error behavior

| Condition | HTTP result | DB/service work |
| --- | --- | --- |
| Server token absent/blank | 503, fixed safe detail | none |
| Header absent/blank/malformed | 401, fixed safe detail | none |
| Header mismatch | 401, fixed safe detail | none |
| Header matches | existing route behavior | unchanged |

`503` makes a deployment misconfiguration distinct from an attacker/client
credential error and avoids a false suggestion that retrying with another
token can fix missing server configuration. It contains no configuration
detail. No fallback and no retry are performed by the application.

## Transactions and security constraints

The authorization dependency must not import SQLAlchemy, instantiate a
session, call a service, or invoke commit/rollback. Existing routers retain
their current transaction ownership. The token is never placed in a response,
exception, metric label, diagnostic payload, or log record. Tests use synthetic
values only and must not introduce real secret material.

## Alternatives rejected

- **Railway domain obscurity or IP/source checks:** insufficient and not
  application-enforced.
- **A feature flag like the local embedding admin router:** hides routes but
  does not authenticate an enabled production route.
- **Global authentication middleware:** would unintentionally break public
  signed Twilio routes and expands the scope.
- **JWT/OAuth/roles:** stronger identity model, but no provider or user model
  exists today; it exceeds the smallest safe correction.

## Deployment and verification

Before production deployment, set a newly generated secret in Railway as the
configured admin token; do not enter it into source, chat, logs, Swagger
examples, or test fixtures. After deployment, verify a protected route returns
`401` without the header and preserves its established behavior with the
header, using only the authorized test pedido. Verify the existing Twilio
webhook remains signature-governed without the admin header. Rotate the token
if it is ever exposed.
