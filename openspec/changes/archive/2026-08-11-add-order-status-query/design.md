# Design: WhatsApp order-status query

## Authoritative outcomes

| Associated state | Processed status | Persisted effect | Safe response meaning |
| --- | --- | --- | --- |
| No `session.id_pedido`, missing row, or row owned by another session | `rejected` | None | No active order is available to consult |
| `borrador` | `executed` | None | The order is still being assembled and has not been confirmed |
| `ingresado` | `executed` | None | The confirmed order was received |
| `preparacion` | `executed` | None | The confirmed order is in preparation |
| `terminado` | `executed` | None | The order is ready/finished according to existing state semantics |
| `entregado` | `executed` | None | The order is marked delivered |
| `cancelado` | `executed` | None | The order is marked cancelled |
| Technical read/render failure | exception / existing failure handling | Outer owner rolls back the turn | Existing technical retry message only if existing boundary produces one |

The successful `ProcessedIntent.resolved_data` carries only the existing
`estado_pedido` value needed by the response builder. It does not expose
pedido/session/customer/comercio IDs, products, prices, payment, delivery,
address, or timestamps. The rejected result has a stable reason such as
`no_pedido_asociado` or `session_mismatch`, likewise not rendered as technical
detail.

## Execution design

1. The provider coordinator continues to resolve the authoritative
   channel/commerce/client/session and invokes the established message pipeline;
   it does not gain a new path.
2. With `session.context_type is None`, the existing classifier emits the
   already-defined `CONSULTAR_ESTADO_PEDIDO` intent and the initial dispatcher
   delegates it once to the status-query orchestrator.
3. The orchestrator reads only `session.id_pedido`, loads that row directly,
   and verifies its `id_session` equals the supplied conversation session id.
   It neither searches nor selects any alternative pedido.
4. For every defined `EstadoPedido`, it returns an `executed` processed intent
   with the state value. Missing/stale/foreign association returns a
   non-mutating `rejected` intent. The `borrador` result is descriptive only;
   it does not attempt confirmation. Terminal states are likewise descriptive,
   not invitations to transition or create a new order.
5. The existing shared `build_customer_responses` / `stage_outbound_rows`
   boundary invokes the dedicated response builder. Therefore the direct/local
   response and the provider's durable outbox carry identical message, intent,
   status, and ordering.

## Isolation, fallback, and preserved boundaries

`session.id_pedido` plus `Pedido.id_session == session.id` is the complete
authority boundary. The query does not use raw phone numbers, commerce IDs,
channel IDs, client IDs, a latest-order query, or a historical search to fill
an absent association. That preserves commerce isolation and prevents
cross-session disclosure. It does not consult product recognizers or candidate
sets, so Fuzzy/hybrid configuration and existing fallback behavior remain
unchanged.

Any active pending context continues to be resolved before initial
classification. A message asking for status while, for example, product choice
or clear confirmation is pending must not repeat the new intent, clear the
context, or widen candidate IDs. No new state/context is written by a status
query.

The orchestrator and response builder are transaction-neutral and do not
perform response transport. The existing transactional processor owns local
commit/rollback; `ProviderInboundMessageCoordinator.process_lease` owns the
deferred receipt/session/pipeline/outbox commit. A technical failure propagates
to those owners; valid `rejected` outcomes do not cause provider retry or any
fallback lookup.

## Focused tests

Tests shall prove dispatcher delegation of the existing enum; read-only
successful results for each state; safe distinct handling of `borrador`,
post-confirmation states, and both terminal states; missing/missing-row and
session-mismatch rejection without a second lookup; zero mutation and no
transaction-control calls; pending-context priority; deterministic response
text with no sensitive fields; and local/outbox mapper equivalence. Existing
provider/outbox behavior remains covered through the shared mapper boundary;
no live provider test or new test infrastructure is needed.
